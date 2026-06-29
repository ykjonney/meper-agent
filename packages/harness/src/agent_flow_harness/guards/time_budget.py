"""TimeBudgetGuard — wall-clock execution ceiling."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from agent_flow_harness.guards.base import Allow, Block, GuardResult, Warn

if TYPE_CHECKING:
    from agent_flow_harness.state import AgentState


class TimeBudgetGuard:
    """Block when wall-clock elapsed time exceeds the budget; warn near it.

    Elapsed time is measured against ``state["started_at"]`` (seconds since
    epoch); ``check_in`` returns ``Allow`` and is a no-op because timing is
    only meaningful before the react node runs.
    """

    name = "time_budget"

    def __init__(self, max_wall_seconds: int) -> None:
        self.max_wall_seconds = max_wall_seconds

    async def check_in(self, state: AgentState) -> GuardResult:
        started_at = float(state.get("started_at", 0) or time.time())
        if started_at == 0:
            started_at = time.time()
        elapsed = time.time() - started_at
        if elapsed >= self.max_wall_seconds:
            return Block(
                f"Time budget exceeded: {elapsed:.1f}s >= {self.max_wall_seconds}s"
            )
        if elapsed >= self.max_wall_seconds * 0.9:
            return Warn(
                f"Time budget 90% used: {elapsed:.1f}s/{self.max_wall_seconds}s"
            )
        return Allow()

    async def check_out(self, state: AgentState, output: dict) -> GuardResult:
        return Allow()
