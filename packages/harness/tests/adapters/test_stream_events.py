"""AC1/AC3-AC11 cover: stream_events_to_app_events mapping (20+ cases).

Each test feeds a scripted list of native ``astream_events`` dicts through the
adapter and asserts the emitted application-layer events (type + fields +
order). A fake LLM/chunk is built with :class:`types.SimpleNamespace` so no
network or provider SDK is needed.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from agent_flow_harness.adapters.stream_events import stream_events_to_app_events


# ---------------------------------------------------------------------------
# Test harness: feed a list of native events, collect emitted app events.
# ---------------------------------------------------------------------------


async def _run(events: list[dict[str, Any]], *, enable_thinking: bool = False) -> list[dict[str, Any]]:
    emitted: list[dict[str, Any]] = []

    async def on_event(ev: Any) -> None:
        emitted.append(ev.model_dump())

    async def _aiter():
        for e in events:
            yield e

    await stream_events_to_app_events(_aiter(), on_event, enable_thinking=enable_thinking)
    return emitted


def _chunk(content: Any = "", *, tool_call_chunks=None, reasoning=None, additional=None) -> SimpleNamespace:
    kwargs: dict[str, Any] = {"content": content}
    if tool_call_chunks is not None:
        kwargs["tool_call_chunks"] = tool_call_chunks
    if additional is not None:
        kwargs["additional_kwargs"] = additional
    msg = SimpleNamespace(**kwargs)
    if reasoning is not None:
        msg.reasoning_content = reasoning
    return msg


def _stream_event(chunk: SimpleNamespace) -> dict[str, Any]:
    return {"event": "on_chat_model_stream", "data": {"chunk": chunk}}


def _end_event(output: SimpleNamespace) -> dict[str, Any]:
    return {"event": "on_chat_model_end", "data": {"output": output}}


def _ai(content: Any = "", *, tool_calls=None, reasoning=None, additional=None) -> SimpleNamespace:
    kwargs: dict[str, Any] = {"content": content, "tool_calls": tool_calls or []}
    ak = dict(additional or {})
    if reasoning is not None:
        ak["reasoning_content"] = reasoning
    kwargs["additional_kwargs"] = ak
    msg = SimpleNamespace(**kwargs)
    if reasoning is not None:
        msg.reasoning_content = reasoning
    return msg


# ---------------------------------------------------------------------------
# on_chat_model_stream — text
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stream_text_delta() -> None:
    emitted = await _run([_stream_event(_chunk("hel")), _stream_event(_chunk("lo"))])
    assert emitted == [
        {"type": "final_answer_delta", "content": "hel"},
        {"type": "final_answer_delta", "content": "lo"},
    ]


@pytest.mark.asyncio
async def test_stream_text_from_list_blocks() -> None:
    """content as list-of-blocks is concatenated text only."""
    chunk = _chunk([{"type": "text", "text": "hi"}, {"type": "text", "text": "!"}])
    emitted = await _run([_stream_event(chunk)])
    assert emitted == [{"type": "final_answer_delta", "content": "hi!"}]


@pytest.mark.asyncio
async def test_stream_empty_content_emits_nothing() -> None:
    emitted = await _run([_stream_event(_chunk(""))])
    assert emitted == []


@pytest.mark.asyncio
async def test_stream_chunk_missing_key_is_safe() -> None:
    """A stream event with no 'chunk' is ignored, not raised."""
    emitted = await _run([{"event": "on_chat_model_stream", "data": {}}])
    assert emitted == []


# ---------------------------------------------------------------------------
# on_chat_model_stream — thinking (enable_thinking switch)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stream_thinking_disabled_by_default() -> None:
    """reasoning_content is suppressed when enable_thinking=False."""
    chunk = _chunk("", reasoning="secret thought")
    emitted = await _run([_stream_event(chunk)])
    assert emitted == []


@pytest.mark.asyncio
async def test_stream_thinking_enabled() -> None:
    chunk = _chunk("answer", reasoning="thinking hard")
    emitted = await _run([_stream_event(chunk)], enable_thinking=True)
    assert {"type": "final_answer_delta", "content": "answer"} in emitted
    assert {"type": "thinking_delta", "content": "thinking hard"} in emitted


@pytest.mark.asyncio
async def test_stream_thinking_from_additional_kwargs() -> None:
    """reasoning_content in additional_kwargs is also captured."""
    chunk = _chunk("", additional={"reasoning_content": "from kw"})
    emitted = await _run([_stream_event(chunk)], enable_thinking=True)
    assert {"type": "thinking_delta", "content": "from kw"} in emitted


# ---------------------------------------------------------------------------
# on_chat_model_stream — tool_call_chunks accumulate (no direct emit)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stream_tool_call_chunks_not_emitted_directly() -> None:
    """Streaming tool_call_chunks are accumulated, never emitted per-chunk."""
    piece = SimpleNamespace(index=0, name="bash", id="c1", args='{"a":')
    chunk = _chunk("", tool_call_chunks=[piece])
    emitted = await _run([_stream_event(chunk)])
    assert emitted == []


# ---------------------------------------------------------------------------
# on_chat_model_end — final answer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_end_final_answer_no_tool_calls() -> None:
    emitted = await _run([_end_event(_ai("the answer"))])
    assert emitted == [{"type": "final_answer", "content": "the answer"}]


@pytest.mark.asyncio
async def test_end_empty_output_emits_nothing() -> None:
    emitted = await _run([_end_event(_ai(""))])  # no content, no calls
    assert emitted == []


# ---------------------------------------------------------------------------
# on_chat_model_end — intermediate text persisted + tool_call
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_end_persists_intermediate_text_with_tool_calls() -> None:
    """AC5: content + tool_calls → final_answer AND tool_call events."""
    output = _ai("let me check", tool_calls=[{"name": "read", "args": {"path": "x"}, "id": "c1"}])
    emitted = await _run([_end_event(output)])
    assert {"type": "final_answer", "content": "let me check"} in emitted
    assert {
        "type": "tool_call",
        "tool_name": "read",
        "args": {"path": "x"},
        "id": "c1",
    } in emitted
    # final_answer precedes tool_call.
    assert emitted.index({"type": "final_answer", "content": "let me check"}) < emitted.index(
        {"type": "tool_call", "tool_name": "read", "args": {"path": "x"}, "id": "c1"}
    )


@pytest.mark.asyncio
async def test_end_multiple_tool_calls_in_one_message() -> None:
    output = _ai(
        "",
        tool_calls=[
            {"name": "a", "args": {}, "id": "1"},
            {"name": "b", "args": {"k": 1}, "id": "2"},
        ],
    )
    emitted = await _run([_end_event(output)])
    assert len(emitted) == 2
    assert {e["tool_name"] for e in emitted} == {"a", "b"}


@pytest.mark.asyncio
async def test_end_empty_tool_calls_emits_nothing() -> None:
    emitted = await _run([_end_event(_ai("", tool_calls=[]))])
    assert emitted == []


# ---------------------------------------------------------------------------
# on_chat_model_end — thinking full
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_end_thinking_full_enabled() -> None:
    output = _ai("answer", reasoning="full reasoning")
    emitted = await _run([_end_event(output)], enable_thinking=True)
    assert {"type": "thinking", "content": "full reasoning"} in emitted
    assert {"type": "final_answer", "content": "answer"} in emitted
    # thinking emitted before final_answer.
    assert emitted.index({"type": "thinking", "content": "full reasoning"}) < emitted.index(
        {"type": "final_answer", "content": "answer"}
    )


@pytest.mark.asyncio
async def test_end_thinking_full_disabled() -> None:
    output = _ai("answer", reasoning="full reasoning")
    emitted = await _run([_end_event(output)], enable_thinking=False)
    assert {"type": "thinking", "content": "full reasoning"} not in emitted
    assert {"type": "final_answer", "content": "answer"} in emitted


@pytest.mark.asyncio
async def test_end_thinking_from_blocks() -> None:
    """Anthropic-style thinking blocks in content are extracted."""
    output = SimpleNamespace(
        content=[{"type": "thinking", "thinking": "block thought"}],
        tool_calls=[],
        additional_kwargs={},
    )
    emitted = await _run([_end_event(output)], enable_thinking=True)
    assert {"type": "thinking", "content": "block thought"} in emitted


# ---------------------------------------------------------------------------
# on_tool_start / on_tool_end
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_start_emits_placeholder() -> None:
    emitted = await _run([{"event": "on_tool_start", "name": "bash", "data": {}}])
    assert emitted == [{"type": "tool_call_start"}]


@pytest.mark.asyncio
async def test_tool_end_emits_result() -> None:
    emitted = await _run(
        [{"event": "on_tool_end", "name": "bash", "data": {"output": "done"}}]
    )
    assert emitted == [{"type": "tool_result", "tool_name": "bash", "content": "done"}]


@pytest.mark.asyncio
async def test_tool_end_none_output_empty_content() -> None:
    emitted = await _run([{"event": "on_tool_end", "name": "x", "data": {"output": None}}])
    assert emitted == [{"type": "tool_result", "tool_name": "x", "content": ""}]


# ---------------------------------------------------------------------------
# error events
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_error_event() -> None:
    emitted = await _run(
        [{"event": "on_llm_error", "data": {"error": RuntimeError("rate limit")}}]
    )
    assert emitted == [{"type": "error", "message": "rate limit", "source": "llm"}]


@pytest.mark.asyncio
async def test_chat_model_error_treated_as_llm_error() -> None:
    emitted = await _run(
        [{"event": "on_chat_model_error", "data": {"error": ValueError("boom")}}]
    )
    assert emitted == [{"type": "error", "message": "boom", "source": "llm"}]


@pytest.mark.asyncio
async def test_tool_error_event() -> None:
    emitted = await _run([{"event": "on_tool_error", "data": {"error": "kaboom"}}])
    assert emitted == [{"type": "error", "message": "kaboom", "source": "tool"}]


# ---------------------------------------------------------------------------
# misc: unrelated events ignored, accumulator reset, full sequence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unrelated_events_ignored() -> None:
    emitted = await _run(
        [
            {"event": "on_chain_start", "data": {}},
            {"event": "on_chain_end", "data": {}},
            {"event": "on_prompt_start", "data": {}},
        ]
    )
    assert emitted == []


@pytest.mark.asyncio
async def test_full_conversation_sequence() -> None:
    """A turn: stream answer, then tool round, then final answer."""
    events = [
        _stream_event(_chunk("hello")),
        _end_event(
            _ai("hello", tool_calls=[{"name": "read", "args": {"p": "x"}, "id": "c1"}])
        ),
        {"event": "on_tool_start", "name": "read", "data": {}},
        {"event": "on_tool_end", "name": "read", "data": {"output": "file"}},
        _end_event(_ai("final")),
    ]
    emitted = await _run(events)

    assert emitted[0] == {"type": "final_answer_delta", "content": "hello"}
    assert {"type": "final_answer", "content": "hello"} in emitted
    assert {
        "type": "tool_call",
        "tool_name": "read",
        "args": {"p": "x"},
        "id": "c1",
    } in emitted
    assert {"type": "tool_call_start"} in emitted
    assert {"type": "tool_result", "tool_name": "read", "content": "file"} in emitted
    assert emitted[-1] == {"type": "final_answer", "content": "final"}


@pytest.mark.asyncio
async def test_accumulator_reset_between_turns() -> None:
    """Two model-end events don't bleed accumulated chunks into each other."""
    piece = SimpleNamespace(index=0, name="bash", id="c1", args='{"a":1}')
    events = [
        _stream_event(_chunk("", tool_call_chunks=[piece])),
        _end_event(_ai("")),  # no tool_calls → nothing emitted, accumulator reset
        _stream_event(_chunk("next")),
        _end_event(_ai("next")),
    ]
    emitted = await _run(events)
    # Only the final_answer from the second turn; no stale tool_call.
    assert {"type": "final_answer", "content": "next"} in emitted
    assert all(e["type"] != "tool_call" for e in emitted)
