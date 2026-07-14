"""Workspace context — shared ContextVar for task tools and node executor.

The built-in file/shell tools (bash/read/write/glob/grep) are now provided
by the harness package (``agent_flow_harness.tools.builtin.BUILTIN_TOOLS``)
and injected at runtime by ``harness_integration.context.resolve_harness_context``.

This module retains only the workspace ContextVar that the task/workflow
tools (``workflow_executor._get_workspace``) and the workflow node executor
depend on to resolve the current user/session/task workspace.
"""
from __future__ import annotations

import contextvars

from app.engine.tool.workspace import Workspace

# ---------------------------------------------------------------------------
# Workspace context — set before REACT loop, read by tool implementations
# ---------------------------------------------------------------------------

_current_workspace: contextvars.ContextVar[Workspace | None] = contextvars.ContextVar(
    "current_workspace",
    default=None,
)


def set_workspace_context(workspace) -> contextvars.Token:
    """Set the workspace context for the current async task.

    Returns a token that can be passed to :func:`reset_workspace_context`
    to restore the previous value.
    """
    return _current_workspace.set(workspace)


def reset_workspace_context(token: contextvars.Token) -> None:
    """Restore the workspace context."""
    _current_workspace.reset(token)


def _get_workspace():
    """Return the current workspace or ``None``."""
    return _current_workspace.get()
