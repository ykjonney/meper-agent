"""PromptInjectionMiddleware — inject system reminders before each LLM call.

Unlike the SlotRenderer (v0.1-6), which builds the system prompt once at agent
start, this middleware appends dynamic reminders before every LLM call.
``order=50`` runs first so downstream middlewares (audit / trace) observe the
final messages.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from langchain_core.messages import SystemMessage

if TYPE_CHECKING:
    from langchain_core.messages import BaseMessage

    from agent_flow_harness.state import AgentState


class PromptInjectionMiddleware:
    """Append ``[系统提醒]`` SystemMessages before each LLM call."""

    name = "prompt_injection"
    order = 50

    def __init__(self, reminders: list[str] | None = None) -> None:
        self.reminders: list[str] = list(reminders or [])

    async def before_llm(self, state: AgentState) -> AgentState:
        if not self.reminders:
            return state
        messages: list = list(state.get("messages", []) or [])
        reminder_text = "\n".join(f"[系统提醒] {r}" for r in self.reminders)
        messages.append(SystemMessage(content=reminder_text))
        return {**state, "messages": messages}

    async def after_llm(self, state: AgentState, response: BaseMessage) -> AgentState:
        return state

    async def before_tool(self, state: AgentState, tool_call: dict[str, Any]) -> dict[str, Any]:
        return tool_call

    async def after_tool(
        self, state: AgentState, tool_call: dict[str, Any], result: str
    ) -> AgentState:
        return state
