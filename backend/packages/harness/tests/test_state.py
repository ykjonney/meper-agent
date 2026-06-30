"""AC6 cover: AgentState is the expected TypedDict shape."""

from __future__ import annotations

from agent_flow_harness.state import AgentState


def test_agent_state_is_typeddict() -> None:
    """AgentState must be a TypedDict so LangGraph can merge its keys."""
    import typing

    assert issubclass(AgentState, dict)
    # TypedDict classes carry __required_keys__ / __optional_keys__ and expose
    # their annotated fields via get_type_hints.
    assert hasattr(AgentState, "__required_keys__")
    assert typing.get_type_hints(AgentState)


def test_agent_state_has_core_fields() -> None:
    """The fields the backend depends on must all be declared."""
    hints = AgentState.__annotations__
    for field in (
        "messages",
        "agent_id",
        "session_id",
        "call_chain",
        "step_count",
        "error",
    ):
        assert field in hints, f"AgentState missing field: {field}"


def test_agent_state_constructs_from_kwargs() -> None:
    state: AgentState = AgentState(  # type: ignore[call-arg]
        messages=[],
        agent_id="a",
        execution_path="react",
        request_id="r",
        tool_results={},
        step_count=0,
        error=None,
        call_chain=[],
        current_depth=0,
        session_id="s",
        user_id="u",
    )
    assert state["agent_id"] == "a"
    assert state["error"] is None
