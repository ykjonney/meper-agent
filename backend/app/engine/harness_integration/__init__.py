"""应用层 ↔ harness Integration Adapter(骨架)。

本模块确立"应用层如何调用 harness"的模式,是 session→thread 迁移的接线层。
当前仅签名 + TODO + 示例注释,未实际接线——agents.py/sessions.py 仍走旧路径,
待迁移切换后启用本模块。

三层架构:
    ① API 层 (FastAPI)         app/api/v1/*          只懂 HTTP + 业务语义
    ② Integration Adapter 层   app/engine/harness_*  本模块:应用层世界 ↔ harness
    ③ harness                  agent_flow_harness    纯净,不认 app.*

应用层调 harness 的契约收敛为两件事:
    - 装配: resolve_*() 把应用层对象(Session/Agent/workspace/model table)
            变成 harness 注入物(llm/tools/agent_doc/checkpointer)
    - 调用: build_agent_graph / build_config / stream_events_to_app_events /
            messages_to_app_events

本模块分三类函数:装配注入物 / 执行 / 输出转换。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from agent_flow_harness.adapters.app_event import AppEvent
    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.tools import BaseTool


# ===========================================================================
# ① 装配注入物(应用层世界 → harness)
# ===========================================================================


async def resolve_llm(agent: dict, *, enable_thinking: bool = False) -> BaseChatModel:
    """查 model table + 解密 API key,构建 LLM 客户端。

    委托现有 ``app.engine.llm_factory.get_llm_client`` 完成 model-table 查找与解密,
    返回的 BaseChatModel 注入 harness 的 ``build_config(llm=...)``。

    TODO(迁移): 当前未接线。agents.py 切换到 harness 后,此处调用:
        from app.engine.llm_factory import get_llm_client
        return await get_llm_client(agent, enable_thinking=enable_thinking)
    """
    raise NotImplementedError("resolve_llm 待迁移接线")


def resolve_tools(agent: dict, workspace: Any | None = None) -> list[BaseTool]:
    """从 agent_doc 解析工具列表,注入 workspace。

    调用 ``TOOL_REGISTRY.resolve(agent_doc)`` 得到工具列表。
    workspace 对象通过 harness contextvar 注入(隔离文件操作)。

    TODO(迁移): 当前未接线。切换后:
        from agent_flow_harness import TOOL_REGISTRY
        agent_doc = build_agent_doc(agent)
        return TOOL_REGISTRY.resolve(agent_doc)
    """
    raise NotImplementedError("resolve_tools 待迁移接线")


def resolve_guards(agent_doc: dict) -> list:
    """从 agent_doc["guards"] 配置实例化 Guard 列表。

    TODO(迁移): 当前未接线。切换后:
        from agent_flow_harness import resolve_guards
        return resolve_guards(agent_doc.get("guards"))
    """
    raise NotImplementedError("resolve_guards 待迁移接线")


def resolve_middleware(agent_doc: dict) -> list:
    """从 agent_doc["middleware"] 配置实例化 Middleware 列表。

    TODO(迁移): 当前未接线。切换后:
        from agent_flow_harness import resolve_middleware
        return resolve_middleware(agent_doc.get("middleware"))
    """
    raise NotImplementedError("resolve_middleware 待迁移接线")


def get_checkpointer() -> Any:
    """构造 MongoDBSaver 并注入 harness 单例。

    替代 backend 现有的 ``app.engine.checkpointer.get_checkpointer``。
    在进程启动时(lifespan)调用一次,而非每次 build graph。

    TODO(迁移): 当前未接线。切换后(lifespan/startup):
        from agent_flow_harness import build_mongo_saver, configure_checkpointer
        from app.db.mongodb import get_mongodb_client
        from app.core.config import settings
        saver = build_mongo_saver(
            client=get_mongodb_client().delegate,
            db_name=settings.MONGODB_DB_NAME,
        )
        configure_checkpointer(saver)
        return saver
    """
    raise NotImplementedError("get_checkpointer 待迁移接线")


def build_agent_doc(agent: dict) -> dict:
    """组装 agent_doc(slots/guards/tools/middleware 配置)。

    从 backend Agent 文档提取 harness 需要的配置子集。

    TODO(迁移): 当前未接线。切换后:
        return {
            "_id": agent["_id"],
            "prompt_slots": agent.get("prompt_slots", {}),
            "guards": agent.get("guards", []),
            "tools": agent.get("tools", []),
            "middleware": agent.get("middleware", []),
        }
    """
    raise NotImplementedError("build_agent_doc 待迁移接线")


# ===========================================================================
# ② 执行(调用 harness)
# ===========================================================================


async def run_chat(
    agent: dict,
    session: dict,
    user_input: str,
    *,
    enable_thinking: bool = False,
) -> AsyncIterator[AppEvent]:
    """装配 + 执行 agent 图,yield AppEvent 流。

    这是实时聊天路径的完整接线示例。替换 agents.py 的 stream 端点。

    TODO(迁移): 当前未接线。切换后:
        from agent_flow_harness import (
            build_agent_graph, build_config,
            stream_events_to_app_events,
        )

        agent_doc = build_agent_doc(agent)
        llm = await resolve_llm(agent, enable_thinking=enable_thinking)
        tools = resolve_tools(agent, workspace=session.get("workspace"))
        graph = build_agent_graph(agent_doc)
        config = build_config(
            agent_doc, llm, tools=tools,
            thread_id=session["_id"],            # thread_id = session_id
            workspace=session.get("workspace"),
        )

        input_state = {
            "messages": [HumanMessage(content=user_input)],
            "session_id": session["_id"],
            "agent_id": agent["_id"],
            ...
        }

        async def _collect(events):
            collected = []
            async def on_event(ev):
                collected.append(ev)
                yield ev  # yield AppEvent 给上层
            await stream_events_to_app_events(
                graph.astream_events(input_state, config=config, version="v2"),
                on_event,
                enable_thinking=enable_thinking,
            )
        ...
    """
    raise NotImplementedError("run_chat 待迁移接线")
    yield  # make this an async generator for type checking  # pragma: no cover


async def get_history(session_id: str) -> list[AppEvent]:
    """从 thread 读取历史 messages,转成 AppEvent 列表。

    替换 sessions.py 的 ``MessageService.list_messages`` +
    ``_history_to_langchain_messages`` 重建逻辑。thread 是单一数据源。

    TODO(迁移): 当前未接线。切换后:
        from agent_flow_harness import get_thread_messages, messages_to_app_events

        agent_doc = ...  # 从 session 取 agent
        graph = build_agent_graph(agent_doc, checkpointer=get_checkpointer())
        messages = await get_thread_messages(graph, thread_id=session_id)
        return messages_to_app_events(messages, enable_thinking=...)
    """
    raise NotImplementedError("get_history 待迁移接线")


# ===========================================================================
# ③ 输出转换(harness → 应用层/前端)
# ===========================================================================


def app_event_to_timeline_entry(event: AppEvent) -> dict:
    """AppEvent → 前端 timeline_entries 形状(前端零改动的默认实现)。

    应用层可覆盖此函数实现自定义信息结构。默认输出与现有
    ``timeline_entries`` dict 兼容(前端 historyEntryToTimeline 直接消费)。

    示例:
        ToolCallEvent → {"type": "tool_call", "tool_name": ..., "args": ...}
        ToolResultEvent → {"type": "tool_result", "tool_name": ..., "content": ...}
        FinalAnswerEvent → {"type": "final_answer", "content": ...}
        ThinkingEvent → {"type": "thinking", "content": ...}
        (tool_call_start / *_delta / error 在历史路径不出现)

    TODO(迁移): 当前未接线。切换后实现上述映射。
    """
    raise NotImplementedError("app_event_to_timeline_entry 待迁移接线")


def app_events_to_message(
    events: list[AppEvent],
    *,
    role: str = "agent",
) -> dict:
    """AppEvent 列表 → MessageRecord 形状(兼容前端 historyToMessages)。

    默认实现把 events 经 app_event_to_timeline_entry 转成 timeline_entries,
    并提取最后一个 final_answer 的 content 作为消息正文。

    应用层可覆盖以自定义消息结构。

    TODO(迁移): 当前未接线。
    """
    raise NotImplementedError("app_events_to_message 待迁移接线")


__all__ = [
    "app_event_to_timeline_entry",
    "app_events_to_message",
    "build_agent_doc",
    "get_checkpointer",
    "get_history",
    "resolve_guards",
    "resolve_llm",
    "resolve_middleware",
    "resolve_tools",
    "run_chat",
]
