"""Guards — coarse-grained gates spliced before the react node.

Public surface:

* :class:`Guard` protocol, :class:`GuardResult` and ``Allow``/``Block``/
  ``Warn`` factories (see :mod:`agent_flow_harness.guards.base`).
* :class:`TokenBudgetGuard`.
* :func:`make_guard_in_node` node factory.
* :data:`GUARD_REGISTRY` + :func:`resolve_guards` to build guards from an
  Agent document's ``guards`` config entries.
"""

from __future__ import annotations

from typing import Any

from agent_flow_harness.guards.base import (
    Allow,
    Block,
    Guard,
    GuardResult,
    Warn,
)
from agent_flow_harness.guards.nodes import make_guard_in_node
from agent_flow_harness.guards.token_budget import TokenBudgetGuard

GUARD_REGISTRY: dict[str, type] = {
    "token_budget": TokenBudgetGuard,
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
        guards.append(cls(**config))
    return guards

__all__ = [
    "Allow",
    "Block",
    "GUARD_REGISTRY",
    "Guard",
    "GuardResult",
    "TokenBudgetGuard",
    "Warn",
    "make_guard_in_node",
    "resolve_guards",
]
