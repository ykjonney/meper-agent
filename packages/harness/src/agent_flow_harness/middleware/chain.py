"""MiddlewareChain — runs middlewares in order with exception isolation.

Core rules:

1. Middlewares run in ascending ``order`` (stable for equal orders).
2. A middleware that raises is logged and **skipped** — the chain never blocks
   (the opposite of a Guard's ``block``). The previous value flows on.
3. Middlewares share state by reference across the chain.

An empty chain (``MiddlewareChain([])``) is a transparent pass-through, so
``react_node`` behaves identically when no middleware is configured.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

from agent_flow_harness.middleware.base import Middleware

if TYPE_CHECKING:
    from langchain_core.messages import BaseMessage

    from agent_flow_harness.state import AgentState

logger = structlog.get_logger(__name__)


class MiddlewareChain:
    """Ordered, fault-isolated middleware executor."""

    def __init__(self, middlewares: list[Middleware] | None = None) -> None:
        # ``sorted`` is stable, so equal orders preserve registration order.
        self._middlewares: list[Middleware] = sorted(
            middlewares or [], key=lambda m: getattr(m, "order", 100)
        )

    @property
    def middlewares(self) -> list[Middleware]:
        return list(self._middlewares)

    async def run_before_llm(self, state: AgentState) -> AgentState:
        for mw in self._middlewares:
            state = await self._call(mw, "before_llm", state, fallback=state)
        return state

    async def run_after_llm(
        self, state: AgentState, response: BaseMessage
    ) -> AgentState:
        for mw in self._middlewares:
            state = await self._call(
                mw, "after_llm", state, response, fallback=state
            )
        return state

    async def run_before_tool(self, state: AgentState, tool_call: dict) -> dict:
        for mw in self._middlewares:
            tool_call = await self._call(
                mw, "before_tool", state, tool_call, fallback=tool_call
            )
        return tool_call

    async def run_after_tool(
        self, state: AgentState, tool_call: dict, result: str
    ) -> AgentState:
        for mw in self._middlewares:
            state = await self._call(
                mw, "after_tool", state, tool_call, result, fallback=state
            )
        return state

    async def _call(
        self,
        mw: Middleware,
        method_name: str,
        *args: Any,
        fallback: Any,
    ) -> Any:
        """Invoke a middleware method, returning ``fallback`` on any error."""
        try:
            method = getattr(mw, method_name)
            return await method(*args)
        except Exception as exc:  # noqa: BLE001 — isolate, never propagate
            logger.warning(
                "middleware_error",
                middleware=getattr(mw, "name", "<unknown>"),
                method=method_name,
                error=str(exc),
            )
            return fallback


__all__ = ["MiddlewareChain"]
