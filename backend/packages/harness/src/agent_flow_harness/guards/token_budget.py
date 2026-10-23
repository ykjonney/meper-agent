"""TokenBudgetGuard — cumulative token spend ceiling."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agent_flow_harness.guards.base import Allow, Block, GuardResult, Warn

if TYPE_CHECKING:
    from agent_flow_harness.state import AgentState


class TokenBudgetGuard:
    """Block when cumulative token spend exceeds a budget; warn near it.

    Reads ``state["total_tokens"]`` (cumulative) in ``check_in``.
    """

    name = "token_budget"

    def __init__(self, max_total_tokens: int) -> None:
        self.max_total_tokens = max_total_tokens

    async def check_in(self, state: AgentState) -> GuardResult:
        current = int(state.get("total_tokens", 0) or 0)
        if current >= self.max_total_tokens:
            return Block(
                f"Token budget exceeded: {current} >= {self.max_total_tokens}"
            )
        if current >= self.max_total_tokens * 0.9:
            return Warn(f"Token budget 90% used: {current}/{self.max_total_tokens}")
        return Allow()
