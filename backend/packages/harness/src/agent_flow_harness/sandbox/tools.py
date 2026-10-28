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

import asyncio
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


class _EditItem(BaseModel):
    old_string: str = Field(..., description="要替换的原文本（必须在原始文件内容中唯一）")
    new_string: str = Field(..., description="替换后的新文本")


class _EditArgs(BaseModel):
    path: str = Field(
        ...,
        description="要编辑的文件路径。裸相对路径基于工作区 tmp/（不存在时回退查 "
        "output/）；output/ 前缀可编辑 write 产出的文件；input/ 为只读不可编辑",
    )
    old_string: str | None = Field(
        None, description="单编辑模式：要替换的原文本（必须在文件中唯一，除非 replace_all=true）"
    )
    new_string: str | None = Field(None, description="单编辑模式：替换后的新文本")
    replace_all: bool = Field(
        False, description="替换所有匹配项。默认 false（要求 old_string 唯一）"
    )
    edits: str | list[_EditItem] | _EditItem | None = Field(
        None,
        description=(
            "批量编辑模式：对同一文件的多处修改优先在**一次调用**中用 edits 数组提交，"
            "而不是发多次 edit 调用。每项 {old_string, new_string} 都基于原始文件内容匹配"
            "（非增量），各项命中区间不得重叠/嵌套；相邻改动应合并为一项。"
            "传入 JSON 字符串也可（会自动解析）"
        ),
    )


def _normalize_edit_pairs(
    old_string: str | None,
    new_string: str | None,
    edits: str | _EditItem | list[_EditItem] | dict[str, str] | list[dict[str, str]] | None,
) -> list[tuple[str, str]]:
    """归一化为 (old, new) 列表：兼容 edits 传 JSON 字符串/单对象（GLM 系模型
    常见 quirk，pi 同款容错），并合并单编辑模式参数。"""
    import json as _json

    if isinstance(edits, str):
        try:
            parsed = _json.loads(edits)
        except _json.JSONDecodeError as exc:
            raise ToolException(f"edits is not valid JSON: {exc}") from exc
        if isinstance(parsed, dict):
            parsed = [parsed]
        if not isinstance(parsed, list):
            raise ToolException(
                "edits must be an array of {old_string, new_string} objects."
            )
        edits = parsed
    elif isinstance(edits, _EditItem):
        edits = [edits]

    pairs: list[tuple[str, str]] = []
    for i, item in enumerate(edits or []):
        if isinstance(item, dict):
            d = item
        elif isinstance(item, _EditItem):
            d = item.model_dump()
        else:
            raise ToolException(
                f"edits[{i}] invalid: expected object with old_string/new_string."
            )
        old, new = d.get("old_string"), d.get("new_string")
        if not isinstance(old, str) or not isinstance(new, str):
            raise ToolException(
                f"edits[{i}] invalid: old_string and new_string are required strings."
            )
        pairs.append((old, new))
    if old_string is not None or new_string is not None:
        if not isinstance(old_string, str) or not isinstance(new_string, str):
            raise ToolException("old_string and new_string must be provided together as strings.")
        pairs.append((old_string, new_string))
    if not pairs:
        raise ToolException(
            "edit requires either old_string+new_string or a non-empty edits array."
        )
    return pairs


class _GlobArgs(BaseModel):
    path: str = Field(..., description="搜索根目录")
    pattern: str = Field(..., description="glob 模式，如 *.py")


class _GrepArgs(BaseModel):
    path: str = Field(..., description="搜索根目录或文件")
    pattern: str = Field(..., description="正则表达式")


# ── 工具实现 ────────────────────────────────────────────────────────────
#
# 全部工具经 asyncio.to_thread 卸载同步 Sandbox 调用：Sandbox 方法是阻塞的
# （DockerSandbox 走 docker-py 同步 API，一条命令可长达 SANDBOX_TIMEOUT），
# 在协程内直调会卡死整个事件循环（与治理 code 工具 _build_code_tool 的
# asyncio.to_thread 模式一致）。


async def _bash(command: str) -> str:
    """执行 shell 命令并返回输出。委托 sandbox.execute_command。"""
    sandbox = _get_sandbox_safe()
    if sandbox is None:
        raise ToolException("Error: sandbox not initialized. Call set_sandbox_context() first.")
    try:
        result = await asyncio.to_thread(sandbox.execute_command, command)
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
        return await asyncio.to_thread(sandbox.read_file, path)
    except Exception as exc:
        raise ToolException(f"Error reading file: {exc}") from exc


async def _write(path: str, content: str) -> str:
    """写文件到 output 目录（用户可见/可下载）。委托 sandbox.write_file。"""
    sandbox = _get_sandbox_safe()
    if sandbox is None:
        raise ToolException("Error: sandbox not initialized.")
    try:
        await asyncio.to_thread(sandbox.write_file, path, content)
        rel = path.removeprefix("output/")
        return f"Successfully wrote {len(content)} chars to output/{rel}"
    except Exception as exc:
        raise ToolException(f"Error writing file: {exc}") from exc


async def _edit(
    path: str,
    old_string: str | None = None,
    new_string: str | None = None,
    replace_all: bool = False,
    edits: str | list[_EditItem] | list[dict[str, str]] | dict[str, str] | None = None,
) -> str:
    """就地编辑文件（字符串替换，支持 edits 批量）。委托 sandbox.edit_file/edit_file_many。"""
    sandbox = _get_sandbox_safe()
    if sandbox is None:
        raise ToolException("Error: sandbox not initialized.")
    try:
        pairs = _normalize_edit_pairs(old_string, new_string, edits)
        if len(pairs) == 1:
            # 单编辑走 edit_file：保持既有 mock 断言与 sandbox 契约不变
            return await asyncio.to_thread(
                sandbox.edit_file, path, pairs[0][0], pairs[0][1], replace_all=replace_all
            )
        return await asyncio.to_thread(
            sandbox.edit_file_many, path, pairs, replace_all=replace_all
        )
    except ToolException:
        raise
    except Exception as exc:
        raise ToolException(f"Error editing file: {exc}") from exc


async def _glob(path: str, pattern: str) -> str:
    """文件匹配。委托 sandbox.glob。"""
    sandbox = _get_sandbox_safe()
    if sandbox is None:
        raise ToolException("Error: sandbox not initialized.")
    try:
        matches = await asyncio.to_thread(sandbox.glob, path, pattern)
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
        matches = await asyncio.to_thread(sandbox.grep, path, pattern)
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
    description=(
        "就地编辑已有文件：将文件中 old_string 精确替换为 new_string。对同一文件的"
        "多处修改，务必在**一次调用**中用 edits 数组批量提交（每项基于原始文件内容"
        "匹配、不得重叠），不要发多次 edit 调用。old_string 必须与文件内容完全一致"
        "（含空格缩进，CRLF/BOM 会自动归一化处理）且在文件中唯一；多处匹配时提供更长"
        "上下文或设 replace_all=true。生成新文件请用 write。write 产出的 output/ "
        "文件同样可编辑（用裸文件名或 output/ 前缀）。"
    ),
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
