"""Session workspace manager — per-Session file isolation.

Each Session gets an independent workspace directory tree::

    {WORKSPACES_DIR}/{user_id}/{session_id}/
        input/      ← user-uploaded attachments
        output/     ← Agent-generated downloadable files
        tmp/        ← bash execution working area (sandbox mount point)

Task workspaces (Story 4-15) live alongside session workspaces::

    {WORKSPACES_DIR}/{user_id}/tasks/{task_id}/
        input/      ← (reserved for future)
        output/     ← Agent node files registered to file_library on completion
        tmp/        ← bash scratch for Agent tools

The workspace provides file isolation between users and sessions,
preventing cross-contamination when multiple users run Agents concurrently.
"""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from app.core.config import settings


@dataclass(frozen=True)
class Workspace:
    """Resolved paths for a Session or Task workspace.

    Story 4-15: Added ``scope`` to distinguish Session workspaces (lifecycle
    tied to chat session) from Task workspaces (lifecycle tied to Task).
    Defaults to ``"session"`` for backward compatibility — all existing
    callers and test fixtures continue to work.
    """

    root: Path
    input_dir: Path
    output_dir: Path
    tmp_dir: Path
    scope: str = "session"  # "session" | "task"

    @property
    def user_id(self) -> str:
        """Extract user_id from the workspace path structure.

        For session scope the path is ``.../{user_id}/{session_id}``; for
        task scope the path is ``.../{user_id}/tasks/{task_id}``.  In both
        cases the user_id is the *grandparent's* parent name (the directory
        immediately under the workspaces root).
        """
        return self.root.parent.parent.name if self.scope == "task" else self.root.parent.name

    @property
    def session_id(self) -> str:
        """Extract session_id from the workspace path structure (session only)."""
        if self.scope != "session":
            return ""
        return self.root.name

    @property
    def task_id(self) -> str:
        """Extract task_id from the workspace path structure (task only)."""
        if self.scope != "task":
            return ""
        return self.root.name

    def tasks_dir(self, task_id: str | None = None) -> Path:
        """Return the tasks directory, optionally for a specific task."""
        base = self.tmp_dir / "tasks"
        if task_id:
            return base / task_id
        return base


