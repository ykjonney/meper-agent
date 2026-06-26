"""Built-in tools — injected into every Agent's REACT loop.

These tools provide the LLM with fundamental capabilities analogous
to Claude Code's built-in tool set: shell execution, file reading,
file writing, and task management.  They are always available to
every Agent alongside Agent-configured Skill/MCP/Workflow tools.

Workspace isolation
-------------------
``read`` and ``write`` are restricted to the current Session workspace
(via :mod:`contextvars`).  Paths that escape the workspace tree are
rejected.  ``bash`` execution will be containerised in Phase 2; for now
the workspace ``tmp/`` directory is used as the working directory.
"""
from __future__ import annotations

import contextvars
import os
import subprocess
from pathlib import Path

from langchain_core.tools import BaseTool, tool
from loguru import logger

from app.engine.agent.workflow_executor import _TASK_TOOLS
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
    """Restore the previous workspace context."""
    _current_workspace.reset(token)


def _get_workspace():
    """Return the current workspace or ``None``."""
    return _current_workspace.get()


def _check_write_quota(workspace: Workspace, additional_bytes: int) -> bool:
    """Check whether writing *additional_bytes* would exceed the workspace quota.

    Returns ``True`` if within quota, ``False`` if exceeded.
    """
    from app.engine.tool.workspace import WorkspaceManager

    return WorkspaceManager.check_quota(workspace, additional_bytes)


def _workspace_log_context() -> dict:
    """Return workspace context dict for structured logging."""
    ws = _get_workspace()
    if ws is None:
        return {}
    return {"user_id": ws.user_id, "session_id": ws.session_id}


# ---------------------------------------------------------------------------
# Path resolution helpers
# ---------------------------------------------------------------------------


def _safe_path_for_read(user_path: str) -> tuple[str | None, str]:
    """Resolve a path for reading within the workspace.

    Also allows read access to the SKILLS_DIR (read-only).

    Returns:
        (resolved_path, error_message) — resolved_path is None on failure.
    """
    from app.core.config import settings
    from app.engine.tool.workspace import WorkspaceManager

    ws = _get_workspace()
    if ws is None:
        # No workspace context — fall back to old behaviour (dev mode)
        if os.path.isabs(user_path):
            return user_path, ""
        project_root = os.environ.get("PROJECT_ROOT", os.getcwd())
        return os.path.join(project_root, user_path), ""

    # Try workspace tree first
    resolved = WorkspaceManager.safe_resolve_workspace_path(
        ws, user_path, allow_skills_read=True,
    )
    if resolved is not None:
        return str(resolved), ""

    # Also allow reading SKILLS_CONTAINER_DIR files by absolute path
    skills_root = str(Path(settings.SKILLS_CONTAINER_DIR).expanduser())
    if os.path.isabs(user_path) and os.path.realpath(user_path).startswith(skills_root):
        return user_path, ""

    return None, "Error: Access denied — path outside workspace"


def _safe_path_for_write(user_path: str, as_output: bool = False) -> tuple[str | None, str]:
    """Resolve a path for writing within the workspace.

    Args:
        user_path: User-supplied path.
        as_output: If True, write to output/; otherwise write to tmp/.

    Returns:
        (resolved_path, error_message) — resolved_path is None on failure.
    """
    from app.engine.tool.workspace import WorkspaceManager

    ws = _get_workspace()
    if ws is None:
        # No workspace context — fall back
        if os.path.isabs(user_path):
            return user_path, ""
        project_root = os.environ.get("PROJECT_ROOT", os.getcwd())
        return os.path.join(project_root, user_path), ""

    # Restrict writing to workspace tree
    target_dir = ws.output_dir if as_output else ws.tmp_dir

    # Resolve relative to the target directory
    if os.path.isabs(user_path):
        resolved = WorkspaceManager.safe_resolve_path(target_dir.parent.parent, user_path)
    else:
        resolved = WorkspaceManager.safe_resolve_path(target_dir, user_path)

    if resolved is None:
        return None, "Error: Access denied — path outside workspace"

    # Additional check: must be within workspace root
    ws_resolved = Path(os.path.realpath(str(ws.root)))
    if not str(resolved).startswith(str(ws_resolved)):
        return None, "Error: Access denied — path outside workspace"

    return str(resolved), ""


