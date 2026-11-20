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
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from agent_flow_harness.workspace import WorkspaceLayout

from app.core.config import settings


def sandbox_bind_source_mapper() -> Callable[[str], str] | None:
    """容器视角路径 → docker daemon 宿主视角路径（bind mount 源换算）。

    backend 容器化部署时进程看到 WORKSPACES_CONTAINER_DIR（如
    /data/workspaces），但沙箱容器由宿主 daemon 经 docker.sock 创建，
    volumes 源必须是 daemon 可见的宿主路径（WORKSPACES_HOST_DIR，即
    backend 自身卷挂载的宿主侧）——否则 daemon 会自动创建 root 属主
    的空目录，沙箱文件读写静默失效。

    本地开发两路径相同（CONTAINER_DIR=None 时 derive 自 HOST_DIR）→
    返回 None 免换算。仅用于 docker run 的 volumes 源；read/write 等
    backend 进程侧文件操作仍用进程视角路径。
    """
    container = Path(settings.WORKSPACES_CONTAINER_DIR).resolve()
    host = Path(settings.WORKSPACES_HOST_DIR).resolve()
    if container == host:
        return None
    prefix = str(container)

    def _map(path: str) -> str:
        if path == prefix or path.startswith(prefix + os.sep):
            return str(host) + path[len(prefix):]
        return path  # 工作区根以外的路径（如临时目录）不换算

    return _map


@dataclass(frozen=True)
class Workspace:
    """Resolved paths for a Session or Task workspace.

    Story 4-15: Added ``scope`` to distinguish Session workspaces (lifecycle
    tied to chat session) from Task workspaces (lifecycle tied to Task).
    Defaults to ``"session"`` for backward compatibility — all existing
    callers and test fixtures continue to work.

    mode（workspace 重设计）：``"cloud"``（默认）= 平台托管三目录布局；
    ``"local"`` = 本地接入（同机目录树，local_dir 为用户指定目录，
    无 input/output 职能，uploads 禁用）。
    """

    root: Path
    input_dir: Path
    output_dir: Path
    tmp_dir: Path
    scope: str = "session"  # "session" | "task"
    mode: str = "cloud"  # "cloud" | "local"
    local_dir: str | None = None  # local 模式：白名单根内的相对路径

    @property
    def is_local(self) -> bool:
        return self.mode == "local"

    @property
    def local_root(self) -> Path:
        """local 模式的实际根目录（必须先经 get_local_workspace 校验）。"""
        if not self.is_local or not self.local_dir:
            raise ValueError("local_root is only available for mode='local' workspaces")
        return self.root

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

    @staticmethod
    def get_local_workspace(local_dir: str) -> Workspace:
        """构造本地接入 workspace（同机目录接入）。

        校验 LOCAL_WORKSPACE_ROOT 白名单：local_dir 必须是白名单根树内
        的相对路径，且目标目录必须已存在（不代建用户目录）。返回 mode
        为 ``"local"`` 的 Workspace——root/tmp/input/output 都指向用户
        目录（local 模式下 input/output 无职能，仅占位保持字段可用）。

        Raises:
            ValueError: 本地模式未启用 / 路径越出白名单 / 目录不存在。
        """
        raw = (settings.LOCAL_WORKSPACE_ROOT or "").strip()
        if not raw:
            raise ValueError(
                "LOCAL_WORKSPACE_ROOT is not configured — local workspace access is disabled"
            )
        allow_root = Path(raw).expanduser().resolve()
        if os.path.isabs(local_dir.strip()) or local_dir.strip().startswith("~"):
            raise ValueError(
                f"local_dir must be relative to LOCAL_WORKSPACE_ROOT, got '{local_dir}'"
            )
        rel = local_dir.strip().strip("/")
        if not rel or rel in (".", "..") or rel.startswith(".."):
            raise ValueError(f"invalid local_dir: '{local_dir}'")
        root = (allow_root / rel).resolve()
        from agent_flow_harness.workspace import is_within

        if not is_within(root, allow_root):
            raise ValueError(f"local_dir '{local_dir}' escapes LOCAL_WORKSPACE_ROOT")
        if not root.is_dir():
            raise ValueError(f"local_dir '{local_dir}' does not exist on this host")
        return Workspace(
            root=root,
            input_dir=root,
            output_dir=root,
            tmp_dir=root,
            mode="local",
            local_dir=rel,
        )


