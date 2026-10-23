"""Guard protocol and result type.

A :class:`Guard` is a coarse-grained gate spliced before the react node as
a LangGraph node (``[guard_in] -> react -> ...``). It decides whether a step
may run (``check_in``), returning a :class:`GuardResult`.

Guard vs Middleware: a Guard *blocks* the flow; a Middleware
*observes/rewrites* without blocking.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Protocol, runtime_checkable

from pydantic import BaseModel

if TYPE_CHECKING:
    from agent_flow_harness.state import AgentState


class GuardResult(BaseModel):
    """Outcome of a guard check.

    Attributes:
        decision: ``allow`` (proceed), ``block`` (short-circuit, set
            ``state["error"]``) or ``warn`` (append to ``state["warnings"]``
            but proceed).
        reason: Human-readable explanation; empty for a plain allow.
    """

    model_config = {"extra": "forbid"}

    decision: Literal["allow", "block", "warn"]
    reason: str = ""


# Convenience factories — keep call sites readable.
def Allow() -> GuardResult:
    return GuardResult(decision="allow")


def Block(reason: str) -> GuardResult:
    return GuardResult(decision="block", reason=reason)


def Warn(reason: str) -> GuardResult:
    return GuardResult(decision="warn", reason=reason)


@runtime_checkable
class Guard(Protocol):
    """Coarse-grained gate executed before the react node.

    Implementations expose a stable ``name`` (used as the graph node suffix)
    and an async ``check_in`` method. Built-in guards live in this package;
    applications may subclass to extend them.
    """

    name: str

    async def check_in(self, state: AgentState) -> GuardResult:
        """Decide whether the react node may run (pre-check)."""
        ...


__all__ = ["Allow", "Block", "Guard", "GuardResult", "Warn"]
