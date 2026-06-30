"""AC2 cover: the 8 AppEvent models dump to legacy-compatible dicts."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent_flow_harness.adapters.app_event import (
    ErrorEvent,
    FinalAnswerDeltaEvent,
    FinalAnswerEvent,
    ThinkingDeltaEvent,
    ThinkingEvent,
    ToolCallEvent,
    ToolCallStartEvent,
    ToolResultEvent,
)


def test_thinking_delta_dump() -> None:
    assert ThinkingDeltaEvent(content="x").model_dump() == {
        "type": "thinking_delta",
        "content": "x",
    }


def test_thinking_dump() -> None:
    assert ThinkingEvent(content="x").model_dump() == {"type": "thinking", "content": "x"}


def test_final_answer_delta_dump() -> None:
    assert FinalAnswerDeltaEvent(content="x").model_dump() == {
        "type": "final_answer_delta",
        "content": "x",
    }


def test_final_answer_dump() -> None:
    assert FinalAnswerEvent(content="x").model_dump() == {
        "type": "final_answer",
        "content": "x",
    }


def test_tool_call_start_dump() -> None:
    assert ToolCallStartEvent().model_dump() == {"type": "tool_call_start"}


def test_tool_call_dump() -> None:
    assert ToolCallEvent(tool_name="bash", args={"q": 1}, id="c1").model_dump() == {
        "type": "tool_call",
        "tool_name": "bash",
        "args": {"q": 1},
        "id": "c1",
    }


def test_tool_result_dump() -> None:
    assert ToolResultEvent(tool_name="bash", content="ok").model_dump() == {
        "type": "tool_result",
        "tool_name": "bash",
        "content": "ok",
    }


def test_error_dump_source_values() -> None:
    assert ErrorEvent(message="boom", source="llm").model_dump() == {
        "type": "error",
        "message": "boom",
        "source": "llm",
    }
    assert ErrorEvent(message="boom", source="tool").source == "tool"


def test_error_rejects_invalid_source() -> None:
    with pytest.raises(ValidationError):
        ErrorEvent(message="boom", source="network")  # type: ignore[arg-type]


def test_extra_fields_rejected() -> None:
    """extra='forbid' keeps the schema tight against drift."""
    with pytest.raises(ValidationError):
        FinalAnswerEvent(content="x", surprise=True)  # type: ignore[call-arg]
