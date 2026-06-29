"""Sandbox 模块 — 环境抽象 + 文件/shell 工具 (v0.2-2 三层工具模型第二层)。

Sandbox 是执行环境抽象（ABC），LocalSandbox 是默认实现。工具（bash/read/
write/glob/grep）零 I/O 委托 Sandbox 方法。实现通过 SandboxProvider 进程级
单例注入，通过 ContextVar 传递给工具。设计见
docs/implementation-artifacts/v0-2-2-sandbox.md。
"""
from agent_flow_harness.sandbox.base import GrepMatch, Sandbox, SandboxResult
from agent_flow_harness.sandbox.context import (
    SandboxContext,
    get_sandbox_context,
    reset_sandbox_context,
    set_sandbox_context,
)
from agent_flow_harness.sandbox.docker import DockerSandbox, DockerSandboxConfig
from agent_flow_harness.sandbox.local import LocalSandbox
from agent_flow_harness.sandbox.provider import (
    SandboxProvider,
    get_sandbox_provider,
    reset_sandbox_provider,
    set_sandbox_provider,
)
from agent_flow_harness.sandbox.tools import bash, glob, grep, read, write

__all__ = [
    "DockerSandbox",
    "DockerSandboxConfig",
    "GrepMatch",
    "LocalSandbox",
    "Sandbox",
    "SandboxContext",
    "SandboxProvider",
    "SandboxResult",
    "bash",
    "get_sandbox_context",
    "get_sandbox_provider",
    "glob",
    "grep",
    "read",
    "reset_sandbox_context",
    "reset_sandbox_provider",
    "set_sandbox_context",
    "set_sandbox_provider",
    "write",
]
