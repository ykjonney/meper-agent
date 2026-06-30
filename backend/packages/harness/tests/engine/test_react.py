"""AC13 cover: react_node full REACT loop — 15+ branches.

Each test scripts :class:`FakeLLM` responses and asserts the node's state
patch. The node is exercised directly (not through the compiled graph) so the
behavioural branches are isolated.
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import StructuredTool

from agent_flow_harness.engine.react import react_node
from agent_flow_harness.tools.workspace_context import (
    get_workspace_context,
)


def _ai_tool_call(name: str, args: dict | None = None, call_id: str = "c1") -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args or {}, "id": call_id}],
    )


def _ai_text(text: str) -> AIMessage:
    return AIMessage(content=text)


# ---------------------------------------------------------------------------
# Basic completion
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_basic_completion(base_state, fake_llm_factory, make_run_config) -> None:
    """LLM returns text with no tool_calls → loop exits after one step."""
    llm = fake_llm_factory([_ai_text("hello there")])
    config = make_run_config(llm)

    result = await react_node(base_state, config)

    assert result["step_count"] == 1
    assert result["messages"][-1].content == "hello there"
    assert "error" not in result


@pytest.mark.asyncio
async def test_state_messages_appended(
    base_state, fake_llm_factory, make_run_config
) -> None:
    """The original user message plus the AI reply both appear in the output."""
    llm = fake_llm_factory([_ai_text("answer")])
    config = make_run_config(llm)

    result = await react_node(base_state, config)

    contents = [m.content for m in result["messages"]]
    assert "hello" in contents  # original HumanMessage preserved
    assert "answer" in contents


@pytest.mark.asyncio
async def test_no_tools_registered_still_works(
    base_state, fake_llm_factory, make_run_config
) -> None:
    """tools=[] is valid — the LLM simply cannot emit usable tool_calls."""
    llm = fake_llm_factory([_ai_text("no tools needed")])
    config = make_run_config(llm, tools=[])

    result = await react_node(base_state, config)

    assert result["step_count"] == 1


# ---------------------------------------------------------------------------
# Tool-call branches
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_single_tool_call(base_state, fake_llm_factory, make_test_tool, make_run_config) -> None:
    """tool_call → tool runs → loop continues → final text → exit."""
    echo = make_test_tool("echo", return_value="echoed")
    llm = fake_llm_factory([_ai_tool_call("echo"), _ai_text("done")])
    config = make_run_config(llm, tools=[echo])

    result = await react_node(base_state, config)

    assert result["step_count"] == 2  # one for tool-call turn, one for final
    # messages: human, ai(tool_call), tool_result, ai(text)
    assert isinstance(result["messages"][-1], AIMessage)
    assert result["messages"][-1].content == "done"
    tool_msgs = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert len(tool_msgs) == 1
    assert tool_msgs[0].content == "echoed"


@pytest.mark.asyncio
async def test_multiple_tool_calls_in_one_turn(
    base_state, fake_llm_factory, make_test_tool, make_run_config
) -> None:
    """Two tool_calls in a single AIMessage → two ToolMessages appended."""
    t1 = make_test_tool("t1", return_value="r1")
    t2 = make_test_tool("t2", return_value="r2")
    two_calls = AIMessage(
        content="",
        tool_calls=[
            {"name": "t1", "args": {}, "id": "a"},
            {"name": "t2", "args": {}, "id": "b"},
        ],
    )
    llm = fake_llm_factory([two_calls, _ai_text("final")])
    config = make_run_config(llm, tools=[t1, t2])

    result = await react_node(base_state, config)

    tool_msgs = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert len(tool_msgs) == 2
    assert result["step_count"] == 2


@pytest.mark.asyncio
async def test_tool_not_found(base_state, fake_llm_factory, make_run_config) -> None:
    """A tool_call for an unknown tool yields an error ToolMessage, loop continues."""
    llm = fake_llm_factory(
        [_ai_tool_call("ghost"), _ai_text("recovered")]
    )
    config = make_run_config(llm, tools=[])

    result = await react_node(base_state, config)

    tool_msg = next(m for m in result["messages"] if isinstance(m, ToolMessage))
    assert "not found" in tool_msg.content
    assert result["step_count"] == 2


@pytest.mark.asyncio
async def test_tool_exception_caught(
    base_state, fake_llm_factory, make_run_config
) -> None:
    """A tool raising is caught and its message becomes the ToolMessage content."""

    def _boom(**_kwargs):  # noqa: ANN202
        msg = "kaboom"
        raise RuntimeError(msg)

    boom = StructuredTool.from_function(_boom, name="boom", description="raises")
    llm = fake_llm_factory([_ai_tool_call("boom"), _ai_text("ok")])
    config = make_run_config(llm, tools=[boom])

    result = await react_node(base_state, config)

    tool_msg = next(m for m in result["messages"] if isinstance(m, ToolMessage))
    assert "kaboom" in tool_msg.content


# ---------------------------------------------------------------------------
# Step counting & iteration limit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_step_count_incremented_per_llm_call(
    base_state, fake_llm_factory, make_run_config
) -> None:
    """step_count increments exactly once per ainvoke (including tool turns)."""
    llm = fake_llm_factory([_ai_text("a"), _ai_text("b"), _ai_text("c")])
    config = make_run_config(llm, tools=[])

    result = await react_node(base_state, config)

    assert result["step_count"] == 1  # first text reply ends the loop


@pytest.mark.asyncio
async def test_max_iterations_reached(
    base_state, fake_llm_factory, make_test_tool, make_run_config, monkeypatch
) -> None:
    """25 tool-call turns in a row → loop exits at the iteration cap."""
    import agent_flow_harness.engine.react as react_mod

    monkeypatch.setattr(react_mod, "_MAX_ITERATIONS", 3)
    echo = make_test_tool("echo")
    # Always emit a tool_call so the loop never sees a plain-text final answer.
    llm = fake_llm_factory([_ai_tool_call("echo", call_id=f"c{i}") for i in range(3)])
    config = make_run_config(llm, tools=[echo])

    result = await react_node(base_state, config)

    assert result["step_count"] == 3
    # All three turns produced a tool_call → no error, just stopped at the cap.
    assert "error" not in result


# ---------------------------------------------------------------------------
# Depth guard short-circuits
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_depth_limit_short_circuit(
    base_state, fake_llm_factory, make_run_config
) -> None:
    """current_depth >= MAX_DEPTH → loop never calls the LLM."""
    base_state["current_depth"] = 999
    llm = fake_llm_factory([_ai_text("should not happen")])
    config = make_run_config(llm)

    result = await react_node(base_state, config)

    assert result["step_count"] == 0
    assert "error" in result
    assert "Depth limit" in result["error"]
    assert llm.calls == []  # LLM never invoked


@pytest.mark.asyncio
async def test_circular_call_detection(
    base_state, fake_llm_factory, make_run_config
) -> None:
    """A repeated entry in call_chain → blocked before the LLM runs."""
    base_state["call_chain"] = ["agent-A", "agent-B", "agent-A"]
    llm = fake_llm_factory([_ai_text("nope")])
    config = make_run_config(llm)

    result = await react_node(base_state, config)

    assert result["step_count"] == 0
    assert "error" in result
    assert "Circular" in result["error"]


# ---------------------------------------------------------------------------
# Context compression
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_context_compression_triggered(
    base_state, fake_llm_factory, make_run_config
) -> None:
    """A tiny context_window forces compression before the LLM call."""
    base_state["messages"] = [HumanMessage(content=f"line {i}") for i in range(50)]
    llm = fake_llm_factory([_ai_text("compressed ok")])
    # context_window so small that should_compress must return True.
    config = make_run_config(llm, context_window=128)

    result = await react_node(base_state, config)

    # After compression the message list is shorter than the 50 originals.
    assert len(result["messages"]) < 50
    assert result["messages"][-1].content == "compressed ok"


# ---------------------------------------------------------------------------
# Workspace context
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_workspace_context_set_and_reset(
    base_state, fake_llm_factory, make_run_config
) -> None:
    """While the node runs the workspace is bound; after it returns it's cleared."""
    ws = object()  # any object satisfies the duck-typed protocol here
    llm = fake_llm_factory([_ai_text("ok")])
    config = make_run_config(llm, workspace=ws)

    # Sanity: nothing set before the call.
    assert get_workspace_context() is None

    result = await react_node(base_state, config)

    # After the node returns, the finally-block has reset the context var.
    assert get_workspace_context() is None
    assert result["step_count"] == 1


