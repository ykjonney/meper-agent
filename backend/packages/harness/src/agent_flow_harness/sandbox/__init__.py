"""Sandbox 模块 — 环境抽象 + 文件/shell 工具 (v0.2-2 三层工具模型第二层)。

Sandbox 是执行环境抽象（ABC），LocalSandbox 是默认实现。工具（bash/read/
write/glob/grep）零 I/O 委托 Sandbox 方法，sandbox 实例通过 ContextVar
传递给工具。设计见 docs/implementation-artifacts/v0-2-2-sandbox.md。
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
from agent_flow_harness.sandbox.tools import bash, glob, grep, read, write

__all__ = [
    "DockerSandbox",
    "DockerSandboxConfig",
    "GrepMatch",
    "LocalSandbox",
    "Sandbox",
    "SandboxContext",
    "SandboxResult",
    "bash",
    "get_sandbox_context",
    "glob",
    "grep",
    "read",
    "reset_sandbox_context",
    "set_sandbox_context",
    "write",
]
