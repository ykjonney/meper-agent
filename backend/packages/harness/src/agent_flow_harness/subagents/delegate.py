"""delegate_to_subagent 工具 — 主 Agent 委派子任务的入口。

工具签名只暴露 subagent_name + task 给 LLM；所有运行时依赖从 ContextVar 拿。
内部：get_context → registry.get → resolve_tools(排除 delegate) → resolve_llm
→ build_subagent_state(全新隔离) → build_agent_graph(延迟构建) → ainvoke
→ extract_final_text。异常被 catch 转错误字符串返回（AC10 异常隔离）。

提取逻辑 extract_final_text 参照 deer-flow executor.py:674-698。
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

# 顶层 import 以便测试 monkeypatch（测试 patch agent_flow_harness.subagents.delegate.build_agent_graph）
from agent_flow_harness.graph import build_agent_graph, build_config

if TYPE_CHECKING:
    from langchain_core.messages import BaseMessage

logger = logging.getLogger(__name__)

_PLACEHOLDER = "No response generated."

_DELEGATE_AGENT_DOC = {"_id": "subagent", "name": "subagent"}


def extract_final_text(messages: "list[BaseMessage]") -> str:
    """从 messages 提取最后一条 AIMessage 的文本内容。

    处理两种 content 类型：
    - str → 直接返回
    - list → 拼接 block["text"]（dict）和 str 块
    - 都不是 → str(content)
    无 AIMessage → 返回兜底字符串。
    """
    last_ai: Any | None = None
    for msg in reversed(messages):
        # 用类型名字符串判断，避免循环 import AIMessage。
        if msg.__class__.__name__ == "AIMessage":
            last_ai = msg
            break
    if last_ai is None:
        return _PLACEHOLDER
    return _content_to_text(last_ai.content)


def _content_to_text(content: Any) -> str:
    """把 AIMessage.content（str / list / other）转成纯文本。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts) if parts else _PLACEHOLDER
    return str(content)


class _DelegateArgs(BaseModel):
    """delegate_to_subagent 的 LLM 可见参数。"""

    subagent_name: str = Field(..., description="要委派的子 Agent 名称")
    task: str = Field(..., description="委派给子 Agent 的任务描述")


_TRACE_TASK_MAX = 200      # task 摘要截断
_TRACE_ARG_MAX = 150       # 工具参数摘要截断
_TRACE_RESULT_MAX = 200    # 工具结果摘要截断
_TRACE_ROUNDS_CAP = 50     # rounds 条数封顶（防 trace 成为膨胀源）


def _summarize_delegation_rounds(messages: "list[Any]") -> "list[dict[str, Any]]":
    """从子图终态 messages 提取过程摘要（LLM 轮次 + 工具调用/结果）。

    子图会话即用即弃（无 checkpointer），终态 messages 是子 agent 过程的
    唯一载体——在丢弃前提取摘要，供宿主落库审计（委派树可观测）。
    """
    rounds: "list[dict[str, Any]]" = []
    for m in messages:
        cls = m.__class__.__name__
        if cls == "AIMessage":
            tool_calls = getattr(m, "tool_calls", None) or []
            if tool_calls:
                for tc in tool_calls:
                    rounds.append({
                        "t": "tool_call",
                        "tool": str(tc.get("name", "")),
                        "args": str(tc.get("args", {}))[:_TRACE_ARG_MAX],
                    })
            else:
                rounds.append({"t": "llm"})
        elif cls == "ToolMessage":
            content = m.content if isinstance(m.content, str) else str(m.content)
            rounds.append({
                "t": "tool_result",
                "tool": str(getattr(m, "name", "") or ""),
                "result": content[:_TRACE_RESULT_MAX],
            })
    return rounds[:_TRACE_ROUNDS_CAP]