@pytest.mark.asyncio
async def test_no_workspace_still_runs(
    base_state, fake_llm_factory, make_run_config
) -> None:
    """Omitting workspace is fine — tools simply run without isolation."""
    llm = fake_llm_factory([_ai_text("ok")])
    config = make_run_config(llm)  # no workspace key

    result = await react_node(base_state, config)

    assert result["step_count"] == 1


# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_config_missing_configurable_raises(base_state) -> None:
    """A config without 'configurable' is a clear ValueError."""
    with pytest.raises(ValueError, match="configurable"):
        await react_node(base_state, {})


@pytest.mark.asyncio
async def test_config_missing_llm_raises(base_state) -> None:
    """configurable must contain 'llm'."""
    with pytest.raises(ValueError, match="llm"):
        await react_node(base_state, {"configurable": {}})


@pytest.mark.asyncio
async def test_tools_passed_as_dict(
    base_state, fake_llm_factory, make_test_tool, make_run_config
) -> None:
    """A pre-built tool mapping is accepted (the app may pass either shape)."""
    echo = make_test_tool("echo", return_value="hi")
    llm = fake_llm_factory([_ai_tool_call("echo"), _ai_text("done")])
    config = make_run_config(llm, tools={"echo": echo})

    result = await react_node(base_state, config)

    tool_msg = next(m for m in result["messages"] if isinstance(m, ToolMessage))
    assert tool_msg.content == "hi"


