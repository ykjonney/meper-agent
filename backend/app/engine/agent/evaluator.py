"""Task evaluator — input analysis and initial-state builder.

The evaluator prepares the initial AgentState and sets the execution
path to ``"react"`` (the single execution mode).  The LLM inside the
REACT loop autonomously decides whether to answer directly, call
tools, or create a Task via workflow tools.
"""
from __future__ import annotations

import uuid

from loguru import logger

from app.engine.state import AgentState


def evaluate_input(agent: dict, user_input: str, request_id: str | None = None) -> AgentState:
    """Analyse ``user_input`` and produce the initial ``AgentState``.

    The execution path is always ``"react"`` — the LLM in the REACT
    loop decides how to handle the input (direct answer, tool calling,
    or workflow Task creation).

    Args:
        agent: The Agent MongoDB document (includes ``llm_config``,
            ``tool_ids``, ``workflow_ids``, ``system_prompt``).
        user_input: The raw text the user sent.
        request_id: Unique trace ID for this execution.
            Auto-generated if not provided.

    Returns:
        An ``AgentState`` dictionary ready to be passed into the
        StateGraph.
    """
    rid = request_id or str(uuid.uuid4())

    logger.bind(
        request_id=rid,
        agent_id=agent.get("_id"),
    ).info("execution_evaluated", input_preview=user_input[:80])

    return {
        "messages": [],
        "agent_id": agent.get("_id", ""),
        "execution_path": "react",
        "request_id": rid,
        "tool_results": {},
        "step_count": 0,
        "error": None,
        "call_chain": [agent.get("_id", "")],
        "current_depth": 0,
    }
