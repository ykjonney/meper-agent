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
    timeout: int | None = Field(
        None, ge=1, le=600,
        description="命令超时秒数（超时强制 kill），上限 600；不传则使用"
        "工作区配置的默认超时。长任务（构建/安装依赖）可适当调大",
    )
    run_in_background: bool = Field(
        False,
        description="后台运行：立即返回任务 id，不等待命令结束。适合构建/"
        "测试/批处理等有限任务（非常驻服务——超过 30 分钟会被终止）。"
        "用 bash_output(command_id=...) 查看状态与增量输出",
    )


class _BashOutputArgs(BaseModel):
    command_id: str = Field(..., description="后台任务 id（bg- 开头，启动时返回）")
    block: bool = Field(
        False,
        description="等待模式：在本次调用内轮询等待任务结束（最多 "
        "block_timeout 秒）。用于\"等任务完成再继续\"的场景",
    )
    block_timeout: int = Field(
        120, ge=10, le=540,
        description="block 等待的最长秒数（默认 120）。超时返回当前进度，"
        "可再次调用续等",
    )
    head_limit: int = Field(
        200, ge=1,
        description="最多返回的输出行数（取尾部）",
    )


class _ReadArgs(BaseModel):
    path: str = Field(..., description="要读取的文件路径（相对或绝对）")
    offset: int = Field(
        1, ge=1,
        description="起始行号（1-based）。大文件分段读取时传入；"
        "上次读取结果尾部的续读提示会给出应使用的 offset 值",
    )
    limit: int = Field(
        2000, ge=1,
        description="本次返回的行数（默认 2000），配合 offset 分页读取大文件",
    )


class _WriteArgs(BaseModel):
    path: str = Field(..., description="目标文件路径（相对或绝对）")
    content: str = Field(..., description="文件内容")


class _EditItem(BaseModel):
    old_string: str = Field(..., description="要替换的原文本（必须在原始文件内容中唯一）")
    new_string: str = Field(..., description="替换后的新文本")


class _EditArgs(BaseModel):
    path: str = Field(..., description="要编辑的文件路径（相对或绝对）")
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
    head_limit: int = Field(
        100, ge=1,
        description="最多返回的匹配数（默认 100）。命中更多时请细化正则"
        "（加文件名/上下文限定）或配合 offset 翻页",
    )
    offset: int = Field(
        0, ge=0,
        description="跳过前 N 条匹配（配合 head_limit 翻页浏览大量命中）",
    )
    context: int = Field(
        0, ge=0,
        description="每条命中附带的前后上下文行数（默认 0）",
    )
    ignore_case: bool = Field(False, description="忽略大小写")
    glob_filter: str | None = Field(
        None, description="按文件名过滤（如 *.py、*.md）",
    )
    output_mode: str = Field(
        "content",
        description="输出模式：content（默认，匹配行+上下文）/ "
        "files_with_matches（只列文件路径）/ count（每文件命中计数）",
    )


# ── 工具实现 ────────────────────────────────────────────────────────────
#
# 全部工具经 asyncio.to_thread 卸载同步 Sandbox 调用：Sandbox 方法是阻塞的
# （DockerSandbox 走 docker-py 同步 API，一条命令可长达 SANDBOX_TIMEOUT），
# 在协程内直调会卡死整个事件循环（与治理 code 工具 _build_code_tool 的
# asyncio.to_thread 模式一致）。


async def _bash(
    command: str, timeout: int | None = None, run_in_background: bool = False
) -> str:
    """执行 shell 命令并返回输出。委托 sandbox.execute_command。

    timeout=None 沿用 sandbox 配置的默认超时（两实现的 execute_command
    均以 None 表示"未覆盖"）；传入值则覆盖沙箱默认（上限 600，schema 约束）。
    run_in_background=true 时毫秒级返回任务 id，命令在容器内 nohup 运行
    （沙箱超时管不到后台子进程）；用 bash_output 查看。
    """
    sandbox = _get_sandbox_safe()
    if sandbox is None:
        raise ToolException("Error: sandbox not initialized. Call set_sandbox_context() first.")
    if run_in_background:
        from agent_flow_harness.sandbox.bg_tasks import (
            build_start_exec,
            new_task_id,
        )

        task_id = new_task_id()
        try:
            result = await asyncio.to_thread(
                lambda: sandbox.execute_command(build_start_exec(task_id, command), timeout=15)
            )
        except Exception as exc:
            raise ToolException(f"Error starting background task: {exc}") from exc
        if result.exit_code != 0:
            raise ToolException(
                f"Error starting background task: {result.stderr.strip() or 'unknown error'}"
            )
        return (
            f"Started background task {task_id}. "
            f"Check status/output with bash_output(command_id='{task_id}'); "
            f"log file: tmp/.af_bg/{task_id}.log"
        )
    try:
        result = await asyncio.to_thread(
            lambda: sandbox.execute_command(command, timeout=timeout)
        )
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


