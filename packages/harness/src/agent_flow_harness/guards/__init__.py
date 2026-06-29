"""Guards — coarse-grained gates spliced around the react node.

Public surface:

* :class:`Guard` protocol, :class:`GuardResult` and ``Allow``/``Block``/
  ``Warn`` factories (see :mod:`agent_flow_harness.guards.base`).
* The four built-in guards — :class:`TokenBudgetGuard`,
  :class:`TimeBudgetGuard`, :class:`ToolRateLimitGuard`,
  :class:`ContentGuard`.
* :func:`make_guard_in_node` / :func:`make_guard_out_node` node factories.
* :data:`GUARD_REGISTRY` + :func:`resolve_guard` to build guards from an
  Agent document's ``guards`` config entries.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agent_flow_harness.guards.base import (
    Allow,
    Block,
    Guard,
    GuardResult,
    Warn,
)
from agent_flow_harness.guards.content import ContentGuard
from agent_flow_harness.guards.nodes import make_guard_in_node, make_guard_out_node
from agent_flow_harness.guards.time_budget import TimeBudgetGuard
from agent_flow_harness.guards.token_budget import TokenBudgetGuard
from agent_flow_harness.guards.tool_rate_limit import ToolRateLimitGuard

if TYPE_CHECKING:
    pass

# Built-in guard name → class. Applications extend by subclassing and
# adding entries (or constructing instances directly for build_agent_graph).
GUARD_REGISTRY: dict[str, type] = {
    "token_budget": TokenBudgetGuard,
    "time_budget": TimeBudgetGuard,
    "tool_rate_limit": ToolRateLimitGuard,
    "content": ContentGuard,
}


def resolve_guards(specs: list[dict[str, Any]] | None) -> list[Guard]:
    """Resolve a list of ``agent_doc["guards"]`` specs into Guard instances.

    Each spec is ``{"name": <guard-name>, "config": {...}}``. Unknown names
    raise :class:`ValueError`. Specs missing a ``config`` use the guard's
    defaults.
    """
    if not specs:
        return []
    guards: list[Guard] = []
    for spec in specs:
        if not isinstance(spec, dict):
            msg = f"guard spec must be a dict, got {type(spec).__name__}"
            raise TypeError(msg)
        name = spec.get("name")
        if not isinstance(name, str):
            msg = "guard spec missing 'name'"
            raise TypeError(msg)
        cls = GUARD_REGISTRY.get(name)
        if cls is None:
            msg = (
                f"Unknown guard: {name}. Available: {sorted(GUARD_REGISTRY)}"
            )
            raise ValueError(msg)
        config = spec.get("config") or {}
        guards.append(cls(**config))  # type: ignore[arg-type]
    return guards


def resolve_guard(spec: dict[str, Any]) -> Guard:
    """Resolve a single guard spec (convenience wrapper over resolve_guards)."""
    resolved = resolve_guards([spec])
    return resolved[0]


__all__ = [
    "Allow",
    "Block",
    "ContentGuard",
    "GUARD_REGISTRY",
    "Guard",
    "GuardResult",
    "TimeBudgetGuard",
    "TokenBudgetGuard",
    "ToolRateLimitGuard",
    "Warn",
    "make_guard_in_node",
    "make_guard_out_node",
    "resolve_guard",
    "resolve_guards",
]
