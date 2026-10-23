"""三态熔断器测试:CLOSED → OPEN → HALF_OPEN → 恢复/冷却翻倍 全周期。

设计语义(见 compact_circuit.py 模块注释):
- 熔断 = 降级运行(跳过摘要,只剩截断+丢弃),不是报错;
- 永久熔断是错的——瞬时故障会自愈、outer 会随任务长大,冷却期满
  必须放行试探;
- 冷却期指数退避(120→240→480 封顶)。
"""
from __future__ import annotations

from agent_flow_harness.context_engineering.compact_circuit import (
    CircuitBreaker,
)


class _FakeClock:
    """可推进的单调时钟(测试注入)。"""

    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def _breaker() -> tuple[CircuitBreaker, _FakeClock]:
    clock = _FakeClock()
    breaker = CircuitBreaker(
        failure_threshold=3,
        initial_cooldown_s=120.0,
        max_cooldown_s=480.0,
        _clock=clock,
    )
    return breaker, clock


# ---------------------------------------------------------------------------
# CLOSED → OPEN
# ---------------------------------------------------------------------------


def test_initial_state_allows_try() -> None:
    breaker, _ = _breaker()
    assert breaker.should_try("s1") is True


def test_failures_below_threshold_stay_closed() -> None:
    """失败 1~2 次仍在 CLOSED,继续放行。"""
    breaker, _ = _breaker()
    breaker.record_failure("s1")
    breaker.record_failure("s1")
    assert breaker.should_try("s1") is True


def test_three_consecutive_failures_open_circuit() -> None:
    """连续 3 次失败 → OPEN,冷却期内一律跳过(降级运行)。"""
    breaker, _ = _breaker()
    for _ in range(3):
        breaker.record_failure("s1")
    assert breaker.should_try("s1") is False


def test_success_resets_failure_streak() -> None:
    """成功清零计数:失败2次+成功1次+失败2次 → 仍 CLOSED。"""
    breaker, _ = _breaker()
    breaker.record_failure("s1")
    breaker.record_failure("s1")
    breaker.record_success("s1")
    breaker.record_failure("s1")
    breaker.record_failure("s1")
    assert breaker.should_try("s1") is True  # 未到连续 3 次


# ---------------------------------------------------------------------------
# OPEN → HALF_OPEN → CLOSED / OPEN(翻倍)
# ---------------------------------------------------------------------------


def test_cooldown_expiry_allows_probe_and_recovery() -> None:
    """冷却期满 → 放行试探(HALF_OPEN) → 试探成功 → CLOSED 恢复。"""
    breaker, clock = _breaker()
    for _ in range(3):
        breaker.record_failure("s1")
    clock.advance(120.0)  # 冷却期(120s)到点
    assert breaker.should_try("s1") is True  # HALF_OPEN 放行一次
    breaker.record_success("s1")
    assert breaker.should_try("s1") is True  # 已回 CLOSED
    assert breaker.success_count("s1") == 1


def test_probe_failure_doubles_cooldown() -> None:
    """试探失败 → 回 OPEN 且冷却翻倍:120s 到点仍熔断,240s 才放行。"""
    breaker, clock = _breaker()
    for _ in range(3):
        breaker.record_failure("s1")
    clock.advance(120.0)
    assert breaker.should_try("s1") is True  # HALF_OPEN
    breaker.record_failure("s1")  # 试探失败
    clock.advance(120.0)
    assert breaker.should_try("s1") is False  # 翻倍后的冷却(240s)未满
    clock.advance(120.0)  # 累计 240s
    assert breaker.should_try("s1") is True


def test_cooldown_capped_at_max() -> None:
    """多次试探失败后冷却封顶 480s,不再翻倍。"""
    breaker, clock = _breaker()
    for _ in range(3):
        breaker.record_failure("s1")  # → OPEN(冷却 120s)
    cooldowns: list[float] = []
    for _ in range(4):
        # 推进到刚好到期(每次试探失败后冷却翻倍:120→240→480→480)。
        waited = 0.0
        while not breaker.should_try("s1"):
            clock.advance(10.0)
            waited += 10.0
        cooldowns.append(waited)
        breaker.record_failure("s1")  # 试探失败
    assert cooldowns == [120.0, 240.0, 480.0, 480.0]


def test_sessions_isolated() -> None:
    """per-session 隔离:s1 熔断不影响 s2。"""
    breaker, _ = _breaker()
    for _ in range(3):
        breaker.record_failure("s1")
    assert breaker.should_try("s1") is False
    assert breaker.should_try("s2") is True


def test_empty_session_id_never_tries() -> None:
    """空 session_id 无法计数熔断,直接不允许(与旧后台摘要条件一致)。"""
    breaker, _ = _breaker()
    assert breaker.should_try("") is False


def test_reset_clears_state() -> None:
    breaker, _ = _breaker()
    for _ in range(3):
        breaker.record_failure("s1")
    breaker.reset("s1")
    assert breaker.should_try("s1") is True
