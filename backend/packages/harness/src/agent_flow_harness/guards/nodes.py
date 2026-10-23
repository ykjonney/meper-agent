"""Guard → LangGraph node adapters.

:func:`make_guard_in_node` wraps a
:class:`~agent_flow_harness.guards.base.Guard` as an async LangGraph node
function the builder splices before the compress node. A ``Block`` result sets
``state["error"]`` (LangGraph then terminates naturally); a ``Warn`` appends
to ``state["warnings"]`` without blocking.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

from agent_flow_harness.guards.base import Guard

if TYPE_CHECKING:
    from langchain_core.runnables import RunnableConfig

    from agent_flow_harness.guards.base import GuardResult

    from agent_flow_harness.state import AgentState

def make_guard_in_node(guard: Guard) -> Callable[..., Any]:
    """Build the pre-react guard node for *guard*."""

    async def guard_in_node(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
        _ = config
        result = await guard.check_in(state)
        return _apply_result(state, guard, result, direction="in")

    guard_in_node.__name__ = f"guard_in_{guard.name}"
    return guard_in_node

def _apply_result(
    state: AgentState,
    guard: Guard,
    result: GuardResult,
    *,
    direction: str,
) -> dict[str, Any]:
    """Translate a GuardResult into a state patch.

    ``allow`` returns an empty patch (state flows on unchanged). ``block`` sets
    ``error``; ``warn`` appends to ``warnings``.
    """
    if result.decision == "allow":
        return {}

    prefix = f"[{guard.name}:{direction}]"
    if result.decision == "block":
        return {"error": f"{prefix} {result.reason}".strip()}
    warnings = list(state.get("warnings") or [])
    warnings.append(f"{prefix} {result.reason}".strip())
    return {"warnings": warnings}

__all__ = ["make_guard_in_node"]