async def _read(path: str, offset: int = 1, limit: int = 2000) -> str:
    """读文件内容（行号格式 + 分页）。委托 sandbox.read_file。

    读取同时记录新鲜度基线：edit 前必须先 read（Sandbox 侧校验）。
    """
    sandbox = _get_sandbox_safe()
    if sandbox is None:
        raise ToolException("Error: sandbox not initialized.")
    try:
        return await asyncio.to_thread(
            sandbox.read_file, path, offset=offset, limit=limit
        )
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


async def _bash_output(
    command_id: str,
    block: bool = False,
    block_timeout: int = 120,
    head_limit: int = 200,
) -> str:
    """查看后台任务：增量输出 + 探活 + 软超时（+可选阻塞等待）。

    增量语义：返回自上次调用以来的新增输出（字节偏移持久在工作区）。
    block=true 时在本次调用内等待任务结束（最多 block_timeout 秒，
    分段调用可实现"等完再继续"）。finished 的任务读取一次后标记已读，
    不再进入 turn 边界的未读注入。
    """
    import asyncio as _asyncio

    from agent_flow_harness.sandbox.bg_tasks import (
        build_output_exec,
        is_valid_task_id,
        parse_output_exec,
    )

    sandbox = _get_sandbox_safe()
    if sandbox is None:
        raise ToolException("Error: sandbox not initialized.")
    if not is_valid_task_id(command_id):
        raise ToolException(
            f"Invalid command_id: '{command_id}' (expected bg-<hex>, "
            "see the started background task message)"
        )
    try:
        # block 等待需要在 exec 内轮询，沙箱超时要盖住等待时长
        exec_timeout = (block_timeout + 15) if block else 15
        result = await _asyncio.to_thread(
            lambda: sandbox.execute_command(
                build_output_exec(command_id, block_timeout=block_timeout if block else 0),
                timeout=exec_timeout,
            )
        )
        status, output = parse_output_exec(result.stdout)
        if not status:
            raise ToolException(
                f"Error checking background task: "
                f"{result.stderr.strip() or result.stdout.strip() or 'no response'}"
            )
        if status["status"] == "unknown":
            return f"Unknown background task: {command_id}"
        nonempty = [ln for ln in output.splitlines() if ln.strip()]
        output = "\n".join(nonempty[-head_limit:])
        summary = (
            f"task {command_id}: {status['status']}"
            + (f", exit={status['exit']}" if status["exit"] else "")
            + f", age={status['age']}s"
        )
        if status["status"] == "running":
            summary += " — still running; call again (optionally block=true) to check later"
        return f"[{summary}]\n{output}".strip()
    except ToolException:
        raise
    except Exception as exc:
        raise ToolException(f"Error checking background task: {exc}") from exc


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


async def _grep(
    path: str,
    pattern: str,
    head_limit: int = 100,
    offset: int = 0,
    output_mode: str = "content",
    context: int = 0,
    ignore_case: bool = False,
    glob_filter: str | None = None,
) -> str:
    """内容搜索（默认最多 head_limit 条）。委托 sandbox.grep。

    context/ignore_case/glob_filter 下沉 sandbox 层；output_mode/offset/
    head_limit 在本层组装。content 模式上下文行去重（按 path+行号）。
    """
    sandbox = _get_sandbox_safe()
    if sandbox is None:
        raise ToolException("Error: sandbox not initialized.")
    try:
        matches = await asyncio.to_thread(
            sandbox.grep, path, pattern,
            context=context, ignore_case=ignore_case, glob_filter=glob_filter,
        )
        if not matches:
            return "(no matches)"
        total = len(matches)
        shown = matches[offset:offset + head_limit]
        if output_mode == "files_with_matches":
            seen: list[str] = []
            for m in shown:
                if m.path not in seen:
                    seen.append(m.path)
            output = "\n".join(seen)
        elif output_mode == "count":
            counts: dict[str, int] = {}
            for m in shown:
                counts[m.path] = counts.get(m.path, 0) + 1
            output = "\n".join(f"{p}: {c}" for p, c in counts.items())
        else:
            rendered: list[str] = []
            seen_ctx: set[tuple[str, int]] = set()
            for m in shown:
                for i, ctx_line in enumerate(m.before, start=m.line_number - len(m.before)):
                    key = (m.path, i)
                    if key not in seen_ctx:
                        seen_ctx.add(key)
                        rendered.append(f"{m.path}:{i}- {ctx_line}")
                rendered.append(f"{m.path}:{m.line_number}: {m.line}")
                seen_ctx.add((m.path, m.line_number))
                for i, ctx_line in enumerate(m.after, start=m.line_number + 1):
                    key = (m.path, i)
                    if key not in seen_ctx:
                        seen_ctx.add(key)
                        rendered.append(f"{m.path}:{i}- {ctx_line}")
            output = "\n".join(rendered)
        if total > len(shown):
            output += (
                f"\n[showing {len(shown)} of {total} matches (offset {offset}); "
                "adjust offset/head_limit or refine the pattern]"
            )
        return output or "(no matches)"
    except Exception as exc:
        raise ToolException(f"Error in grep: {exc}") from exc


