"""LLM 语义摘要:同步压缩核心 + 历史渲染 + 摘要消息装配。

核心原则:
- 非工具消息(用户/AI文本)原文喂给摘要LLM(单条AI文本截 ~4k,防几十条
  长文本累计撑爆摘要请求自身——摘要本就有损,不需逐字保真)。
- 工具调用渲染成「已调用 X(参数概要)」。
- 工具结果不喂原始内容,只留 recall 引用(大结果不撑爆摘要请求)。
- 绝不生成机械摘要(避免累积退化)。

同步化说明(业界对齐):Codex/Gemini CLI/Claude Code 的 compaction 全部
同步执行——触发是低频事件(几十轮一次),异步「省几秒」不抵缓存/竞态/
持久化/兜底路径的整套复杂度。本模块只提供同步核心 :func:`run_summary`,
由 ``_compress_by_turns`` 在超阈值时直接 await;失败/超时返回 None,
当轮以上一级(工具截断)的结果继续,下一轮自然重试(熔断器防 thrashing)。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

import structlog

if TYPE_CHECKING:
    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.messages import BaseMessage, HumanMessage

logger = structlog.get_logger(__name__)

_SUMMARY_PROMPT = """请将以下对话历史压缩为结构化摘要，用于后续对话的上下文延续。严格按以下六段输出（每段 1-3 句，没有则写"无"）：

1. 用户的核心意图与需求：
2. 关键决策与结论：
3. 重要错误与修复（含失败尝试）：
4. 进行中的任务与未完成项：
5. 当前工作状态与建议的下一步：
6. 关键文件/数据引用（recall 引用标记原样保留，便于重取）：

要求：优先保留任务连续性关键信息；丢弃闲聊与冗余细节；[此前摘要] 是更早历史的浓缩，其中信息须合并进对应段落继续保留（不得丢弃）；用中文。

对话历史：
{history}"""

_MAX_AI_TEXT_CHARS = 4000
"""render 给摘要 LLM 的单条 AI 文本上限。用户消息与既有摘要不截
(用户原话/决策链保真),只有 AI 的长篇推理文本截断。"""

_SUMMARY_MESSAGE_PREFIX = "[系统生成的此前对话摘要，非用户发言]"
_SUMMARY_MESSAGE_ID = "llm_summary"


def _truncate_args_preview(args: dict[str, Any], limit: int = 100) -> str:
    """工具参数概要(截断防过长)。"""
    s = str(args)
    return s[:limit] + "..." if len(s) > limit else s


def render_history_for_summary(
    messages: "list[BaseMessage]",
    *,
    reference_formatter: "Callable[[str, str], str] | None" = None,
    max_ai_text_chars: int | None = _MAX_AI_TEXT_CHARS,
) -> str:
    """渲染历史给摘要 LLM:非工具原文,工具结果只留引用。

    - 摘要消息(id="llm_summary"/"summary",任何形态)或 SystemMessage:
      [此前摘要] {原文} —— 修复硬丢失 bug:旧摘要必须参与再摘要,不能静默跳过
    - HumanMessage: [用户] {原文}(不截断,保真用户原话与决策链)
    - AIMessage(有tool_calls): [助手] 已调用 {name}({参数概要})
    - AIMessage(有content): [助手] {原文,超过 max_ai_text_chars 截断}
    - ToolMessage: [工具结果] 已返回 + reference_formatter(tool_call_id, 原文) 的输出

    Args:
        reference_formatter: app 层注入的引用标记生成器(与 compress_tool_outputs
            共用同一个,签名 ``(tool_call_id, original_content) -> str``)。
            None 时只写"[工具结果] 已返回"(harness 不硬编码工具名)。
        max_ai_text_chars: 单条 AI 文本截断上限;None 表示不截断。
    """
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

    parts: list[str] = []
    for m in messages:
        mid = getattr(m, "id", "") or ""
        content = str(m.content)
        if mid in (_SUMMARY_MESSAGE_ID, "summary") or isinstance(m, SystemMessage):
            if content.strip():
                parts.append(f"[此前摘要]\n{content}")
        elif isinstance(m, HumanMessage):
            content = str(m.content)
            if content.strip():
                parts.append(f"[用户] {content}")
        elif isinstance(m, AIMessage):
            # 先渲染工具调用
            for tc in getattr(m, "tool_calls", None) or []:
                name = tc.get("name", "") if isinstance(tc, dict) else getattr(tc, "name", "")
                args = tc.get("args", {}) if isinstance(tc, dict) else getattr(tc, "args", {})
                parts.append(f"[助手] 已调用 {name}({_truncate_args_preview(args)})")
            # 再渲染文本内容(超长截断——摘要本就有损)
            content = str(m.content)
            if content.strip():
                if max_ai_text_chars is not None and len(content) > max_ai_text_chars:
                    content = content[:max_ai_text_chars] + "..."
                parts.append(f"[助手] {content}")
        elif isinstance(m, ToolMessage):
            tcid = m.tool_call_id or ""
            ref = reference_formatter(tcid, content) if reference_formatter else ""
            parts.append(f"[工具结果] 已返回{ref}")
    return "\n".join(parts)


async def run_summary(
    llm: "BaseChatModel",
    outer_messages: "list[BaseMessage]",
    *,
    reference_formatter: "Callable[[str, str], str] | None" = None,
    timeout: float = 60.0,
) -> str | None:
    """对 outer 历史同步生成语义摘要,返回摘要文本。

    失败/超时/空结果 → None(调用方按失败处理,当轮继续,下一轮重试)。

    摘要消息的装配用 :func:`build_summary_message`——HumanMessage
    (Claude Code / Codex 同款 user-message 形态):天然在历史区,下次
    压缩自然重吸收;配框架文本防归因混淆(模型不会当成用户发言)。
    """
    import asyncio

    from langchain_core.messages import HumanMessage

    history_text = render_history_for_summary(
        outer_messages, reference_formatter=reference_formatter,
    )
    prompt = _SUMMARY_PROMPT.format(history=history_text)

    try:
        # config 必须显式传 callbacks=[]：隔离 contextvar 隐式继承的
        # astream_events 回调,摘要 LLM 的 on_chat_model_* 事件就不会冒泡进
        # 聊天 SSE 流(前端表现为游离 text/thinking 事件插进对话中间)。
        # 空 callbacks 覆盖继承,tags 再给适配器 stream_events_to_app_events
        # 作第二道过滤防线。
        resp = await asyncio.wait_for(
            llm.ainvoke(
                [HumanMessage(content=prompt)],
                config={"callbacks": [], "tags": ["llm_summary"]},
            ),
            timeout=timeout,
        )
    except TimeoutError:
        logger.warning("compress_summary_timeout", timeout=timeout)
        return None
    except Exception:
        logger.exception("compress_summary_failed")
        return None

    summary_text = str(resp.content).strip()
    if not summary_text:
        logger.warning("compress_summary_empty")
        return None
    return summary_text


def build_summary_message(summary_text: str) -> "HumanMessage":
    """把摘要文本装配为历史区消息(HumanMessage, id=llm_summary)。"""
    from langchain_core.messages import HumanMessage

    return HumanMessage(
        content=f"{_SUMMARY_MESSAGE_PREFIX}\n{summary_text}",
        id=_SUMMARY_MESSAGE_ID,
    )


__all__ = [
    "build_summary_message",
    "render_history_for_summary",
    "run_summary",
]