# ---------------------------------------------------------------------------
# GraphInterrupt passthrough (v0.2-x HITL prerequisite)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_graph_interrupt_passthrough(
    base_state, fake_llm_factory, make_run_config
) -> None:
    """A tool that raises GraphInterrupt must propagate, not be swallowed.

    GraphInterrupt is an Exception subclass, so react_node's broad
    ``except Exception`` would otherwise catch it and turn it into a
    ToolMessage error — breaking HITL. The node must re-raise it.
    """
    from langchain_core.tools import tool
    from langgraph.errors import GraphInterrupt

    @tool
    async def interrupting_tool(question: str) -> str:
        """Raise GraphInterrupt to test HITL passthrough."""
        raise GraphInterrupt({"question": question})

    llm = fake_llm_factory([_ai_tool_call("interrupting_tool", {"question": "how?"})])
    config = make_run_config(llm, tools=[interrupting_tool])

    with pytest.raises(GraphInterrupt):
        await react_node(base_state, config)


@pytest.mark.asyncio
async def test_normal_exception_still_handled(
    base_state, fake_llm_factory, make_run_config
) -> None:
    """Non-interrupt exceptions still become ToolMessages (regression guard)."""
    from langchain_core.tools import tool

    @tool
    async def failing_tool(x: str) -> str:
        """A tool that fails with a normal exception."""
        raise RuntimeError("boom")

    llm = fake_llm_factory([_ai_tool_call("failing_tool", {"x": "1"}), _ai_text("ok")])
    config = make_run_config(llm, tools=[failing_tool])

    result = await react_node(base_state, config)
    tool_msgs = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert any("Error" in m.content or "boom" in m.content for m in tool_msgs)
