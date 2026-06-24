"""Tests for WorkspaceManager — session and task workspace isolation.

Story 4-15: Task workspaces are siblings of session workspaces under
``{root}/{user_id}/tasks/{task_id}/``. They are excluded from the
periodic cleanup pass that removes expired session workspaces.
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
# Story 4-15: get_task_workspace / create_task_workspace
# ---------------------------------------------------------------------------


def test_get_task_workspace_path_correct(workspaces_root: Path) -> None:
    """``get_task_workspace`` returns a path under ``{root}/{user_id}/tasks/{task_id}``."""
    ws = WorkspaceManager.get_task_workspace("user_alice", "task_01")
    expected_root = workspaces_root / "user_alice" / "tasks" / "task_01"
    assert ws.root == expected_root
    assert ws.input_dir == expected_root / "input"
    assert ws.output_dir == expected_root / "output"
    assert ws.tmp_dir == expected_root / "tmp"
    assert ws.scope == "task"


def test_create_task_workspace_creates_dirs(workspaces_root: Path) -> None:
    """``create_task_workspace`` materializes input/output/tmp directories."""
    ws = WorkspaceManager.create_task_workspace("user_bob", "task_xyz")
    assert ws.root.is_dir()
    assert ws.input_dir.is_dir()
    assert ws.output_dir.is_dir()
    assert ws.tmp_dir.is_dir()
    # Idempotent: a second call must not raise.
    ws2 = WorkspaceManager.create_task_workspace("user_bob", "task_xyz")
    assert ws2 == ws


def test_task_workspace_isolated_from_session(workspaces_root: Path) -> None:
    """Task and session workspaces are independent directory trees."""
    session_ws = WorkspaceManager.create_workspace("user_carol", "sess_1")
    task_ws = WorkspaceManager.create_task_workspace("user_carol", "task_1")

    # Paths differ.
    assert session_ws.root != task_ws.root
    # task lives under the ``tasks`` container; session does not.
    assert task_ws.root.parent.name == "tasks"
    assert session_ws.root.parent.name == "user_carol"
    # Scopes are reported correctly.
    assert session_ws.scope == "session"
    assert task_ws.scope == "task"


def test_cleanup_skips_tasks_directory(workspaces_root: Path) -> None:
    """``cleanup_expired_workspaces`` must not remove task workspaces."""
    # Create both a session and a task workspace, both long expired.
    session_ws = WorkspaceManager.create_workspace("user_d", "sess_expired")
    task_ws = WorkspaceManager.create_task_workspace("user_d", "task_kept")
    # Put a marker file in each so size > 0.
    (session_ws.output_dir / "old.txt").write_text("old")
    (task_ws.output_dir / "keep.txt").write_text("keep")

    # Force ``now`` to be far in the future so both pass the cutoff.
    # The cleanup function does ``import time`` *inside* the function, so
    # we patch the ``time`` symbol in the standard-library namespace and
    # the local one in workspace module both resolve to the same object.
    import time

    future = time.time() + 10**9
    with patch("time.time", return_value=future):
        result = WorkspaceManager.cleanup_expired_workspaces()

    # The session workspace should be removed.
    assert not session_ws.root.exists()
    # The task workspace must remain — cleanup skips ``tasks/``.
    assert task_ws.root.exists()
    assert (task_ws.output_dir / "keep.txt").exists()
    # Sanity: at least one workspace was removed and zero were task workspaces.
    assert result["workspaces_removed"] >= 1
    # No bytes_freed should be counted for the task directory.
    # (Not strict — we only assert the task file is still on disk.)


def test_cleanup_still_removes_expired_session_sessions(
    workspaces_root: Path,
) -> None:
    """Regression: cleanup must continue to remove expired *session* workspaces."""
    session_ws = WorkspaceManager.create_workspace("user_e", "sess_old")
    (session_ws.output_dir / "data.csv").write_text("a,b,c\n1,2,3\n")

    import time

    future = time.time() + 10**9
    with patch("time.time", return_value=future):
        result = WorkspaceManager.cleanup_expired_workspaces()

    assert not session_ws.root.exists()
    assert result["workspaces_removed"] == 1
    assert result["bytes_freed"] > 0


# ---------------------------------------------------------------------------
# Workspace dataclass — scope field & derived properties
# ---------------------------------------------------------------------------


def test_workspace_scope_default_is_session() -> None:
    """The ``scope`` field defaults to ``"session"`` for backward compatibility."""
    ws = Workspace(
        root=Path("/x/y/user/sess"),
        input_dir=Path("/x/y/user/sess/input"),
        output_dir=Path("/x/y/user/sess/output"),
        tmp_dir=Path("/x/y/user/sess/tmp"),
    )
    assert ws.scope == "session"


def test_workspace_task_id_property() -> None:
    """``task_id`` property returns the directory name when scope is task."""
    ws = Workspace(
        root=Path("/x/y/user/tasks/task_42"),
        input_dir=Path("/x/y/user/tasks/task_42/input"),
        output_dir=Path("/x/y/user/tasks/task_42/output"),
        tmp_dir=Path("/x/y/user/tasks/task_42/tmp"),
        scope="task",
    )
    assert ws.task_id == "task_42"
    assert ws.session_id == ""


def test_workspace_session_id_property() -> None:
    """``session_id`` property returns the directory name when scope is session."""
    ws = Workspace(
        root=Path("/x/y/user/sess_1"),
        input_dir=Path("/x/y/user/sess_1/input"),
        output_dir=Path("/x/y/user/sess_1/output"),
        tmp_dir=Path("/x/y/user/sess_1/tmp"),
    )
    assert ws.session_id == "sess_1"
    assert ws.task_id == ""
