"""Built-in tools — injected into every Agent's REACT loop.

These tools provide the LLM with fundamental capabilities analogous
to Claude Code's built-in tool set: shell execution, file reading,
file writing, and task management.  They are always available to
every Agent alongside Agent-configured Skill/MCP/Workflow tools.
"""
from __future__ import annotations

import subprocess
import os

from langchain_core.tools import BaseTool, tool
from loguru import logger

from app.engine.agent.workflow_executor import _TASK_TOOLS


# ---------------------------------------------------------------------------
# Built-in tools (bash, read, write)
# ---------------------------------------------------------------------------


@tool
def bash(command: str) -> str:
    """Execute a shell command and return its output.

    Use this tool when you need to run shell commands — file
    operations, git operations, inspections, or any CLI tool.

    Args:
        command: The shell command to execute.
    """
    logger.info("builtin_bash_executed", command_preview=command[:80])
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
        # Limit output to prevent context overflow
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
    """Read a file from the filesystem and return its content.

    Use this tool when you need to inspect file contents.
    The path is relative to the project root or absolute.

    Args:
        path: Path to the file to read.
    """
    logger.info("builtin_read_executed", path=path)
    try:
        # Resolve relative paths against project root
        if not os.path.isabs(path):
            project_root = os.environ.get(
                "PROJECT_ROOT",
                os.getcwd(),
            )
            full_path = os.path.join(project_root, path)
        else:
            full_path = path

        if not os.path.exists(full_path):
            return f"Error: File not found: {path}"

        with open(full_path, encoding="utf-8", errors="replace") as f:
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


@tool
def write(path: str, content: str) -> str:
    """Write content to a file on the filesystem.

    Creates parent directories if they do not exist.
    The path is relative to the project root or absolute.

    Args:
        path: Path to the file to write.
        content: The content to write to the file.
    """
    logger.info("builtin_write_executed", path=path)
    try:
        if not os.path.isabs(path):
            project_root = os.environ.get(
                "PROJECT_ROOT",
                os.getcwd(),
            )
            full_path = os.path.join(project_root, path)
        else:
            full_path = path

        parent = os.path.dirname(full_path)
        if parent and not os.path.exists(parent):
            os.makedirs(parent, exist_ok=True)

        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)

        return f"Successfully wrote {len(content)} bytes to {path}"
    except Exception as e:
        return f"Error writing file: {e}"


# ---------------------------------------------------------------------------
# Tool registry — all built-in tools including task management
# ---------------------------------------------------------------------------

_BUILTIN_BASE_TOOLS: list[BaseTool] = [bash, read, write]

# Task management tools — always available to all Agents
_BUILTIN_TASK_TOOLS: list[BaseTool] = _TASK_TOOLS

# Full list of built-in tools
_BUILTIN_TOOLS: list[BaseTool] = _BUILTIN_BASE_TOOLS + _BUILTIN_TASK_TOOLS
_BUILTIN_TOOL_REGISTRY: dict[str, BaseTool] = {t.name: t for t in _BUILTIN_TOOLS}