class WorkspaceManager:
    """Manage per-Session workspace directories on the local filesystem."""

    @staticmethod
    def _workspaces_root() -> Path:
        """Return the configured workspaces root directory (expanded)."""
        return Path(settings.WORKSPACES_CONTAINER_DIR).expanduser()

    @staticmethod
    def get_workspace(user_id: str, session_id: str) -> Workspace:
        """Return a :class:`Workspace` object for an existing or new session.

        Does **not** create the directories — call :meth:`create_workspace`
        to ensure they exist on disk.
        """
        root = WorkspaceManager._workspaces_root() / user_id / session_id
        return Workspace(
            root=root,
            input_dir=root / "input",
            output_dir=root / "output",
            tmp_dir=root / "tmp",
        )

    @staticmethod
    def create_workspace(user_id: str, session_id: str) -> Workspace:
        """Create the workspace directory tree for a Session.

        Idempotent — existing directories are not replaced.

        Args:
            user_id: Owner user ID.
            session_id: Session ID.

        Returns:
            The created :class:`Workspace`.
        """
        ws = WorkspaceManager.get_workspace(user_id, session_id)

        for d in (ws.input_dir, ws.output_dir, ws.tmp_dir):
            d.mkdir(parents=True, exist_ok=True)

        logger.info(
            "workspace_created",
            user_id=user_id,
            session_id=session_id,
            path=str(ws.root),
        )
        return ws

    @staticmethod
    def get_task_workspace(user_id: str, task_id: str) -> Workspace:
        """Return a :class:`Workspace` for a Task.

        Story 4-15: Task workspaces are siblings of session workspaces
        (``{root}/{user_id}/tasks/{task_id}/``), not nested under any
        session. This keeps Agent node output file lifecycle tied to the
        Task rather than any specific chat session.

        Does **not** create the directories — call
        :meth:`create_task_workspace` to ensure they exist on disk.

        Args:
            user_id: Owner user ID.
            task_id: Task ID (Task._id, ULID).

        Returns:
            The :class:`Workspace` object (without creating directories).
        """
        root = WorkspaceManager._workspaces_root() / user_id / "tasks" / task_id
        return Workspace(
            root=root,
            input_dir=root / "input",
            output_dir=root / "output",
            tmp_dir=root / "tmp",
            scope="task",
        )

    @staticmethod
    def create_task_workspace(user_id: str, task_id: str) -> Workspace:
        """Create the workspace directory tree for a Task.

        Idempotent — existing directories are not replaced.

        Args:
            user_id: Owner user ID.
            task_id: Task ID (Task._id, ULID).

        Returns:
            The created :class:`Workspace` with ``scope='task'``.
        """
        ws = WorkspaceManager.get_task_workspace(user_id, task_id)

        for d in (ws.input_dir, ws.output_dir, ws.tmp_dir):
            d.mkdir(parents=True, exist_ok=True)

        logger.info(
            "task_workspace_created",
            user_id=user_id,
            task_id=task_id,
            path=str(ws.root),
        )
        return ws

    @staticmethod
    def safe_resolve_path(base: Path, user_path: str) -> Path | None:
        """Resolve a user-supplied path safely within a base directory.

        Prevents path traversal attacks (``..`` components, absolute paths
        that escape the base, symlink escapes).

        Args:
            base: The allowed root directory (e.g. workspace root).
            user_path: The user-supplied relative path.

        Returns:
            The resolved absolute :class:`Path` if it stays within *base*,
            or ``None`` if it escapes.
        """
        # Reject absolute paths that point outside the base
        if os.path.isabs(user_path):
            resolved = Path(os.path.realpath(user_path))
        else:
            resolved = Path(os.path.realpath(str(base / user_path)))

        base_resolved = Path(os.path.realpath(str(base)))

        # Check the resolved path is within the base directory
        try:
            resolved.relative_to(base_resolved)
            return resolved
        except ValueError:
            return None

    @staticmethod
    def safe_resolve_workspace_path(
        workspace: Workspace,
        user_path: str,
        *,
        allow_skills_read: bool = False,
    ) -> Path | None:
        """Resolve a path within a workspace, with optional Skill read access.

        Args:
            workspace: The Session workspace.
            user_path: The user-supplied relative path.
            allow_skills_read: If True, also allow read access to SKILLS_DIR.

        Returns:
            Resolved :class:`Path` or ``None`` if access is denied.
        """
        # First try within the workspace
        resolved = WorkspaceManager.safe_resolve_path(workspace.root, user_path)
        if resolved is not None:
            return resolved

        # Optionally allow read access to Skill files
        if allow_skills_read:
            skills_root = Path(settings.SKILLS_CONTAINER_DIR).expanduser()
            resolved = WorkspaceManager.safe_resolve_path(skills_root, user_path)
            if resolved is not None:
                return resolved

        return None

    @staticmethod
    def delete_workspace(user_id: str, session_id: str) -> bool:
        """Remove a workspace directory tree.

        Args:
            user_id: Owner user ID.
            session_id: Session ID.

        Returns:
            ``True`` if the directory existed and was removed.
        """
        ws = WorkspaceManager.get_workspace(user_id, session_id)
        if not ws.root.exists():
            return False

        shutil.rmtree(ws.root)
        logger.info(
            "workspace_deleted",
            user_id=user_id,
            session_id=session_id,
        )
        return True

    @staticmethod
    def delete_task_workspace(user_id: str, task_id: str) -> bool:
        """Remove a Task workspace directory tree.

        Args:
            user_id: Owner user ID.
            task_id: Task ID.

        Returns:
            ``True`` if the directory existed and was removed.
        """
        ws = WorkspaceManager.get_task_workspace(user_id, task_id)
        if not ws.root.exists():
            return False

        shutil.rmtree(ws.root)
        logger.info(
            "task_workspace_deleted",
            user_id=user_id,
            task_id=task_id,
        )
        return True

    @staticmethod
    def delete_user_workspace(user_id: str) -> bool:
        """Remove the entire workspace directory tree for a user.

        Deletes ``{WORKSPACES_ROOT}/{user_id}/`` and everything under it
        (sessions, tasks, files). Used during user deletion cascade.

        Args:
            user_id: Owner user ID.

        Returns:
            ``True`` if the directory existed and was removed.
        """
        user_root = WorkspaceManager._workspaces_root() / user_id
        if not user_root.exists():
            return False
        shutil.rmtree(user_root)
        logger.info("user_workspace_deleted", user_id=user_id)
        return True

    @staticmethod
    def get_workspace_size(workspace: Workspace) -> int:
        """Calculate the total size of all files in a workspace (bytes)."""
        total = 0
        if workspace.root.exists():
            for p in workspace.root.rglob("*"):
                if p.is_file():
                    total += p.stat().st_size
        return total

    @staticmethod
    def check_quota(workspace: Workspace, additional_bytes: int = 0) -> bool:
        """Check whether writing *additional_bytes* would exceed the quota.

        Returns:
            ``True`` if within quota, ``False`` if exceeded.
        """
        current = WorkspaceManager.get_workspace_size(workspace)
        return (current + additional_bytes) <= settings.WORKSPACE_MAX_BYTES

    @staticmethod
    def list_output_files(workspace: Workspace) -> list[dict]:
        """List files in the output/ directory for download.

        Returns:
            List of dicts with ``path`` (relative to output/), ``size``,
            and ``modified`` keys.
        """
        if not workspace.output_dir.exists():
            return []

        entries: list[dict] = []
        for p in sorted(workspace.output_dir.rglob("*")):
            if not p.is_file():
                continue
            rel = p.relative_to(workspace.output_dir)
            stat = p.stat()
            entries.append({
                "path": str(rel),
                "size": stat.st_size,
                "modified": stat.st_mtime,
            })
        return entries

    # ── Lifecycle cleanup ───────────────────────────────────────────────

    @staticmethod
    def cleanup_expired_workspaces(
        tmp_retention_days: int | None = None,
        full_retention_days: int | None = None,
    ) -> dict:
        """Remove expired workspace files.

        Strategy:
          - ``tmp/`` is cleaned when older than *tmp_retention_days* (default:
            ``WORKSPACE_RETENTION_DAYS / 2``).
          - The entire workspace is removed when older than *full_retention_days*
            (default: ``WORKSPACE_RETENTION_DAYS``).

        Only directories with a valid ``{user_id}/{session_id}`` structure are
        considered.  Partial / orphan directories are left untouched.

        Returns:
            Summary dict with ``tmp_cleaned``, ``workspaces_removed``, and
            ``bytes_freed``.
        """
        import time

        tmp_days = tmp_retention_days or max(settings.WORKSPACE_RETENTION_DAYS // 2, 1)
        full_days = full_retention_days or settings.WORKSPACE_RETENTION_DAYS

        tmp_cutoff = time.time() - (tmp_days * 86400)
        full_cutoff = time.time() - (full_days * 86400)

        root = WorkspaceManager._workspaces_root()
        if not root.exists():
            return {"tmp_cleaned": 0, "workspaces_removed": 0, "bytes_freed": 0}

        tmp_cleaned = 0
        workspaces_removed = 0
        bytes_freed = 0

        for user_dir in root.iterdir():
            if not user_dir.is_dir():
                continue
            for session_dir in user_dir.iterdir():
                if not session_dir.is_dir():
                    continue
                # Story 4-15: skip task workspace container — task workspaces
                # have their own lifecycle and are not managed by this cleanup
                # pass. They live at ``{user_dir}/tasks/{task_id}`` and are
                # siblings of session workspaces, not children.
                if session_dir.name == "tasks":
                    continue

                # Get workspace mtime (latest modification in the tree)
                try:
                    ws_mtime = _get_dir_mtime(session_dir)
                except OSError:
                    continue

                # Full removal
                if ws_mtime < full_cutoff:
                    size = _dir_size(session_dir)
                    shutil.rmtree(session_dir, ignore_errors=True)
                    workspaces_removed += 1
                    bytes_freed += size
                    logger.info(
                        "workspace_cleanup_removed",
                        user_id=user_dir.name,
                        session_id=session_dir.name,
                        bytes_freed=size,
                    )
                    continue

                # tmp/ cleanup (only if tmp is old enough)
                tmp_dir = session_dir / "tmp"
                if tmp_dir.exists():
                    try:
                        tmp_mtime = _get_dir_mtime(tmp_dir)
                    except OSError:
                        tmp_mtime = ws_mtime

                    if tmp_mtime < tmp_cutoff:
                        size = _dir_size(tmp_dir)
                        shutil.rmtree(tmp_dir, ignore_errors=True)
                        tmp_dir.mkdir(parents=True, exist_ok=True)
                        tmp_cleaned += 1
                        bytes_freed += size

        logger.info(
            "workspace_cleanup_completed",
            tmp_cleaned=tmp_cleaned,
            workspaces_removed=workspaces_removed,
            bytes_freed=bytes_freed,
        )
        return {
            "tmp_cleaned": tmp_cleaned,
            "workspaces_removed": workspaces_removed,
            "bytes_freed": bytes_freed,
        }


# ── Module-level helpers ──────────────────────────────────────────────────────


def _dir_size(path: Path) -> int:
    """Calculate total size of all files under *path*."""
    total = 0
    for p in path.rglob("*"):
        if p.is_file():
            total += p.stat().st_size
    return total


def _get_dir_mtime(path: Path) -> float:
    """Return the most recent mtime of any file under *path*."""
    latest = path.stat().st_mtime
    for p in path.rglob("*"):
        if p.is_file():
            mt = p.stat().st_mtime
            if mt > latest:
                latest = mt
    return latest
