"""Direct execution mode — single LLM call, no tool calling.

The direct executor is the simplest path: it passes the conversation
messages to the LLM once, collects the response, and returns immediately.
No tool calling, no reasoning loop — ideal for simple Q&A and quick
lookups where the Agent doesn't need to interact with external systems.
"""
from __future__ import annotations

from langchain_core.language_models.chat_models import BaseChatModel
from loguru import logger

from app.engine.state import AgentState


async def run(state: AgentState, llm: BaseChatModel) -> dict:
    """Execute a single LLM call and return the response.

    Args:
        state: Current AgentState with messages to send to the LLM.
        llm: Configured LangChain chat model instance.

    Returns:
        Updated state with the AI response appended to messages and
        step_count incremented.
    """
    messages = state.get("messages", [])
    if not messages:
        logger.warning(
            "direct_executor_empty_state",
            agent_id=state.get("agent_id"),
        )
        return _result(state, "No input provided.")

    response = await llm.ainvoke(messages)
    content = str(response.content) if hasattr(response, "content") else str(response)

    logger.bind(
        agent_id=state.get("agent_id"),
        request_id=state.get("request_id"),
    ).info("direct_executor_completed")

    return _result(state, content)


def _result(state: AgentState, content: str) -> dict:
    """Build the output dict with the AI response appended."""
    new_msg = {"role": "assistant", "content": content}
    return {
        **state,
        "messages": [new_msg],
        "step_count": state.get("step_count", 0) + 1,
    }