# ── Module-level helpers ──────────────────────────────────────────────────────


def layout_for_workspace(ws: Workspace) -> WorkspaceLayout:
    """Workspace → harness WorkspaceLayout（环境段 describe() 与沙箱共用）。

    cloud → CloudLayout（三目录角色）；local → LocalLayout（单 root）。
    """
    from agent_flow_harness.workspace import CloudLayout, LocalLayout

    if ws.is_local:
        return LocalLayout(ws.local_root)
    return CloudLayout(ws.tmp_dir, ws.output_dir, ws.input_dir)


def list_background_tasks(ws: Workspace) -> list[dict]:
    """结构化扫描工作区后台任务（API 端点与通知文本共用）。

    纯宿主 FS 读取（无需 exec）：``{id}.exit`` 存在 = 已结束；有
    ``{id}.read`` = 已被 bash_output 读过；无 ``.exit`` = 进行中
    （是否真在跑取决于容器是否存活）。按启动时间倒序。
    """
    bg_dir = ws.tmp_dir / ".af_bg"
    if not bg_dir.is_dir():
        return []
    items: list[dict] = []
    for pid_file in bg_dir.glob("*.pid"):
        tid = pid_file.name[: -len(".pid")]
        if not tid.startswith("bg-"):
            continue
        try:
            started = float((bg_dir / f"{tid}.start").read_text().strip() or 0)
        except (OSError, ValueError):
            started = 0.0
        exit_code: str | None = None
        exit_file = bg_dir / f"{tid}.exit"
        if exit_file.is_file():
            try:
                exit_code = exit_file.read_text().strip() or "0"
            except OSError:
                exit_code = "?"
        try:
            cmd_first_line = (bg_dir / f"{tid}.cmd").read_text(
                encoding="utf-8", errors="replace"
            ).strip().splitlines()[0][:80]
        except (OSError, IndexError):
            cmd_first_line = "(unknown command)"
        items.append({
            "id": tid,
            "running": exit_code is None,
            "exit_code": exit_code,
            "unread": not (bg_dir / f"{tid}.read").is_file(),
            "started_at": started,
            "cmd": cmd_first_line,
        })
    items.sort(key=lambda item: item["started_at"], reverse=True)
    return items


def collect_background_task_notices(ws: Workspace, *, max_tasks: int = 5) -> str:
    """扫描工作区后台任务 → turn 边界注入文本（docs/background-tasks.md §4）。

    基于 :func:`list_background_tasks`（纯宿主 FS，无需 exec）。已结束且
    已读的任务不再注入。返回 ``[后台任务]`` 段文本；无任务返回空串。
    """
    import time

    items = [
        item for item in list_background_tasks(ws)
        if item["running"] or item["unread"]
    ][:max_tasks]
    if not items:
        return ""
    now = time.time()
    lines = ["[后台任务]"]
    for item in items:
        minutes = max(0, int((now - item["started_at"]) / 60)) if item["started_at"] else "?"
        if item["running"]:
            lines.append(
                f"- {item['id']}：进行中（约 {minutes} 分钟）——`{item['cmd']}`。"
                f"进度用 bash_output(command_id='{item['id']}') 查看；"
                f"等待完成用 bash_output(command_id='{item['id']}', block=true)"
            )
        else:
            lines.append(
                f"- {item['id']}：已结束（exit {item['exit_code']}，未读）——`{item['cmd']}`。"
                f"用 bash_output(command_id='{item['id']}') 查看输出"
            )
    return "\n".join(lines)

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
