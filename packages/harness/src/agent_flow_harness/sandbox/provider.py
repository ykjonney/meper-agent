"""SandboxProvider — sandbox 生命周期管理与进程级单例。

与 v0.1 ToolRegistry / checkpointer 同模式：进程级单例，启动时配置。
具体 Provider（Local/Docker/E2B）实现此 ABC。宿主调用 set_sandbox_provider
注入，工具通过 ContextVar 获取 sandbox 实例。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent_flow_harness.sandbox.base import Sandbox


class SandboxProvider(ABC):
    """sandbox 生命周期管理抽象。"""

    @abstractmethod
    def acquire(self, thread_id: str | None = None) -> "Sandbox":
        """获取一个 sandbox 实例。"""
        ...

    @abstractmethod
    def get(self, sandbox_id: str) -> "Sandbox | None":
        """按 id 查找 sandbox。"""
        ...

    @abstractmethod
    def release(self, sandbox_id: str) -> None:
        """释放 sandbox。"""
        ...


# ---------------------------------------------------------------------------
# 进程级单例（与 TOOL_REGISTRY / checkpointer 同模式）
# ---------------------------------------------------------------------------

_default_provider: SandboxProvider | None = None


def set_sandbox_provider(provider: SandboxProvider) -> None:
    """设置进程级 sandbox provider。"""
    global _default_provider
    _default_provider = provider


def get_sandbox_provider() -> SandboxProvider:
    """获取当前 sandbox provider。未设置 raise RuntimeError。"""
    if _default_provider is None:
        msg = (
            "SandboxProvider not set: call set_sandbox_provider() before "
            "using sandbox tools."
        )
        raise RuntimeError(msg)
    return _default_provider


def reset_sandbox_provider() -> None:
    """清除 provider（测试用）。"""
    global _default_provider
    _default_provider = None


__all__ = [
    "SandboxProvider",
    "set_sandbox_provider",
    "get_sandbox_provider",
    "reset_sandbox_provider",
]
