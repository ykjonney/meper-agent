"""Middleware protocol — fine-grained hooks around LLM/Tool calls.

Unlike a Guard (a coarse gate that *blocks* the whole react node), a
Middleware *observes or rewrites* individual LLM / tool calls without ever
blocking the flow. Middlewares are chained in ascending ``order`` and run
inside the react node via :class:`~agent_flow_harness.middleware.chain.MiddlewareChain`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from langchain_core.messages import BaseMessage

    from agent_flow_harness.state import AgentState


@runtime_checkable
class Middleware(Protocol):
    """Fine-grained hook executed around each LLM / tool call.

    Attributes:
        name: Stable identifier (referenced from ``agent_doc["middleware"]``).
        order: Execution priority; lower runs first. Defaults to ``100``.
    """

    name: str
    order: int

    async def before_llm(self, state: AgentState) -> AgentState:
        """Run before an LLM call; may rewrite and return the new state."""
        ...

    async def after_llm(self, state: AgentState, response: BaseMessage) -> AgentState:
        """Run after an LLM call; may inspect ``response`` and rewrite state."""
        ...

    async def before_tool(self, state: AgentState, tool_call: dict) -> dict:
        """Run before a tool call; may rewrite and return the tool_call."""
        ...

    async def after_tool(
        self, state: AgentState, tool_call: dict, result: str
    ) -> AgentState:
        """Run after a tool call; may inspect ``result`` and rewrite state."""
        ...


__all__ = ["Middleware"]
