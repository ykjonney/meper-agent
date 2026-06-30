"""Workspace context variable for tool isolation.

Set before the REACT loop begins (using the workspace injected into
``AgentState`` by the host application) and read by the built-in tools
(``read``, ``write``, ``bash``) to enforce path isolation.

The harness only owns the *context-var plumbing*; the workspace object
itself is supplied by the host application (which knows how to create
and persist sessions).  The object must satisfy :class:`WorkspaceProtocol`.
"""

from __future__ import annotations

import contextvars
from typing import Any, Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# Workspace protocol (duck-typed — any object with the listed members works)
# ---------------------------------------------------------------------------


@runtime_checkable
class WorkspaceProtocol(Protocol):
    """Minimal surface area that a workspace object must expose.

    The harness never imports the concrete backend Workspace class; it
    only touches these attributes.
    """

    user_id: str
    session_id: str
    input_dir: Any  # pathlib.Path (or compatible)
    output_dir: Any
    tmp_dir: Any


# ---------------------------------------------------------------------------
# Context var
# ---------------------------------------------------------------------------

_current_workspace: contextvars.ContextVar[WorkspaceProtocol | None] = (
    contextvars.ContextVar("current_workspace", default=None)
)


def set_workspace_context(workspace: WorkspaceProtocol | None) -> contextvars.Token[Any]:
    """Set the workspace for the current async task and return a reset token."""
    return _current_workspace.set(workspace)


def reset_workspace_context(token: contextvars.Token[Any]) -> None:
    """Restore the previous workspace context."""
    _current_workspace.reset(token)


def get_workspace_context() -> WorkspaceProtocol | None:
    """Return the current workspace (or ``None`` when not set)."""
    return _current_workspace.get()
