"""TraceMiddleware — span-boundary tracing (v0.1-5 stub).

Records LLM / tool span boundaries (start/end/duration) on an internal stack.
``order=200`` runs last so the span wraps the most complete information.
Provider adapters (LangSmith / OpenTelemetry) are wired in a later story via
``emit``; v0.1-5 keeps the span data and logs it.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, Callable

import structlog

if TYPE_CHECKING:
    from langchain_core.messages import BaseMessage

    from agent_flow_harness.state import AgentState

logger = structlog.get_logger("agent_flow_harness.trace")


class TraceMiddleware:
    """Track LLM / tool span boundaries.

    Args:
        provider: Trace backend label (``"noop"`` / ``"langsmith"`` /
            ``"otel"``). v0.1-5 only honours ``"noop"``; others fall back to
            structlog logging.
        emit: Optional callable receiving each completed span dict. Lets the
            host wire a real exporter without subclassing.
    """

    name = "trace"
    order = 200

    def __init__(
        self,
        provider: str = "noop",
        emit: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.provider = provider
        self.emit = emit
        self.span_stack: list[dict[str, Any]] = []

    async def before_llm(self, state: AgentState) -> AgentState:
        self.span_stack.append(
            {"type": "llm", "start": time.time(), "step": state.get("step_count", 0)}
        )
        return state

    async def after_llm(self, state: AgentState, response: BaseMessage) -> AgentState:
        self._close_span(extra={"has_tool_calls": bool(getattr(response, "tool_calls", None))})
        return state

    async def before_tool(self, state: AgentState, tool_call: dict[str, Any]) -> dict[str, Any]:
        self.span_stack.append(
            {"type": "tool", "tool_name": tool_call.get("name"), "start": time.time()}
        )
        return tool_call

    async def after_tool(
        self, state: AgentState, tool_call: dict[str, Any], result: str
    ) -> AgentState:
        self._close_span(extra={"result_length": len(result) if result else 0})
        return state

    def _close_span(self, *, extra: dict[str, Any] | None = None) -> dict[str, Any] | None:
        if not self.span_stack:
            return None
        span = self.span_stack.pop()
        span["end"] = time.time()
        span["duration"] = span["end"] - span["start"]
        if extra:
            span.update(extra)
        if self.emit is not None:
            try:
                self.emit(span)
            except Exception as exc:  # noqa: BLE001 — never break the flow
                logger.warning("trace_emit_failed", error=str(exc))
        else:
            logger.debug("trace_span", **{k: v for k, v in span.items() if k != "start"})
        return span
