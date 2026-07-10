"""AC7 cover: build_agent_graph builds a node-based graph (compress/llm/tools)."""

from __future__ import annotations

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph.state import CompiledStateGraph

from agent_flow_harness.graph import build_agent_graph


def test_build_agent_graph_returns_compiled_graph(agent_doc: dict) -> None:
    graph = build_agent_graph(agent_doc, tools=[], middleware=[])
    assert isinstance(graph, CompiledStateGraph)


def test_build_agent_graph_has_node_topology(agent_doc: dict) -> None:
    """v0.3 topology: compress + llm + tools (node-based, no 'react')."""
    graph = build_agent_graph(agent_doc, tools=[], middleware=[])
    user_nodes = set(graph.nodes) - {"__start__", "__end__"}
    assert user_nodes == {"compress", "llm", "tools"}


def test_build_agent_graph_accepts_checkpointer(
    agent_doc: dict, in_memory_checkpointer: MemorySaver
) -> None:
    graph = build_agent_graph(
        agent_doc, checkpointer=in_memory_checkpointer, tools=[], middleware=[],
    )
    assert isinstance(graph, CompiledStateGraph)


def test_build_agent_graph_accepts_guards_and_middleware_stubs(agent_doc: dict) -> None:
    """Signature is stable: guards/middleware kwargs accepted."""
    graph = build_agent_graph(agent_doc, guards=None, middleware=[], tools=[])
    assert isinstance(graph, CompiledStateGraph)


@pytest.mark.asyncio
async def test_build_agent_graph_runs_llm_node(
    agent_doc: dict, base_state, fake_llm_factory, make_run_config
) -> None:
    """Invoking the graph runs the llm node with the injected config."""
    from langchain_core.messages import AIMessage

    llm = fake_llm_factory([AIMessage(content="graph ok")])
    graph = build_agent_graph(agent_doc, tools=[], middleware=[])
    result = await graph.ainvoke(base_state, config=make_run_config(llm))
    assert result["step_count"] == 1
    assert result["messages"][-1].content == "graph ok"


@pytest.mark.asyncio
async def test_cancel_checker_triggers_interrupt(
    agent_doc: dict, base_state, fake_llm_factory, in_memory_checkpointer
) -> None:
    """When cancel_checker returns True, compress_node calls interrupt() and
    the graph suspends (result contains __interrupt__).
    """
    from langchain_core.messages import AIMessage

    from agent_flow_harness.graph import build_config

    llm = fake_llm_factory([AIMessage(content="should not reach")])

    cancelled = True

    async def _cancel_checker() -> bool:
        return cancelled

    graph = build_agent_graph(
        agent_doc, checkpointer=in_memory_checkpointer, tools=[], middleware=[],
    )
    config = build_config(
        agent_doc, llm, tools=[], middlewares=[],
        thread_id="cancel-test",
        cancel_checker=_cancel_checker,
    )
    result = await graph.ainvoke(base_state, config=config)
    # Graph should be interrupted, not completed
    assert "__interrupt__" in result, f"Expected __interrupt__, got: {result.keys()}"


@pytest.mark.asyncio
async def test_cancel_checker_false_runs_normally(
    agent_doc: dict, base_state, fake_llm_factory, in_memory_checkpointer
) -> None:
    """When cancel_checker returns False, the graph runs normally."""
    from langchain_core.messages import AIMessage

    from agent_flow_harness.graph import build_config

    llm = fake_llm_factory([AIMessage(content="done")])

    async def _cancel_checker() -> bool:
        return False

    graph = build_agent_graph(
        agent_doc, checkpointer=in_memory_checkpointer, tools=[], middleware=[],
    )
    config = build_config(
        agent_doc, llm, tools=[], middlewares=[],
        thread_id="no-cancel-test",
        cancel_checker=_cancel_checker,
    )
    result = await graph.ainvoke(base_state, config=config)
    assert "__interrupt__" not in result
    assert result["messages"][-1].content == "done"
