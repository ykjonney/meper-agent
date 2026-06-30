"""Application-layer event schemas for the streaming adapter.

Eight Pydantic event models that the frontend SSE client consumes. These
mirror the legacy ``react_executor.run_streaming`` event dict shapes so the
chat panel needs zero changes when the harness adapter takes over.

The union :data:`AppEvent` is the discriminated sum type: every model carries
a literal ``type`` field, so ``model_dump()`` yields the exact dict the legacy
code emitted (``{"type": "...", ...}``).
"""

from __future__ import annotations

from typing import Any, Literal, Union

from pydantic import BaseModel


class _Base(BaseModel):
    """Common base — subclasses pin their own ``type`` literal."""

    model_config = {"extra": "forbid"}


class ThinkingDeltaEvent(_Base):
    """Incremental reasoning token (only emitted when thinking is enabled)."""

    type: Literal["thinking_delta"] = "thinking_delta"
    content: str


class ThinkingEvent(_Base):
    """Complete reasoning text emitted once at ``on_chat_model_end``."""

    type: Literal["thinking"] = "thinking"
    content: str


class FinalAnswerDeltaEvent(_Base):
    """Incremental answer token streamed from the LLM."""

    type: Literal["final_answer_delta"] = "final_answer_delta"
    content: str


class FinalAnswerEvent(_Base):
    """Complete answer text (or persisted intermediate text before tool calls)."""

    type: Literal["final_answer"] = "final_answer"
    content: str


class ToolCallStartEvent(_Base):
    """Placeholder signalling a tool call is about to start (no name/args)."""

    type: Literal["tool_call_start"] = "tool_call_start"


class ToolCallEvent(_Base):
    """A fully-resolved tool call (name/args/id), emitted at model end."""

    type: Literal["tool_call"] = "tool_call"
    tool_name: str
    args: dict[str, Any]
    id: str


class ToolResultEvent(_Base):
    """The result content of a completed tool invocation."""

    type: Literal["tool_result"] = "tool_result"
    tool_name: str
    content: str


class ErrorEvent(_Base):
    """A terminal error from the LLM, a tool, or the graph itself."""

    type: Literal["error"] = "error"
    message: str
    source: Literal["llm", "tool", "graph"]


AppEvent = Union[
    ThinkingDeltaEvent,
    ThinkingEvent,
    FinalAnswerDeltaEvent,
    FinalAnswerEvent,
    ToolCallStartEvent,
    ToolCallEvent,
    ToolResultEvent,
    ErrorEvent,
]
"""Discriminated union of all application-layer events."""


__all__ = [
    "AppEvent",
    "ErrorEvent",
    "FinalAnswerDeltaEvent",
    "FinalAnswerEvent",
    "ThinkingDeltaEvent",
    "ThinkingEvent",
    "ToolCallEvent",
    "ToolCallStartEvent",
    "ToolResultEvent",
]
