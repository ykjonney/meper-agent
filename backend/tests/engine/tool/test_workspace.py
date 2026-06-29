"""Tests for WorkspaceManager — session workspace isolation & lifecycle.

The harness-era workspace model is session-scoped only: the standalone
"task workspace" concept (``get_task_workspace`` / ``create_task_workspace`` /
``Workspace.scope``) was removed. Task sub-workspaces now live under
``tmp/tasks/{task_id}`` via :meth:`Workspace.tasks_dir`. These tests cover the
current API.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from app.engine.tool.workspace import Workspace, WorkspaceManager


@pytest.fixture
def workspaces_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Point ``WorkspaceManager`` at a temp directory for the test."""
    monkeypatch.setattr(
        "app.engine.tool.workspace.settings.WORKSPACES_CONTAINER_DIR",
        str(tmp_path),
    )
    return tmp_path


# ---------------------------------------------------------------------------
# Workspace creation & path layout
# ---------------------------------------------------------------------------


def test_get_workspace_path_correct(workspaces_root: Path) -> None:
    """``get_workspace`` returns paths under ``{root}/{user_id}/{session_id}``."""
    ws = WorkspaceManager.get_workspace("user_alice", "sess_1")
    expected_root = workspaces_root / "user_alice" / "sess_1"
    assert ws.root == expected_root
    assert ws.input_dir == expected_root / "input"
    assert ws.output_dir == expected_root / "output"
    assert ws.tmp_dir == expected_root / "tmp"


def test_create_workspace_creates_dirs(workspaces_root: Path) -> None:
    """``create_workspace`` materializes input/output/tmp directories."""
    ws = WorkspaceManager.create_workspace("user_bob", "sess_xyz")
    assert ws.root.is_dir()
    assert ws.input_dir.is_dir()
    assert ws.output_dir.is_dir()
    assert ws.tmp_dir.is_dir()
    # Idempotent: a second call must not raise.
    ws2 = WorkspaceManager.create_workspace("user_bob", "sess_xyz")
    assert ws2 == ws


def test_tasks_dir_returns_task_subdir_under_tmp() -> None:
    """``tasks_dir`` returns the task subdirectory under tmp/ (no scope field)."""
    root = Path("/x/y/user/sess")
    ws = Workspace(
        root=root,
        input_dir=root / "input",
        output_dir=root / "output",
        tmp_dir=root / "tmp",
    )
    # Without a task_id, returns the tasks base directory.
    assert ws.tasks_dir() == root / "tmp" / "tasks"
    # With a task_id, returns the task-specific subdirectory.
    assert ws.tasks_dir("task_42") == root / "tmp" / "tasks" / "task_42"


def test_workspace_derived_properties() -> None:
    """user_id / session_id are derived from the path structure."""
    root = Path("/x/y/user_99/sess_abc")
    ws = Workspace(
        root=root,
        input_dir=root / "input",
        output_dir=root / "output",
        tmp_dir=root / "tmp",
    )
    assert ws.user_id == "user_99"
    assert ws.session_id == "sess_abc"


# ---------------------------------------------------------------------------
# Lifecycle cleanup
# ---------------------------------------------------------------------------


def test_cleanup_removes_expired_session_workspaces(workspaces_root: Path) -> None:
    """``cleanup_expired_workspaces`` removes expired session workspaces."""
    session_ws = WorkspaceManager.create_workspace("user_e", "sess_old")
    (session_ws.output_dir / "data.csv").write_text("a,b,c\n1,2,3\n")

    import time

    future = time.time() + 10**9
    with patch("time.time", return_value=future):
        result = WorkspaceManager.cleanup_expired_workspaces()

    assert not session_ws.root.exists()
    assert result["workspaces_removed"] == 1
    assert result["bytes_freed"] > 0
