"""ExecutionIdentity —— 执行身份的 contextvar 传播（E5）。

工具执行链深处（tool_wrapper）无法直接拿到 execution/step 身份；
与 sandbox workspace contextvar 同模式，调用方（Adapter/node_executor）
在执行入口 set，账本据此构造稳定幂等键。

无身份时（legacy chat / 未迁移路径）账本整体旁路。
"""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass

_current: ContextVar["ExecutionIdentity | None"] = ContextVar(
    "agent_flow_execution_identity", default=None
)


@dataclass(frozen=True)
class ExecutionIdentity:
    """当前逻辑执行的标识（harness 侧只需要这三个字段）。"""

    execution_id: str
    step_id: str | None = None
    # E6/E7 起 token 随 lease 提供；E5 影子期为 None（账本写不 fencing）
    fencing_token: int | None = None

    @property
    def idempotency_prefix(self) -> str:
        step = self.step_id or "root"
        return f"{self.execution_id}:{step}"

    def tool_idempotency_key(self, tool_call_id: str) -> str:
        return f"{self.idempotency_prefix}:{tool_call_id}"


def set_execution_identity(identity: ExecutionIdentity | None) -> None:
    """绑定/清除当前任务的执行身份（Adapter 执行入口调用）。"""
    _current.set(identity)


def get_execution_identity() -> ExecutionIdentity | None:
    return _current.get()


__all__ = ["ExecutionIdentity", "get_execution_identity", "set_execution_identity"]
