"""LangGraph Agent runtime state definition.

Mirror of the backend ``AgentState`` TypedDict. The harness does not
own the canonical state schema (it lives in the backend today and is
expected to graduate into the harness in a later Story); for v0.1 we
ship a parallel copy so downstream code can already import the harness
state type.
"""

from __future__ import annotations

from typing import Annotated, Any, TypedDict

from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    """Runtime state for an Agent execution session."""

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
    """Ordered list of entity IDs representing the nested call chain."""

    current_depth: int
    """Current nesting depth (0-based)."""

    session_id: str
    """Session ID for workspace isolation.  Set by the API layer."""

    user_id: str
    """User ID for workspace isolation.  Set by the API layer."""

    # -- v0.1-4 Guard fields (optional; populated by guard nodes) -------------

    warnings: list[str]
    """Non-fatal guard warnings accumulated during execution (v0.1-4)."""

    started_at: float
    """Wall-clock start timestamp (seconds) for :class:`TimeBudgetGuard`."""

    total_tokens: int
    """Cumulative token spend for :class:`TokenBudgetGuard`."""

    tool_call_count: dict[str, int]
    """Per-tool call counts for :class:`ToolRateLimitGuard`."""

    tool_calls_this_step: list[dict]
    """Tool calls made in the current step, inspected by guards."""