bash = StructuredTool.from_function(
    _bash, name="bash",
    description=(
        "执行 shell 命令并返回输出。工作目录在调用间保持（cd 持久）；"
        "环境变量不跨调用持久——export 需与使用在同一条命令内完成。"
        "长任务用 run_in_background=true 后台运行（立即返回，不阻塞）。"
    ),
    args_schema=_BashArgs, coroutine=_bash,
)
bash_output = StructuredTool.from_function(
    _bash_output, name="bash_output",
    description=(
        "查看后台任务的状态与增量输出（自上次调用以来的新增部分）。"
        "status=running 可再次调用（block=true 可在本次调用内等待任务结束，"
        "最多 block_timeout 秒——用于\"等构建完成再继续\"）；"
        "finished 附带退出码。任务日志持久在工作区 tmp/.af_bg/，跨轮次可查。"
    ),
    args_schema=_BashOutputArgs, coroutine=_bash_output,
)
read = StructuredTool.from_function(
    _read, name="read",
    description=(
        "读取文件内容（带行号，支持 offset/limit 分页）。返回 cat -n 风格"
        "行号文本；大文件按续读提示传 offset 分段读取。编辑文件前必须先用"
        "本工具读取目标文件。工作区目录布局见系统提示 Environment 段。"
    ),
    args_schema=_ReadArgs, coroutine=_read,
)
write = StructuredTool.from_function(
    _write, name="write",
    description=(
        "创建新文件或整体重写文件内容（产物目录由工作区布局决定，见系统提示"
        " Environment 段）。当用户要求生成、创建、保存或导出任何文件时使用此"
        "工具；更新已有文件的局部内容请用 edit（整篇重写才用 write，避免凭"
        "记忆复述丢内容）。"
    ),
    args_schema=_WriteArgs, coroutine=_write,
)
edit = StructuredTool.from_function(
    _edit, name="edit",
    description=(
        "就地编辑已有文件：将文件中 old_string 精确替换为 new_string。编辑前"
        "必须已用 read 读取该文件；若 read 之后文件被 bash 等其他方式修改过，"
        "edit 会被拒绝，需重新 read。对同一文件的多处修改，务必在**一次调用**"
        "中用 edits 数组批量提交（每项基于原始文件内容匹配、不得重叠），"
        "不要发多次 edit 调用。old_string 必须与文件内容完全一致"
        "（含空格缩进，CRLF/BOM 会自动归一化处理）且在文件中唯一；多处匹配时"
        "提供更长上下文或设 replace_all=true。生成新文件请用 write。"
        "工作区目录布局见系统提示 Environment 段。"
    ),
    args_schema=_EditArgs, coroutine=_edit,
)
glob = StructuredTool.from_function(
    _glob, name="glob", description="按 glob 模式匹配文件。",
    args_schema=_GlobArgs, coroutine=_glob,
)
grep = StructuredTool.from_function(
    _grep, name="grep",
    description=(
        "在文件中搜索正则匹配（返回 path:line: content，默认最多 100 条，"
        "自动跳过 .git/node_modules 等噪音目录并遵循 .gitignore）。命中过多时"
        "细化正则或用 offset 翻页；只要文件列表用 output_mode=files_with_matches。"
    ),
    args_schema=_GrepArgs, coroutine=_grep,
)


__all__ = ["bash", "bash_output", "read", "write", "edit", "glob", "grep"]
