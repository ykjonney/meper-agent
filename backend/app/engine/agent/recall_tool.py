"""recall_tool_result —— 工具输出回溯工具，按 tool_call_id 取回被压缩的原文。

上下文压缩（harness compress_tool_outputs / LLM 摘要）会把已消费的大工具
结果缩短成极简提示，末尾追加"完整原文已存档,可用 recall_tool_result(...) 查看"
（formatter 由 harness_integration.context 注入）。本工具是"回取"的落地：
在压缩发生的那一刻，app 层 formatter 已把原文归档进 tool_output_archives
（对齐 penguin-harness 的截断归档设计）；IM 渠道 / workflow 节点没有 messages
明细，归档是它们唯一的原文来源。

取数链（与 view_image 同构的安全模型）：
1. tool_output_archives 按 (thread_id, tool_call_id) 精确命中 —— thread_id
   经 ContextVar 注入（chat=会话 id，workflow agent 节点=``{task_id}_{node_id}``）；
2. 兜底 messages.timeline_entries（修复上线前已压缩的存量 chat 会话原文）；
3. 都 miss → 友好错误文本（不抛异常，让 agent 能读懂并放弃/换路径）。
"""

from __future__ import annotations

import contextvars

from langchain_core.tools import BaseTool, tool

# ---------------------------------------------------------------------------
# Thread context — set by execution.py adjacent to build_config(thread_id=…)
# （thread 权威来源就是传给 checkpointer 的那个值）,read by recall tool /
# 压缩 formatter 的归档调度。工具执行（含 run_code 桥接线程，经 copy_context
# 透传）期间保持有效，run 结束后成对 reset。
# ---------------------------------------------------------------------------

_current_thread_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "current_thread_id",
    default="",
)


def set_thread_id_context(thread_id: str) -> contextvars.Token:
    """Set the thread (checkpointer) id context for the current async task.

    Returns a token that can be passed to :func:`reset_thread_id_context`
    to restore the previous value.
    """
    return _current_thread_id.set(thread_id)


def reset_thread_id_context(token: contextvars.Token) -> None:
    """Restore the thread id context."""
    _current_thread_id.reset(token)


def _get_thread_id() -> str:
    """Return the current thread id or ``""``."""
    return _current_thread_id.get()


def _err(msg: str) -> str:
    """返回友好错误文本（不抛异常，让 agent 能读懂并修正）。"""
    return f"[recall_tool_result] {msg}"


# 单次返回的默认/上限字符数（对齐 read_file 的分页量级）。
_DEFAULT_LIMIT = 8000
_MAX_LIMIT = 20000


@tool
async def recall_tool_result(
    tool_call_id: str, offset: int = 0, limit: int = _DEFAULT_LIMIT
) -> str:
    """Retrieve the full original output of a previously compressed tool result.

    Large tool outputs are compacted in older turns with a marker like
    "[此结果已被压缩,完整原文已存档,可用 recall_tool_result(tool_call_id=...)
    查看]" — this tool fetches that archived original. Use it when you need
    details (exact values, full JSON, log lines) that the compressed hint no
    longer contains. Long outputs are paginated: pass ``offset`` to continue
    reading from where the previous call stopped.

    Args:
        tool_call_id: The tool_call id quoted in the compression marker.
        offset: 0-based character offset to start reading from.
        limit: Max characters to return per call (capped at 20000).
    """
    thread_id = _get_thread_id()
    if not thread_id:
        return _err("当前无会话上下文，无法回溯工具结果")

    content: str | None = None
    source = ""
    # 1) 压缩时归档的原文 —— 唯一覆盖 chat/渠道/workflow 三场景的来源。
    from app.services.tool_output_archive_service import ToolOutputArchiveService

    archived = await ToolOutputArchiveService.get(thread_id, tool_call_id)
    if archived is not None:
        content, source = archived, "archive"
    else:
        # 2) 兜底：修复上线前已压缩的存量 chat 会话，原文在 messages 明细里
        #    （渠道/工作流本就不落 messages，miss 属预期）。
        from app.services.session_service import MessageService

        content = await MessageService.get_tool_result_content(thread_id, tool_call_id)
        if content is not None:
            source = "messages"

    if content is None:
        return _err(
            f"未找到 tool_call_id={tool_call_id} 的归档原文"
            "（历史会话在归档机制上线前压缩、且无消息明细，或 id 有误）"
        )

    limit = max(1, min(limit, _MAX_LIMIT))
    total = len(content)
    offset = max(0, min(offset, total))
    chunk = content[offset : offset + limit]
    footer = f"\n\n[共 {total} 字符，本次返回 {offset}-{offset + len(chunk)}"
    if offset + len(chunk) < total:
        footer += f"，续读请传 offset={offset + len(chunk)}"
    footer += f"，来源：{source}]"
    return chunk + footer


# ---------------------------------------------------------------------------
# Tool list — exported for context.py injection（always-on 能力型工具）
# ---------------------------------------------------------------------------

_RECALL_TOOLS: list[BaseTool] = [recall_tool_result]

# name → tool 实例查找表：/tools/builtin 端点、context 注入、builder prompt 声明
# 三处共用（harness BUILTIN_TOOLS 取不到 app 层工具，需补此表查找）。
RECALL_TOOL_BY_NAME: dict[str, BaseTool] = {t.name: t for t in _RECALL_TOOLS}
