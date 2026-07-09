"""harness execution — stream / invoke / resume entry points.

Each function assembles the harness context (via ``resolve_harness_context``),
builds the graph + config, and executes. ErrorEvent fields are remapped to
match the frontend contract (``message`` → ``content``).
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agent_flow_harness.adapters.app_event import AppEvent

from app.engine.harness_integration.context import (
    _maybe_migrate_legacy,
    get_checkpointer,
    release_harness_context,
    resolve_harness_context,
)


def _make_event_callback(on_event):
    """Create an adapter that converts AppEvent → dict and remaps error fields."""

    async def _on_event_dict(app_event: AppEvent) -> None:
        data = app_event.model_dump()
        # ErrorEvent 字段是 {message, source},前端契约用 {content}。
        if data.get("type") == "error":
            data["content"] = data.pop("message", "")
        await on_event(data)

    return _on_event_dict


async def stream(
    agent: dict,
    state: dict,
    on_event,
    *,
    enable_thinking: bool = False,
    legacy_records: list[dict] | None = None,
) -> dict:
    """流式执行 harness graph,通过 on_event 推送 AppEvent dict。"""
    from agent_flow_harness import build_agent_graph, build_config
    from agent_flow_harness.adapters import stream_events_to_app_events

    hctx = await resolve_harness_context(agent, state, enable_thinking=enable_thinking)
    try:
        session_id = state.get("session_id", "")
        graph = build_agent_graph(
            hctx["agent_doc"], checkpointer=get_checkpointer(),
            middleware=hctx["middlewares"], tools=hctx["tools"],
        )
        config = build_config(
            hctx["agent_doc"],
            hctx["llm"],
            tools=hctx["tools"],
            context_window=hctx["context_window"],
            middlewares=hctx["middlewares"],
            thread_id=session_id,
        )
        await _maybe_migrate_legacy(graph, config, legacy_records)

        event_stream = graph.astream_events(state, config=config, version="v2")
        await stream_events_to_app_events(
            event_stream,
            _make_event_callback(on_event),
            enable_thinking=enable_thinking,
        )
    finally:
        release_harness_context(hctx)

    return {"step_count": 0}


async def invoke(
    agent: dict,
    state: dict,
    *,
    enable_thinking: bool = False,
    workspace: Any | None = None,
    legacy_records: list[dict] | None = None,
) -> dict:
    """非流式执行 harness graph(供 invoke 端点 / workflow agent 节点使用)。"""
    from agent_flow_harness import build_agent_graph, build_config

    hctx = await resolve_harness_context(
        agent, state, enable_thinking=enable_thinking, workspace=workspace,
    )
    try:
        session_id = state.get("session_id", "")
        graph = build_agent_graph(
            hctx["agent_doc"], checkpointer=get_checkpointer(),
            middleware=hctx["middlewares"], tools=hctx["tools"],
        )
        config = build_config(
            hctx["agent_doc"],
            hctx["llm"],
            tools=hctx["tools"],
            context_window=hctx["context_window"],
            middlewares=hctx["middlewares"],
            thread_id=session_id,
        )
        await _maybe_migrate_legacy(graph, config, legacy_records)
        return await graph.ainvoke(state, config=config)
    finally:
        release_harness_context(hctx)


async def resume(
    agent: dict,
    state: dict,
    on_event,
    answer: str,
    *,
    enable_thinking: bool = False,
) -> dict:
    """恢复被 interrupt 挂起的 graph,用 Command(resume=answer) 继续。"""
    from agent_flow_harness import build_agent_graph, build_config
    from agent_flow_harness.adapters import stream_events_to_app_events
    from langgraph.types import Command

    hctx = await resolve_harness_context(agent, state, enable_thinking=enable_thinking)
    try:
        session_id = state.get("session_id", "")
        graph = build_agent_graph(
            hctx["agent_doc"], checkpointer=get_checkpointer(),
            middleware=hctx["middlewares"], tools=hctx["tools"],
        )
        config = build_config(
            hctx["agent_doc"],
            hctx["llm"],
            tools=hctx["tools"],
            context_window=hctx["context_window"],
            middlewares=hctx["middlewares"],
            thread_id=session_id,
        )

        event_stream = graph.astream_events(
            Command(resume=answer), config=config, version="v2",
        )
        await stream_events_to_app_events(
            event_stream,
            _make_event_callback(on_event),
            enable_thinking=enable_thinking,
        )
    finally:
        release_harness_context(hctx)

    return {"step_count": 0}
