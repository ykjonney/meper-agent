"""LangGraph Agent runtime state definition.

Replaces the placeholder ``dict[str, Any]`` with a proper ``TypedDict``
that the StateGraph builder (Story 3.1) and all three executors
(Story 3.2—3.4) depend on.
"""
from __future__ import annotations

from typing import Annotated, Any, TypedDict

from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    """Runtime state for an Agent execution session.

    Passed through every node of the StateGraph.  LangGraph uses
    ``add_messages`` reducer to accumulate the message list across nodes.
    """

    messages: Annotated[list, add_messages]
    """Conversation / reasoning messages accumulated during execution."""

    agent_id: str
    """The Agent document ID that owns this execution."""

    execution_path: str
    """Selected execution path: ``"direct"`` / ``"react"`` / ``"planner"`` /
    ``"workflow"``.  Populated by the evaluator node (first step).
    """

    request_id: str
    """Unique request ID for end-to-end traceability across logs."""

    tool_results: dict[str, Any]
    """Cache of tool-call results keyed by tool name or call ID."""

    step_count: int
    """Number of reasoning / acting steps taken so far (0-based)."""

    error: str | None
    """Non-None when a terminal error has occurred inside the graph."""

    call_chain: list[str]
    """Ordered list of entity IDs representing the nested call chain.

    Initial entry is ``[agent_id]``.  When an Agent triggers a Workflow
    that contains another Agent node, the downstream execution appends
    the new entity ID, e.g. ``["agent_a", "task_x", "agent_b"]``.
    Used by :mod:`app.engine.agent.depth_guard` to enforce depth limits
    and detect circular calls.
    """

    current_depth: int
    """Current nesting depth (0-based).

    Equals ``len(call_chain) - 1`` in normal conditions but is tracked
    explicitly so depth can be incremented without mutating the chain
    (e.g. for Workflow-level depth that does not add a chain entry).
    """

    session_id: str
    """Session ID for workspace isolation.  Set by the API layer."""

    user_id: str
    """User ID for workspace isolation.  Set by the API layer."""
