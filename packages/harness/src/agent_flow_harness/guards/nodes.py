"""Guard → LangGraph node adapters.

:func:`make_guard_in_node` / :func:`make_guard_out_node` wrap a
:class:`~agent_flow_harness.guards.base.Guard` as async LangGraph node
functions the builder splices around the react node. A ``Block`` result sets
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

    async def guard_in_node(state: AgentState, config: RunnableConfig | None = None) -> dict[str, Any]:
        _ = config
        result = await guard.check_in(state)
        return _apply_result(state, guard, result, direction="in")

    guard_in_node.__name__ = f"guard_in_{guard.name}"
    return guard_in_node


def make_guard_out_node(guard: Guard) -> Callable[..., Any]:
    """Build the post-react guard node for *guard*."""

    async def guard_out_node(state: AgentState, config: RunnableConfig | None = None) -> dict[str, Any]:
        _ = config
        # By the time guard_out runs, the react output is merged into state,
        # so ``output`` is the state itself.
        result = await guard.check_out(state, dict(state))
        return _apply_result(state, guard, result, direction="out")

    guard_out_node.__name__ = f"guard_out_{guard.name}"
    return guard_out_node


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
    # warn
    warnings = list(state.get("warnings") or [])
    warnings.append(f"{prefix} {result.reason}".strip())
    return {"warnings": warnings}


__all__ = ["make_guard_in_node", "make_guard_out_node"]
