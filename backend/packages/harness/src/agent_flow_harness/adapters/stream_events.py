"""astream_events → application-layer event adapter.

:func:`stream_events_to_app_events` subscribes to a LangGraph
``astream_events(version="v2")`` iterator and translates the native events into
the eight application-layer :data:`AppEvent` types consumed by the frontend SSE
client. The adapter owns no LLM / tool / IO coupling — it is pure event
plumbing, so the same code serves any backend that drives the agent graph.

Event mapping (see Story v0.1-3 §1):

* ``on_chat_model_stream`` → ``final_answer_delta`` (text) / ``thinking_delta``
  (reasoning, only when enabled); ``tool_call_chunks`` are *accumulated*.
* ``on_chat_model_end`` → ``thinking`` + ``final_answer`` (incl. intermediate
  text persisted before tool calls) + one ``tool_call`` per resolved call.
* ``on_tool_start`` → ``tool_call_start`` placeholder.
* ``on_tool_end`` → ``tool_result``.
* ``on_llm_error`` / ``on_tool_error`` → ``error``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

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

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

    from agent_flow_harness.adapters.app_event import AppEvent

logger = structlog.get_logger(__name__)

OnEventCallback = "Callable[[AppEvent], Awaitable[None]]"

# Native event kinds we translate; everything else is ignored.
_LLM_ERROR_KINDS = ("on_llm_error", "on_chat_model_error")
_TOOL_ERROR_KINDS = ("on_tool_error",)


async def stream_events_to_app_events(
    astream_iter: AsyncIterator[dict[str, Any]],
    on_event: Callable[[AppEvent], Awaitable[None]],
    *,
    enable_thinking: bool = False,
) -> None:
    """Translate a native ``astream_events`` stream into app-layer events.

    Args:
        astream_iter: The async iterator returned by
            ``graph.astream_events(..., version="v2")``.
        on_event: Async callback invoked once per emitted :class:`AppEvent`.
        enable_thinking: When ``False`` (default) reasoning deltas / the
            complete ``thinking`` event are suppressed even if the model
            returns reasoning content.
    """
    accumulator = _StreamingAccumulator(enable_thinking=enable_thinking)

    async for event in astream_iter:
        kind = event.get("event")
        data = event.get("data") or {}

        if kind == "on_chat_model_stream":
            chunk = data.get("chunk")
            if chunk is None:
                continue

            text = _extract_text_content(chunk)
            if text:
                await on_event(FinalAnswerDeltaEvent(content=text))

            if enable_thinking:
                thinking = _extract_thinking_content(chunk)
                if thinking:
                    await on_event(ThinkingDeltaEvent(content=thinking))

            accumulator.accumulate_tool_call_chunk(chunk)

        elif kind == "on_chat_model_end":
            output = data.get("output")
            await _emit_model_end(output, on_event, enable_thinking=enable_thinking)
            accumulator.reset()

        elif kind == "on_tool_start":
            await on_event(ToolCallStartEvent())

        elif kind == "on_tool_end":
            output = data.get("output")
            tool_name = event.get("name") or "unknown"
            await on_event(
                ToolResultEvent(
                    tool_name=tool_name,
                    content="" if output is None else str(output),
                )
            )

        elif kind in _LLM_ERROR_KINDS:
            await on_event(
                ErrorEvent(message=_error_message(data), source="llm")
            )

        elif kind in _TOOL_ERROR_KINDS:
            await on_event(
                ErrorEvent(message=_error_message(data), source="tool")
            )


# ---------------------------------------------------------------------------
# on_chat_model_end emission (shared logic)
# ---------------------------------------------------------------------------


async def _emit_model_end(
    output: Any,
    on_event: Callable[[AppEvent], Awaitable[None]],
    *,
    enable_thinking: bool,
) -> None:
    """Emit the complete thinking / final-answer / tool-call events."""
    if output is None:
        return

    # 1. Complete thinking (only when enabled).
    if enable_thinking:
        reasoning = _extract_thinking_content(output)
        if reasoning:
            await on_event(ThinkingEvent(content=reasoning))

    # 2. Final answer — emitted whenever there is content, including the
    #    "intermediate text persisted" case (content + tool_calls together).
    content = _extract_text_content(output)
    if content:
        await on_event(FinalAnswerEvent(content=content))

    # 3. One tool_call event per resolved call.
    for tc in _iter_tool_calls(output):
        await on_event(
            ToolCallEvent(
                tool_name=tc.get("name", ""),
                args=tc.get("args") or {},
                id=tc.get("id", ""),
            )
        )


# ---------------------------------------------------------------------------
# Streaming accumulator (tool_call_chunks → resolved calls)
# ---------------------------------------------------------------------------


class _StreamingAccumulator:
    """Accumulate ``tool_call_chunks`` across stream events.

    LangGraph streams a single tool call as multiple chunks (the ``id`` /
    ``name`` arrive early; ``args`` JSON is fragmented). This accumulates them
    per-call so the adapter *could* emit a fallback ``tool_call`` if a model
    backend never produces a clean ``on_chat_model_end``. In the common path
    the resolved calls come from ``output.tool_calls`` at model end; the
    accumulator is a safety net and is reset after each model end.
    """

    def __init__(self, *, enable_thinking: bool = False) -> None:
        self.enable_thinking = enable_thinking
        self._calls: dict[str, dict[str, Any]] = {}

    def accumulate_tool_call_chunk(self, chunk: Any) -> None:
        chunks = getattr(chunk, "tool_call_chunks", None)
        if not chunks:
            return
        for piece in chunks:
            index = getattr(piece, "index", 0)
            key = str(index)
            entry = self._calls.setdefault(
                key, {"name": "", "args": "", "id": ""}
            )
            name = getattr(piece, "name", None)
            if name:
                entry["name"] = name
            piece_id = getattr(piece, "id", None)
            if piece_id:
                entry["id"] = piece_id
            args = getattr(piece, "args", None)
            if args:
                entry["args"] += args

    def reset(self) -> None:
        self._calls.clear()

    def resolved_calls(self) -> list[dict[str, Any]]:
        """Return accumulated calls (best-effort; args kept as raw string)."""
        return list(self._calls.values())


# ---------------------------------------------------------------------------
# Content extraction helpers (str / list-of-blocks tolerant)
# ---------------------------------------------------------------------------


def _extract_text_content(message: Any) -> str:
    """Pull the answer text delta from a chunk / message.

    Handles plain-string ``content`` and list-of-blocks ``content``
    (``[{"type": "text", "text": "..."}, ...]``).
    """
    content = getattr(message, "content", None)
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(block.get("text") or "")
            elif isinstance(block, str):
                parts.append(block)
        return "".join(parts)
    return ""


def _extract_thinking_content(message: Any) -> str:
    """Pull reasoning text from a chunk / message.

    Looks first at ``additional_kwargs.reasoning_content`` (OpenAI-style),
    then falls back to ``reasoning_content`` attribute, then to
    ``type="thinking"`` blocks in ``content`` (Anthropic-style).
    """
    additional = getattr(message, "additional_kwargs", None) or {}
    reasoning = additional.get("reasoning_content")
    if isinstance(reasoning, str) and reasoning:
        return reasoning

    direct = getattr(message, "reasoning_content", None)
    if isinstance(direct, str) and direct:
        return direct

    content = getattr(message, "content", None)
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "thinking":
                parts.append(block.get("thinking") or "")
        joined = "".join(parts)
        if joined:
            return joined
    return ""


def _iter_tool_calls(message: Any) -> list[dict[str, Any]]:
    """Return the resolved tool_calls list from a message (empty if none)."""
    calls = getattr(message, "tool_calls", None)
    if not calls:
        return []
    return [c if isinstance(c, dict) else dict(c) for c in calls]


def _error_message(data: dict[str, Any]) -> str:
    err = data.get("error")
    if isinstance(err, BaseException):
        return str(err)
    if err is not None:
        return str(err)
    return "unknown error"


__all__ = ["OnEventCallback", "stream_events_to_app_events"]
