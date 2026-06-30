"""AuditMiddleware — structured audit log for every LLM / tool call."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from langchain_core.messages import BaseMessage

    from agent_flow_harness.state import AgentState

logger = structlog.get_logger("agent_flow_harness.audit")


class AuditMiddleware:
    """Emit a structured log line for each LLM / tool call boundary.

    ``order=100`` puts audit after prompt-injection (50) so it logs the final
    messages, and before trace (200).
    """

    name = "audit"
    order = 100

    def __init__(self, log_level: str = "info") -> None:
        level = log_level.lower()
        # structlog loggers expose debug/info/warning/error/etc. methods.
        self._log = getattr(logger, level, logger.info)

    async def before_llm(self, state: AgentState) -> AgentState:
        self._log(
            "llm_call_start",
            agent_id=state.get("agent_id"),
            session_id=state.get("session_id"),
            step_count=state.get("step_count", 0),
            message_count=len(state.get("messages", []) or []),
        )
        return state

    async def after_llm(self, state: AgentState, response: BaseMessage) -> AgentState:
        self._log(
            "llm_call_end",
            agent_id=state.get("agent_id"),
            session_id=state.get("session_id"),
            step_count=state.get("step_count", 0),
            has_tool_calls=bool(getattr(response, "tool_calls", None)),
            content_length=len(response.content) if getattr(response, "content", None) else 0,
        )
        return state

    async def before_tool(self, state: AgentState, tool_call: dict[str, Any]) -> dict[str, Any]:
        self._log(
            "tool_call_start",
            agent_id=state.get("agent_id"),
            tool_name=tool_call.get("name"),
            tool_id=tool_call.get("id"),
        )
        return tool_call

    async def after_tool(
        self, state: AgentState, tool_call: dict[str, Any], result: str
    ) -> AgentState:
        self._log(
            "tool_call_end",
            agent_id=state.get("agent_id"),
            tool_name=tool_call.get("name"),
            tool_id=tool_call.get("id"),
            result_length=len(result) if result else 0,
        )
        return state
