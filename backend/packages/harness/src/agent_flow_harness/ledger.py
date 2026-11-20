"""SideEffectLedger —— 外部副作用账本协议（E5，#71 / 提案 §3.8）。

harness 只定义协议与织入点，不感知存储（Mongo 实现由 app 注入，
维持 harness 可独立发布边界——与 checkpointer 同模式）。

状态机：``prepared → in_progress → succeeded | failed | unknown``，
补偿支线 ``compensation_pending → compensated``。关键语义：

- ``prepare`` 即持久化**原始调用意图**（完整参数 + digest）——恢复裁决
  与回放以持久化意图为准，不假设模型重生成的 tool_call_id 稳定；
- ``unknown``：无法确认外部副作用是否发生（超时/连接中断）——禁止
  默认盲目重试，恢复时由裁决协议处理；
- 命中 ``succeeded`` 的历史调用 → 直接回放记录的结果，不重执行。

无 ExecutionIdentity（legacy chat / 未迁移路径）时账本整体旁路。
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

import structlog

logger = structlog.get_logger(__name__)


class LedgerStatus(StrEnum):
    PREPARED = "prepared"
    IN_PROGRESS = "in_progress"
    SUCCEEDED = "succeeded"
    FAILED = "failed"          # 已确认未产生目标副作用
    UNKNOWN = "unknown"        # 无法确认副作用是否发生
    COMPENSATION_PENDING = "compensation_pending"
    COMPENSATED = "compensated"


@dataclass
class ToolInvocationDraft:
    """prepare 时必须持久化的最小意图集。"""

    tool_call_id: str
    tool_name: str
    args: dict[str, Any]
    idempotency_key: str  # 恢复期稳定：{execution}:{step}:{tool_call_id}
    request_digest: str  # sha256:… —— 回放三匹配校验之一
    tool_version: str | None = None
    step_id: str | None = None


@dataclass
class LedgerRecord:
    """lookup 命中时返回的账本记录（裁决/回放所需字段）。"""

    idempotency_key: str
    status: LedgerStatus
    tool_call_id: str
    tool_name: str
    request_digest: str
    result_summary: str | None = None
    error: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class SideEffectLedger(Protocol):
    """副作用账本协议（实现必须自身容错——账本故障不得阻断工具执行）。"""

    async def prepare(self, draft: ToolInvocationDraft) -> None: ...

    async def claim(self, idempotency_key: str) -> bool: ...

    async def mark(
        self,
        idempotency_key: str,
        status: LedgerStatus,
        *,
        result_summary: str | None = None,
        error: str | None = None,
    ) -> None: ...

    async def lookup(self, idempotency_key: str) -> LedgerRecord | None: ...


class NoLedger:
    """默认空实现：全旁路（未装配/legacy 路径）。"""

    async def prepare(self, draft: ToolInvocationDraft) -> None:  # noqa: ARG002
        return None

    async def claim(self, idempotency_key: str) -> bool:  # noqa: ARG002
        return True

    async def mark(
        self,
        idempotency_key: str,
        status: LedgerStatus,  # noqa: ARG002
        *,
        result_summary: str | None = None,  # noqa: ARG002
        error: str | None = None,  # noqa: ARG002
    ) -> None:
        return None

    async def lookup(self, idempotency_key: str) -> LedgerRecord | None:  # noqa: ARG002
        return None


_ledger: SideEffectLedger = NoLedger()


def set_ledger(ledger: SideEffectLedger) -> None:
    """注入账本实现（app 装配点调用；测试可替换）。"""
    global _ledger  # noqa: PLW0603 - 进程级单例
    _ledger = ledger


def get_ledger() -> SideEffectLedger:
    return _ledger


def digest_args(args: dict[str, Any]) -> str:
    """参数摘要（sha256）——稳定序列化后哈希。"""
    import hashlib
    import json

    canonical = json.dumps(args, sort_keys=True, ensure_ascii=False, default=str)
    return f"sha256:{hashlib.sha256(canonical.encode()).hexdigest()}"


class LedgerClaimError(RuntimeError):
    """调用未获得唯一执行权；调用方不得执行外部副作用。"""


async def ledger_protected_call(
    draft: ToolInvocationDraft,
    execute: "Callable[[], Awaitable[Any]]",
) -> Any:
    """账本包裹的工具执行（make_tool_wrapper 的 awrap 内部使用）。

    状态迁移：prepare → in_progress → succeeded / failed / unknown。
    异常分类（提案 §3.8 恢复裁决的运行侧一半）：
    - ``ToolException``（业务校验失败，外部调用未发出或已确认失败）→ failed
    - 其它异常（连接中断/超时——副作用可能已发生）→ unknown
    - 成功 → succeeded（结果摘要一并持久化，供回放）

    账本操作全部 best-effort：异常只告警，绝不阻断工具执行本身。
    """
    from langchain_core.messages import ToolMessage
    ledger = get_ledger()
    # A durable side-effect ledger is a safety boundary, not best-effort
    # telemetry. If persistence/claim fails, fail closed before the tool runs.
    await ledger.prepare(draft)
    if not await ledger.claim(draft.idempotency_key):
        raise LedgerClaimError(
            f"tool invocation is not claimable: {draft.idempotency_key}"
        )

    try:
        result = await execute()
    except BaseException as exc:
        # 含超时/连接错误与取消——外部副作用可能已发生 → unknown
        try:
            await ledger.mark(
                draft.idempotency_key, LedgerStatus.UNKNOWN, error=str(exc)[:2000]
            )
        except Exception:  # noqa: BLE001
            logger.warning("ledger_mark_unknown_failed", tool=draft.tool_name)
        raise
    else:
        try:
            # Only plain-text ToolMessage results are safely replayable by the
            # current schema. Command/state updates and structured/multimodal
            # payloads must not be flattened into str() and replayed as text.
            if isinstance(result, ToolMessage) and isinstance(result.content, str):
                await ledger.mark(
                    draft.idempotency_key,
                    LedgerStatus.SUCCEEDED,
                    result_summary=result.content[:4000] or None,
                )
            else:
                await ledger.mark(
                    draft.idempotency_key,
                    LedgerStatus.UNKNOWN,
                    error="result_not_replayable_by_current_ledger_schema",
                )
        except Exception:  # noqa: BLE001
            logger.warning("ledger_mark_succeeded_failed", tool=draft.tool_name)
        return result


__all__ = [
    "LedgerClaimError",
    "LedgerRecord",
    "LedgerStatus",
    "NoLedger",
    "SideEffectLedger",
    "ToolInvocationDraft",
    "digest_args",
    "get_ledger",
    "ledger_protected_call",
    "set_ledger",
]
