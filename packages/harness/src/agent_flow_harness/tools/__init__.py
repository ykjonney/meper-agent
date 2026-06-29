"""Harness tools — registry, community protocol, workspace context, builtins.

Public surface:

* :class:`ToolRegistry` / :data:`TOOL_REGISTRY` — the global tool registry.
* :class:`CommunityTool` — protocol for third-party pluggable tools.
* :data:`BUILTIN_TOOLS` / :data:`BUILTIN_TOOL_NAMES` — harness built-in tools
  (lazy; accessed via module __getattr__ to avoid import cycles).
* Workspace context-var plumbing.

The built-in tools are lazy-loaded (PEP 562) because they pull in the
sandbox/subagents/interaction subpackages, which would otherwise cycle.
"""

from agent_flow_harness.tools.community import CommunityTool
from agent_flow_harness.tools.registry import TOOL_REGISTRY, ToolRegistry
from agent_flow_harness.tools.resolver import resolve_variable
from agent_flow_harness.tools.workspace_context import (
    WorkspaceProtocol,
    get_workspace_context,
    reset_workspace_context,
    set_workspace_context,
)


def __getattr__(name: str):
    """Lazy-load BUILTIN_TOOLS / BUILTIN_TOOL_NAMES to avoid import cycles."""
    if name in ("BUILTIN_TOOLS", "BUILTIN_TOOL_NAMES"):
        from agent_flow_harness.tools import builtin as _builtin

        return getattr(_builtin, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "BUILTIN_TOOL_NAMES",
    "BUILTIN_TOOLS",
    "CommunityTool",
    "TOOL_REGISTRY",
    "ToolRegistry",
    "WorkspaceProtocol",
    "get_workspace_context",
    "reset_workspace_context",
    "resolve_variable",
    "set_workspace_context",
]
