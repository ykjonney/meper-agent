"""ToolRateLimitGuard — per-tool call-count and repeated-args limits."""

from __future__ import annotations

import json
from collections import defaultdict
from typing import TYPE_CHECKING, Any

from agent_flow_harness.guards.base import Allow, Block, GuardResult

if TYPE_CHECKING:
    from agent_flow_harness.state import AgentState


class ToolRateLimitGuard:
    """Block when a tool is called too often, or with the same args too often.

    ``check_in`` inspects ``state["tool_call_count"]`` (per-tool totals);
    ``check_out`` inspects ``output["tool_calls_this_step"]`` for the same-args
    repetition limit. Either condition raises a :class:`Block`.
    """

    name = "tool_rate_limit"

    def __init__(
        self,
        max_calls_per_tool: int = 30,
        max_repeat_args: int = 3,
    ) -> None:
        self.max_calls_per_tool = max_calls_per_tool
        self.max_repeat_args = max_repeat_args

    async def check_in(self, state: AgentState) -> GuardResult:
        tool_call_count: dict[str, int] = dict(state.get("tool_call_count") or {})
        for tool_name, count in tool_call_count.items():
            if count >= self.max_calls_per_tool:
                return Block(
                    f"Tool '{tool_name}' called {count} times, "
                    f"limit {self.max_calls_per_tool}"
                )
        return Allow()

    async def check_out(self, state: AgentState, output: dict) -> GuardResult:
        tool_calls: list[dict[str, Any]] = list(output.get("tool_calls_this_step") or [])
        if not tool_calls:
            return Allow()
        args_counter: dict[tuple[str, str], int] = defaultdict(int)
        for tc in tool_calls:
            key = (
                tc.get("name", ""),
                json.dumps(tc.get("args") or {}, sort_keys=True),
            )
            args_counter[key] += 1
        for (name, _args), count in args_counter.items():
            if count >= self.max_repeat_args:
                return Block(
                    f"Tool '{name}' called with same args {count} times"
                )
        return Allow()