async def _delegate_to_subagent(subagent_name: str, task: str) -> str:
    """委派子任务给子 Agent，返回其最终输出文本。

    依赖从 ContextVar 获取。异常被 catch 转错误字符串返回（AC10 异常隔离）。
    子图挂 UsageMiddleware 采集 token 消耗并累加进 ctx.usage_totals——宿主在
    父 graph 执行结束后读取并入父级 usage（账本冒泡，防子图消耗无人回收）。
    超时按 spec.timeout_ms wall-clock 控制：同步委派阻塞在父 REACT 的一轮里，
    超时必须诚实返回错误字符串而非卡死父节点。

    委派留痕：finally 提交结构化 trace 进 ctx.delegation_traces（ok/timeout/
    error 全路径）——子图会话即用即弃，这是子 agent 过程的唯一审计通道。
    """
    import asyncio
    import time as _time

    from agent_flow_harness.middleware.builtin.usage import UsageMiddleware
    from agent_flow_harness.subagents.context import get_subagent_context

    timeout_ms = 0.0
    started = _time.monotonic()
    ctx = None
    status = "error"
    error_msg = ""
    usage_summary: "dict[str, Any]" = {}
    final_messages: "list[Any]" = []
    try:
        ctx = get_subagent_context()
        spec = ctx.registry.get(subagent_name)
        timeout_ms = spec.timeout_ms
        tools = ctx.resolve_tools(spec)               # AC7: 已排除 delegate
        llm = ctx.resolve_llm(spec)
        state = ctx.build_subagent_state(spec, task)  # AC8: 全新隔离 state
        # 延迟构建子 agent graph（AC5）。tools 必须传给 build_agent_graph：
        # ToolNode 的执行表在图编译期决定（config 里的 tools 只供 llm_node
        # bind）——不传则 ToolNode 按空 agent_doc 静态解析出空表，LLM 声明
        # 并调用的每个工具都会 "not a valid tool, try one of []"。
        graph = build_agent_graph(_DELEGATE_AGENT_DOC, tools=tools)
        usage_mw = UsageMiddleware()
        config = build_config(
            _DELEGATE_AGENT_DOC, llm, tools=tools,
            # LangGraph recursion_limit 计 super-steps（REACT 一轮 = llm+tool
            # 两步），直接透传 max_turns 只允许约一半轮数——×2+1 对齐语义。
            recursion_limit=spec.max_turns * 2 + 1,
            middlewares=[usage_mw],
        )
        # 打 subagent tag：嵌套子图的 LLM/工具事件会经 contextvar 回调冒泡进
        # 父图 astream_events，app 层适配器 stream_events_to_app_events 按此
        # tag 过滤（游离 text/thinking 与无法配对的 tool_result 不进父对话流）。
        config["tags"] = [*config.get("tags", []), "subagent"]
        # 子图共用硬编码 agent_doc（name="subagent"），运行中事件流只能靠
        # metadata 区分具体是哪个子 agent（trace 是事后审计，不解决实时观测）。
        config.setdefault("metadata", {})["subagent"] = subagent_name
        result_state = await asyncio.wait_for(
            graph.ainvoke(state, config=config),  # type: ignore[call-overload]
            timeout=spec.timeout_ms / 1000,
        )
        usage_summary = usage_mw.summary
        ctx.accumulate_usage(usage_summary)
        final_messages = result_state.get("messages", [])
        status = "ok"
        return extract_final_text(final_messages)
    except asyncio.TimeoutError:
        status = "timeout"
        error_msg = f"timed out after {timeout_ms / 1000:.0f}s"
        return (
            f"Error: subagent '{subagent_name}' timed out after "
            f"{timeout_ms / 1000:.0f}s — task not completed. "
            "Consider delegating a narrower task."
        )
    except Exception as exc:
        error_msg = str(exc)
        logger.warning("delegate_to_subagent failed: %s", exc, exc_info=True)
        return f"Error: {exc}"
    finally:
        # 留痕失败不影响委派主流程（trace 是旁路审计）。
        if ctx is not None:
            try:
                ctx.record_delegation({
                    "subagent": subagent_name,
                    "task": (task or "")[:_TRACE_TASK_MAX],
                    "duration_ms": int((_time.monotonic() - started) * 1000),
                    "status": status,
                    "error": error_msg,
                    "usage": usage_summary,
                    "rounds": _summarize_delegation_rounds(final_messages),
                })
            except Exception:
                logger.debug("delegation_trace_submit_failed", exc_info=True)


delegate_to_subagent = StructuredTool.from_function(
    _delegate_to_subagent,
    name="delegate_to_subagent",
    description=(
        "委派子任务给一个专门的子 Agent 执行，返回子 Agent 的最终输出。"
        "当任务复杂、需要不同工具集或独立上下文时使用。"
    ),
    args_schema=_DelegateArgs,
    coroutine=_delegate_to_subagent,
)


__all__ = ["delegate_to_subagent", "extract_final_text"]
