"""文件/shell 工具 — bash/read/write/edit/glob/grep（零 I/O，全部委托 Sandbox）。

三层工具模型第二层。工具代码从不直接 subprocess/open，全部委托注入的
Sandbox 方法。异常被 catch 转 ToolException 抛出（AC8 异常隔离）：由
tool_wrapper 统一转为 status="error" 的 ToolMessage，REACT 循环不中断，
LLM 仍可看到错误文案并重试，前端也能结构化区分工具成败。

工作区布局（workspace 模式）：tmp/ 工作区（bash cwd、裸相对路径默认）、
input/ 只读输入、output/ 产物目录（write 固定写入，read/edit 可访问）。

通过 ContextVar（sandbox_context）获取 sandbox 实例，与 workspace_context /
subagent_context 同模式。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from langchain_core.tools import StructuredTool, ToolException
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from agent_flow_harness.sandbox.base import Sandbox


def _get_sandbox_safe() -> Sandbox | None:
    """获取 sandbox，失败返回 None（由工具转 ToolException）。"""
    from agent_flow_harness.sandbox.context import get_sandbox_context

    try:
        return get_sandbox_context().sandbox
    except RuntimeError:
        return None


# ── 参数 schema ────────────────────────────────────────────────────────


class _BashArgs(BaseModel):
    command: str = Field(..., description="要执行的 shell 命令")


class _ReadArgs(BaseModel):
    path: str = Field(
        ...,
        description="要读取的文件路径。裸相对路径基于工作区 tmp/；"
        "input/、output/ 前缀（或 /workspace/input/、/workspace/output/ 绝对路径）"
        "可访问对应目录",
    )


class _WriteArgs(BaseModel):
    path: str = Field(..., description="文件路径（相对于 output 目录）")
    content: str = Field(..., description="文件内容")


class _EditArgs(BaseModel):
    path: str = Field(
        ...,
        description="要编辑的文件路径。裸相对路径基于工作区 tmp/（不存在时回退查 "
        "output/）；output/ 前缀可编辑 write 产出的文件；input/ 为只读不可编辑",
    )
    old_string: str = Field(..., description="要替换的原文本（必须在文件中唯一，除非 replace_all=true）")
    new_string: str = Field(..., description="替换后的新文本")
    replace_all: bool = Field(
        False, description="替换所有匹配项。默认 false（要求 old_string 唯一）"
    )


class _GlobArgs(BaseModel):
    path: str = Field(..., description="搜索根目录")
    pattern: str = Field(..., description="glob 模式，如 *.py")


class _GrepArgs(BaseModel):
    path: str = Field(..., description="搜索根目录或文件")
    pattern: str = Field(..., description="正则表达式")


# ── 工具实现 ────────────────────────────────────────────────────────────


async def _bash(command: str) -> str:
    """执行 shell 命令并返回输出。委托 sandbox.execute_command。"""
    sandbox = _get_sandbox_safe()
    if sandbox is None:
        raise ToolException("Error: sandbox not initialized. Call set_sandbox_context() first.")
    try:
        result = sandbox.execute_command(command)
        output = result.stdout
        if result.stderr:
            output += f"\nSTDERR:\n{result.stderr}"
        if result.exit_code != 0 and not result.timed_out:
            output += f"\nExit code: {result.exit_code}"
        if result.timed_out:
            raise ToolException("Error: command timed out and was killed.")
        return output if output else "(command produced no output)"
    except ToolException:
        raise
    except Exception as exc:
        raise ToolException(f"Error executing command: {exc}") from exc


async def _read(path: str) -> str:
    """读文件内容。委托 sandbox.read_file。"""
    sandbox = _get_sandbox_safe()
    if sandbox is None:
        raise ToolException("Error: sandbox not initialized.")
    try:
        return sandbox.read_file(path)
    except Exception as exc:
        raise ToolException(f"Error reading file: {exc}") from exc


async def _write(path: str, content: str) -> str:
    """写文件到 output 目录（用户可见/可下载）。委托 sandbox.write_file。"""
    sandbox = _get_sandbox_safe()
    if sandbox is None:
        raise ToolException("Error: sandbox not initialized.")
    try:
        sandbox.write_file(path, content)
        rel = path.removeprefix("output/")
        return f"Successfully wrote {len(content)} chars to output/{rel}"
    except Exception as exc:
        raise ToolException(f"Error writing file: {exc}") from exc


async def _edit(path: str, old_string: str, new_string: str, replace_all: bool = False) -> str:
    """就地编辑文件（字符串替换）。委托 sandbox.edit_file。"""
    sandbox = _get_sandbox_safe()
    if sandbox is None:
        raise ToolException("Error: sandbox not initialized.")
    try:
        return sandbox.edit_file(path, old_string, new_string, replace_all=replace_all)
    except Exception as exc:
        raise ToolException(f"Error editing file: {exc}") from exc


async def _glob(path: str, pattern: str) -> str:
    """文件匹配。委托 sandbox.glob。"""
    sandbox = _get_sandbox_safe()
    if sandbox is None:
        raise ToolException("Error: sandbox not initialized.")
    try:
        matches = sandbox.glob(path, pattern)
        if not matches:
            return "(no matches)"
        return "\n".join(matches)
    except Exception as exc:
        raise ToolException(f"Error in glob: {exc}") from exc


async def _grep(path: str, pattern: str) -> str:
    """内容搜索。委托 sandbox.grep。"""
    sandbox = _get_sandbox_safe()
    if sandbox is None:
        raise ToolException("Error: sandbox not initialized.")
    try:
        matches = sandbox.grep(path, pattern)
        if not matches:
            return "(no matches)"
        return "\n".join(f"{m.path}:{m.line_number}: {m.line}" for m in matches)
    except Exception as exc:
        raise ToolException(f"Error in grep: {exc}") from exc


bash = StructuredTool.from_function(
    _bash, name="bash", description="执行 shell 命令并返回输出。",
    args_schema=_BashArgs, coroutine=_bash,
)
read = StructuredTool.from_function(
    _read, name="read", description="读取文件内容（支持工作区 tmp/input/output 目录）。",
    args_schema=_ReadArgs, coroutine=_read,
)
write = StructuredTool.from_function(
    _write, name="write",
    description="写入文件内容到 output 目录（用户可见/可下载）。当用户要求生成、创建、保存或导出任何文件时使用此工具。",
    args_schema=_WriteArgs, coroutine=_write,
)
edit = StructuredTool.from_function(
    _edit, name="edit",
    description="就地编辑已有文件：将文件中 old_string 精确替换为 new_string。old_string 必须与文件内容完全一致（含空格缩进）且在文件中唯一；多处匹配时提供更长上下文或设 replace_all=true。生成新文件请用 write。write 产出的 output/ 文件同样可编辑（用裸文件名或 output/ 前缀）。",
    args_schema=_EditArgs, coroutine=_edit,
)
glob = StructuredTool.from_function(
    _glob, name="glob", description="按 glob 模式匹配文件。",
    args_schema=_GlobArgs, coroutine=_glob,
)
grep = StructuredTool.from_function(
    _grep, name="grep", description="在文件中搜索正则匹配。",
    args_schema=_GrepArgs, coroutine=_grep,
)


__all__ = ["bash", "read", "write", "edit", "glob", "grep"]