# ---------------------------------------------------------------------------
# Built-in tools (bash, read, write)
# ---------------------------------------------------------------------------


@tool
def bash(command: str) -> str:
    """Execute a shell command and return its output.

    Use this tool when you need to run shell commands — file
    operations, git operations, inspections, or any CLI tool.

    The command runs inside an isolated sandbox container when
    SANDBOX_ENABLED=True; otherwise it runs via subprocess (local dev).

    Inside the sandbox, use relative paths to access workspace files:
      - tmp/    → working area (read/write)
      - input/  → user-uploaded files (read-only)
      - output/ → files for user download (read/write)

    Args:
        command: The shell command to execute.
    """
    logger.info("builtin_bash_executed", command_preview=command[:80])

    # Circuit breaker — reject if too many recent failures
    from app.core.circuit_breaker import get_breaker

    breaker = get_breaker("bash")
    if not breaker.allow_request():
        return "Error: bash 工具暂时不可用（近期失败过多），请稍后再试。"

    ws = _get_workspace()

    # Without workspace context, fall back to simple subprocess (dev mode)
    if ws is None:
        result_text = _bash_subprocess_fallback(command)
        breaker.record_success()
        return result_text

    # Use SandboxExecutor (auto-falls-back to subprocess when Docker unavailable)
    from app.engine.tool.sandbox import SandboxExecutor

    executor = SandboxExecutor()
    result = executor.execute(command=command, workspace=ws)

    # Record result for circuit breaker
    # Count timeout and non-zero exit as failures
    if result.timed_out or result.exit_code != 0:
        breaker.record_failure()
    else:
        breaker.record_success()

    output = result.stdout or ""
    if result.stderr:
        output += f"\nSTDERR:\n{result.stderr}"
    if result.exit_code != 0 and not result.timed_out:
        output += f"\nExit code: {result.exit_code}"

    return output if output else "(command produced no output)"


def _bash_subprocess_fallback(command: str) -> str:
    """Run command via subprocess without workspace isolation (dev fallback)."""
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
        output = result.stdout or ""
        if result.stderr:
            output += f"\nSTDERR:\n{result.stderr}"
        if result.returncode != 0:
            output += f"\nExit code: {result.returncode}"
        max_output = 50_000
        if len(output) > max_output:
            output = output[:max_output] + (
                f"\n... [output truncated: {len(output):,} total chars]"
            )
        return output if output else "(command produced no output)"
    except subprocess.TimeoutExpired:
        return "Error: Command timed out after 120 seconds."
    except Exception as e:
        return f"Error executing command: {e}"


@tool
def read(path: str) -> str:
    """Read a file and return its content.

    Use this tool when you need to inspect file contents.
    Paths are resolved relative to the Session workspace.
    Skill files (under the skills directory) are also readable.

    Args:
        path: Path to the file to read (relative to workspace or absolute).
    """
    logger.info("builtin_read_executed", path=path, workspace=_workspace_log_context())

    from app.core.config import settings

    ws = _get_workspace()

    # When sandbox is enabled, read inside the container to share the same
    # filesystem view as bash.  No path translation needed.
    if settings.SANDBOX_ENABLED and ws is not None:
        return _read_via_sandbox(path, ws)

    # Local dev (or no workspace): read directly on the host.
    resolved, error = _safe_path_for_read(path)
    if error:
        return error

    try:
        if not os.path.exists(resolved):
            return f"Error: File not found: {path}"

        with open(resolved, encoding="utf-8", errors="replace") as f:
            content = f.read()

        # Limit output
        max_content = 50_000
        if len(content) > max_content:
            lines = content.count("\n")
            content = content[:max_content] + (
                f"\n... [truncated: {len(content):,} chars, {lines} lines]"
            )
        return content
    except Exception as e:
        return f"Error reading file: {e}"


