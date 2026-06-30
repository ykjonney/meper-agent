"""AC4 cover: get_thread_messages reads checkpoint state."""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import MemorySaver

from agent_flow_harness.graph import build_agent_graph, get_thread_messages


def _fake_llm(responses):
    class _LLM:
        model_name = "test"

        def __init__(self, resp):
            self._resp = resp

        def bind_tools(self, _tools):
            return self

        async def ainvoke(self, _messages, _config=None):
            return self._resp.pop(0)

    return _LLM(responses)


@pytest.mark.asyncio
async def test_get_thread_messages_after_invoke(base_state) -> None:
    """After invoking with a checkpointer, get_thread_messages recovers the messages."""
    saver = MemorySaver()
    graph = build_agent_graph({"_id": "a"}, checkpointer=saver)
    llm = _fake_llm([AIMessage(content="hello back")])
    config = {"configurable": {"thread_id": "t1", "llm": llm, "tools": []}}

    await graph.ainvoke(base_state, config=config)

    recovered = await get_thread_messages(graph, "t1")
    assert len(recovered) >= 1
    # The final AI message should be present.
    assert any(getattr(m, "content", "") == "hello back" for m in recovered)


@pytest.mark.asyncio
async def test_get_thread_messages_empty_for_unknown_thread() -> None:
    """A thread_id with no checkpoint returns []."""
    saver = MemorySaver()
    graph = build_agent_graph({"_id": "a"}, checkpointer=saver)
    recovered = await get_thread_messages(graph, "nonexistent")
    assert recovered == []


@pytest.mark.asyncio
async def test_get_thread_messages_without_checkpointer_returns_empty(base_state) -> None:
    """A graph built without a checkpointer returns [] (no state to read)."""
    graph = build_agent_graph({"_id": "a"})  # no checkpointer
    recovered = await get_thread_messages(graph, "t1")
    assert recovered == []


@pytest.mark.asyncio
async def test_get_thread_messages_isolation_between_threads(base_state) -> None:
    """Different thread_ids keep independent state."""
    saver = MemorySaver()
    graph = build_agent_graph({"_id": "a"}, checkpointer=saver)

    llm1 = _fake_llm([AIMessage(content="answer for thread1")])
    await graph.ainvoke(
        base_state,
        config={"configurable": {"thread_id": "t1", "llm": llm1, "tools": []}},
    )

    llm2 = _fake_llm([AIMessage(content="answer for thread2")])
    state2 = {**base_state, "session_id": "s2"}
    await graph.ainvoke(
        state2,
        config={"configurable": {"thread_id": "t2", "llm": llm2, "tools": []}},
    )

    msgs1 = await get_thread_messages(graph, "t1")
    msgs2 = await get_thread_messages(graph, "t2")
    assert any(getattr(m, "content", "") == "answer for thread1" for m in msgs1)
    assert any(getattr(m, "content", "") == "answer for thread2" for m in msgs2)
    assert not any(getattr(m, "content", "") == "answer for thread2" for m in msgs1)
