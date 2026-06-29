"""SandboxContext + ContextVar — sandbox 工具的依赖注入协议。

与 v0.1 workspace_context / v0.2-1 subagent_context 同模式：宿主在每次
主 Agent 执行前 set_sandbox_context()，bash/read/write/glob/grep 工具
内部 get_sandbox_context() 读取。ContextVar 保证异步任务隔离。
"""
from __future__ import annotations

import contextvars
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent_flow_harness.sandbox.base import Sandbox


@dataclass
class SandboxContext:
    """工具执行时的 sandbox 依赖。"""

    sandbox: "Sandbox"


_sandbox_ctx: contextvars.ContextVar[SandboxContext | None] = contextvars.ContextVar(
    "sandbox_ctx", default=None
)


def set_sandbox_context(ctx: SandboxContext) -> "contextvars.Token[SandboxContext | None]":
    return _sandbox_ctx.set(ctx)


def reset_sandbox_context(token: "contextvars.Token[SandboxContext | None]") -> None:
    _sandbox_ctx.reset(token)


def get_sandbox_context() -> SandboxContext:
    """读取当前 sandbox context。未设置 raise RuntimeError。"""
    ctx = _sandbox_ctx.get()
    if ctx is None:
        msg = (
            "SandboxContext not set: call set_sandbox_context() before "
            "invoking sandbox tools (bash/read/write/glob/grep)."
        )
        raise RuntimeError(msg)
    return ctx


__all__ = [
    "SandboxContext",
    "set_sandbox_context",
    "reset_sandbox_context",
    "get_sandbox_context",
]
