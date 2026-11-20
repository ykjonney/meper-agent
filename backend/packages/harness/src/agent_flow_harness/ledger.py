"""SideEffectLedger —— 外部副作用账本协议（E5，#71 / 提案 §3.8）。

harness 只定义协议与织入点，不感知存储（Mongo 实现由 app 注入，
维持 harness 可独立发布边界——与 checkpointer 同模式）。

状态机：``prepared → in_progress → succeeded | failed | unknown``，
补偿支线 ``compensation_pending → compensated``。关键语义：

- ``prepare`` 即持久化**原始调用意图**（完整参数 + digest）。当前 key 使用
  tool_call_id；恢复必须从已持久化的 AIMessage/Graph checkpoint 继续执行原
  ToolCall，不能重新调用模型生成替代 ID。跨 checkpoint 重生成去重仍需 E7
  持久化逻辑 invocation identity，不能由本层自行推导；
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
    idempotency_key: str  # {execution}:{step}:{checkpointed tool_call_id}
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
    """副作用账本协议；持久化/认领失败必须阻止工具执行。"""

    async def prepare(self, draft: ToolInvocationDraft) -> None: ...

    async def claim(self, idempotency_key: str, expected_digest: str) -> bool: ...

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

    async def claim(
        self, idempotency_key: str, expected_digest: str  # noqa: ARG002
    ) -> bool:
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

    状态迁移：prepare → CAS claim → succeeded / unknown。
    任何异常默认 UNKNOWN；只有纯文本 ToolMessage 可安全回放。结构化结果和
    Command 在当前 schema 下记为 UNKNOWN，避免丢失语义后错误回放。
    prepare/claim 失败会在副作用发生前 fail closed。
    """
    from langchain_core.messages import ToolMessage
    ledger = get_ledger()
    # A durable side-effect ledger is a safety boundary, not best-effort
    # telemetry. If persistence/claim fails, fail closed before the tool runs.
    await ledger.prepare(draft)
    # digest 是原子 claim 谓词的一部分（follow-up P1-3）：lookup 瞬态失败
    # 不能让"旧 PREPARED + 不同 digest"的记录被认领后以旧身份执行新参数。
    if not await ledger.claim(draft.idempotency_key, draft.request_digest):
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
        # Only plain-text *success* ToolMessage results are safely
        # replayable. ToolNode converts raised exceptions into
        # ToolMessage(status="error") RETURNED (not raised)——副作用可能
        # 已发生，记 SUCCEEDED 会让恢复把失败当成功回放。Command/结构化
        # 结果同样不可文本化回放 → UNKNOWN。
        #
        # 终态落库 fail-closed（E6 follow-up P1-1）：LeaseLostError 原样
        # 传播（旧 Worker 不得带着失效 token 继续推进）；普通持久化故障
        # 同样上抛——副作用已发生而账本无法落库时，不能把不确定状态
        # 伪装成成功交回 Workflow。记录保持 IN_PROGRESS，恢复侧按
        # UNKNOWN 语义裁决（claim 拒绝重执行，等待显式协议）。
        if (
            isinstance(result, ToolMessage)
            and isinstance(result.content, str)
            and getattr(result, "status", "success") != "error"
        ):
            await ledger.mark(
                draft.idempotency_key,
                LedgerStatus.SUCCEEDED,
                result_summary=result.content[:4000] or None,
            )
        else:
            reason = (
                "tool_returned_error_status"
                if isinstance(result, ToolMessage)
                and getattr(result, "status", "success") == "error"
                else "result_not_replayable_by_current_ledger_schema"
            )
            await ledger.mark(
                draft.idempotency_key,
                LedgerStatus.UNKNOWN,
                error=reason,
            )
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
