"""ContentGuard — deny-pattern / PII checks on tool I/O."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

from agent_flow_harness.guards.base import Allow, Block, GuardResult

if TYPE_CHECKING:
    from agent_flow_harness.state import AgentState


class ContentGuard:
    """Block when deny-patterns match the user message or tool args.

    ``check_in`` scans the last user message text; ``check_out`` scans each
    tool call's ``args`` JSON. PII redaction patterns are compiled when
    ``redact_pii`` is set (kept available for downstream middleware; this
    guard only blocks on deny-patterns).
    """

    name = "content"

    def __init__(
        self,
        deny_patterns: list[str] | None = None,
        redact_pii: bool = False,
    ) -> None:
        self.deny_patterns = [re.compile(p) for p in (deny_patterns or [])]
        self.redact_pii = redact_pii
        self.pii_patterns: list[re.Pattern[str]] = (
            [
                re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),  # SSN
                re.compile(r"\b[\w.]+@[\w.]+\b"),  # email
            ]
            if redact_pii
            else []
        )

    async def check_in(self, state: AgentState) -> GuardResult:
        messages = state.get("messages") or []
        if not messages:
            return Allow()
        last = messages[-1]
        text = getattr(last, "content", "") or ""
        if isinstance(text, list):
            # content blocks form — concatenate text blocks
            text = "".join(
                b.get("text", "") for b in text if isinstance(b, dict)
            )
        for pattern in self.deny_patterns:
            if pattern.search(text):
                return Block(
                    f"Content denied by pattern: {pattern.pattern}"
                )
        return Allow()

    async def check_out(self, state: AgentState, output: dict[str, Any]) -> GuardResult:
        tool_calls: list[dict[str, Any]] = list(output.get("tool_calls_this_step") or [])
        for tc in tool_calls:
            args_text = json.dumps(tc.get("args") or {})
            for pattern in self.deny_patterns:
                if pattern.search(args_text):
                    return Block(
                        f"Tool args denied by pattern: {pattern.pattern}"
                    )
        return Allow()
