"""TokenBudgetGuard — cumulative token spend ceiling."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agent_flow_harness.guards.base import Allow, Block, GuardResult, Warn

if TYPE_CHECKING:
    from agent_flow_harness.state import AgentState


class TokenBudgetGuard:
    """Block when cumulative token spend exceeds a budget; warn near it.

    Reads ``state["total_tokens"]`` (cumulative) in ``check_in``; ``check_out``
    adds the step's ``output["step_tokens"]`` delta and blocks if the new
    total exceeds the budget.
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

    async def check_out(self, state: AgentState, output: dict[str, Any]) -> GuardResult:
        delta = int(output.get("step_tokens", 0) or 0)
        new_total = int(state.get("total_tokens", 0) or 0) + delta
        if new_total > self.max_total_tokens:
            return Block(f"Token budget exceeded after step: {new_total}")
        return Allow()