def _read_via_sandbox(path: str, workspace: Workspace) -> str:
    """Read a file by running ``cat`` inside the sandbox container.

    The sandbox sees the same paths as bash (e.g. ``/workspace/tmp/...``),
    so no path translation is needed.

    When Docker is unavailable, SandboxExecutor falls back to subprocess
    which translates container paths to host paths before executing.
    """
    import shlex

    from app.engine.tool.sandbox import SandboxExecutor

    # SandboxExecutor falls back to subprocess if Docker is unavailable
    executor = SandboxExecutor()
    result = executor.execute(
        command=f"cat -- {shlex.quote(path)}",
        workspace=workspace,
        timeout=30,
    )

    if result.timed_out:
        return "Error: Read timed out"

    if result.exit_code != 0:
        stderr = result.stderr.strip()
        if "No such file or directory" in stderr:
            return f"Error: File not found: {path}"
        return f"Error reading file: {stderr}" or f"Error reading file: exit code {result.exit_code}"

    content = result.stdout
    max_content = 50_000
    if len(content) > max_content:
        lines = content.count("\n")
        content = content[:max_content] + (
            f"\n... [truncated: {len(content):,} chars, {lines} lines]"
        )
    return content


@tool
def write(path: str, content: str) -> str:
    """Write content to a temporary file in tmp/ (intermediate/scratch files).

    Creates parent directories if they do not exist.
    Files written here are NOT visible or downloadable by the user.
    For files the user needs to keep or download, use the write_to_output tool instead.

    Args:
        path: Path to the file to write (relative to tmp/).
        content: The content to write.
    """
    logger.info("builtin_write_executed", path=path, content_len=len(content),
                workspace=_workspace_log_context())

    ws = _get_workspace()
    if ws and not _check_write_quota(ws, len(content.encode("utf-8"))):
        return "Error: Workspace quota exceeded — please free up space or download existing output files."

    resolved, error = _safe_path_for_write(path)
    if error:
        return error

    try:
        parent = os.path.dirname(resolved)
        if parent and not os.path.exists(parent):
            os.makedirs(parent, exist_ok=True)

        with open(resolved, "w", encoding="utf-8") as f:
            f.write(content)

        return f"Successfully wrote {len(content)} bytes to {path}"
    except Exception as e:
        return f"Error writing file: {e}"


@tool
def write_to_output(path: str, content: str) -> str:
    """Write content to output/ — files here are visible and downloadable by the user.

    ALWAYS use this tool when the user asks you to generate, create, save, or
    export any file (code, document, report, data, etc.).

    Args:
        path: Filename (relative to output/) or absolute path within workspace.
        content: The content to write.
    """
    logger.info("builtin_write_to_output_executed", path=path, content_len=len(content),
                workspace=_workspace_log_context())

    ws = _get_workspace()
    if ws and not _check_write_quota(ws, len(content.encode("utf-8"))):
        return "Error: Workspace quota exceeded — please free up space or download existing output files."

    resolved, error = _safe_path_for_write(path, as_output=True)
    if error:
        return error

    try:
        parent = os.path.dirname(resolved)
        if parent and not os.path.exists(parent):
            os.makedirs(parent, exist_ok=True)

        with open(resolved, "w", encoding="utf-8") as f:
            f.write(content)

        return f"Successfully wrote {len(content)} bytes to output/{path}"
    except Exception as e:
        return f"Error writing file: {e}"


# ---------------------------------------------------------------------------
# Tool registry — all built-in tools including task management
# ---------------------------------------------------------------------------

_BUILTIN_BASE_TOOLS: list[BaseTool] = [bash, read, write, write_to_output]

# Task management tools — always available to all Agents
_BUILTIN_TASK_TOOLS: list[BaseTool] = _TASK_TOOLS

# Full list of built-in tools
_BUILTIN_TOOLS: list[BaseTool] = _BUILTIN_BASE_TOOLS + _BUILTIN_TASK_TOOLS
_BUILTIN_TOOL_REGISTRY: dict[str, BaseTool] = {t.name: t for t in _BUILTIN_TOOLS}
