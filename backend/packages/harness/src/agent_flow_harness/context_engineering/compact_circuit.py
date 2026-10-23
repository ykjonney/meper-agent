"""三态熔断器 — LLM 摘要的成本保护(防 thrashing)。

状态机::

    CLOSED(正常) ──连续 failure_threshold 次失败/无进展──▶ OPEN(冷却期)
    OPEN ──冷却期满──▶ HALF_OPEN(放行一次试探)
    HALF_OPEN ──成功且有进展──▶ CLOSED(计数清零)
    HALF_OPEN ──失败──▶ OPEN(冷却期指数翻倍,封顶 max_cooldown_s)

设计依据(Claude Code thrashing 教训):固定占用过大时摘要永远压不掉,
无限重试 = 每轮白烧一次摘要调用。但**永久**禁用会误杀两类会自愈的场景
——provider 瞬时故障恢复 / outer 随任务推进长大(任务初期 outer 小压不动,
几十轮后 outer 膨胀、摘要重新有效)——故冷却期满后放行一次试探。

熔断状态是**成本优化状态而非正确性状态**:进程内 per-session,
不持久化、跨进程丢失无害(最坏结果是重新计数三次再熔断)。
"""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum

import structlog

logger = structlog.get_logger(__name__)

INITIAL_COOLDOWN_S = 120.0
"""首次熔断的冷却期(秒);此后每次试探失败翻倍,封顶 MAX_COOLDOWN_S。"""

MAX_COOLDOWN_S = 480.0
"""冷却期封顶(秒)——结构性无解场景下摘要调用频率随之收敛到近零。"""


class CircuitState(Enum):
    CLOSED = "closed"      # 正常:每次都放行
    OPEN = "open"          # 熔断:冷却期内一律跳过(降级为截断+丢弃)
    HALF_OPEN = "half_open"  # 试探:放行一次,成败决定回 CLOSED 还是回 OPEN


@dataclass
class _SessionCircuit:
    """单个 session(thread)的熔断器状态。"""

    state: CircuitState = CircuitState.CLOSED
    consecutive_failures: int = 0
    cooldown_seconds: float = INITIAL_COOLDOWN_S
    cooldown_deadline: float = 0.0
    success_count: int = 0
    """累计成功摘要次数(可观测:一个 session 被压了几次,对齐 Codex 的
    多轮压缩降质警告)。"""


@dataclass
class CircuitBreaker:
    """三态熔断器(per-session dict 管理)。

    Args:
        failure_threshold: 连续失败/无进展多少次后熔断(Claude Code 同款 3)。
        initial_cooldown_s: 首次冷却期。
        max_cooldown_s: 冷却期封顶(指数退避翻倍)。
        clock: 时间源(time.monotonic 默认;测试可注入假时钟)。
    """

    failure_threshold: int = 3
    initial_cooldown_s: float = INITIAL_COOLDOWN_S
    max_cooldown_s: float = MAX_COOLDOWN_S
    _sessions: dict[str, _SessionCircuit] = field(default_factory=dict)
    _clock: Callable[[], float] = field(default=time.monotonic, repr=False)

    # ── 查询门闸 ──────────────────────────────────────────────────────

    def should_try(self, session_id: str) -> bool:
        """是否允许发起一次摘要尝试(含 OPEN→HALF_OPEN 的到期转移)。"""
        if not session_id:
            return False
        sc = self._sessions.get(session_id)
        if sc is None:
            return True
        if sc.state is CircuitState.OPEN:
            if self._clock() >= sc.cooldown_deadline:
                sc.state = CircuitState.HALF_OPEN
                logger.info(
                    "compact_circuit_half_open",
                    session_id=session_id,
                    cooldown_seconds=sc.cooldown_seconds,
                )
                return True
            return False
        return True  # CLOSED / HALF_OPEN 均放行(record_* 收尾状态)。

    def success_count(self, session_id: str) -> int:
        """该 session 累计成功摘要次数(compact_count 可观测)。"""
        sc = self._sessions.get(session_id)
        return sc.success_count if sc else 0

    # ── 结果回报 ──────────────────────────────────────────────────────

    def record_success(self, session_id: str) -> None:
        """摘要成功且有进展 → 回 CLOSED,计数清零,累计 +1。"""
        sc = self._sessions.get(session_id)
        if sc is None:
            sc = _SessionCircuit()
            self._sessions[session_id] = sc
        if sc.state is not CircuitState.CLOSED:
            logger.info(
                "compact_circuit_recovered",
                session_id=session_id,
                previous_state=sc.state.value,
            )
        sc.state = CircuitState.CLOSED
        sc.consecutive_failures = 0
        sc.cooldown_seconds = self.initial_cooldown_s
        sc.success_count += 1

    def record_failure(self, session_id: str) -> None:
        """摘要失败/无进展 → 计数;满阈值转 OPEN(冷却期翻倍)。"""
        sc = self._sessions.get(session_id)
        if sc is None:
            sc = _SessionCircuit()
            self._sessions[session_id] = sc
        sc.consecutive_failures += 1
        if sc.state is CircuitState.HALF_OPEN or sc.consecutive_failures >= self.failure_threshold:
            sc.state = CircuitState.OPEN
            sc.cooldown_deadline = self._clock() + sc.cooldown_seconds
            logger.warning(
                "compact_circuit_open",
                session_id=session_id,
                consecutive_failures=sc.consecutive_failures,
                cooldown_seconds=sc.cooldown_seconds,
                note="摘要连续失败/无进展,冷却期内降级为截断+丢弃",
            )
            sc.cooldown_seconds = min(
                sc.cooldown_seconds * 2, self.max_cooldown_s,
            )
            sc.consecutive_failures = 0  # OPEN 期间不再计数;HALF_OPEN 重来。

    def reset(self, session_id: str) -> None:
        """清掉 session 状态(测试/会话结束时用)。"""
        self._sessions.pop(session_id, None)


# 模块级单例:进程内共享(成本优化状态,不持久化)。
compact_circuit = CircuitBreaker()


__all__ = [
    "CircuitBreaker",
    "CircuitState",
    "compact_circuit",
]
