"""Middleware — protocol, chain executor and built-in middlewares.

Public surface:

* :class:`Middleware` protocol + :class:`MiddlewareChain` executor.
* :class:`UsageMiddleware` — token/time accounting.
* :data:`MIDDLEWARE_REGISTRY` + :func:`resolve_middleware` to build
  middlewares from an Agent document's ``middleware`` config entries.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agent_flow_harness.middleware.base import Middleware
from agent_flow_harness.middleware.builtin import UsageMiddleware
from agent_flow_harness.middleware.chain import MiddlewareChain

if TYPE_CHECKING:
    pass

MIDDLEWARE_REGISTRY: dict[str, type] = {
    "usage": UsageMiddleware,
}

def resolve_middleware(specs: list[dict[str, Any]] | None) -> list[Middleware]:
    """Resolve ``agent_doc["middleware"]`` specs into Middleware instances.

    Each spec is ``{"name": <mw-name>, "config": {...}}``. Unknown names raise
    :class:`ValueError`.
    """
    if not specs:
        return []
    middlewares: list[Middleware] = []
    for spec in specs:
        if not isinstance(spec, dict):
            msg = f"middleware spec must be a dict, got {type(spec).__name__}"
            raise TypeError(msg)
        name = spec.get("name")
        if not isinstance(name, str):
            msg = "middleware spec missing 'name'"
            raise TypeError(msg)
        cls = MIDDLEWARE_REGISTRY.get(name)
        if cls is None:
            msg = (
                f"Unknown middleware: {name}. Available: {sorted(MIDDLEWARE_REGISTRY)}"
            )
            raise ValueError(msg)
        config = spec.get("config") or {}
        middlewares.append(cls(**config))
    return middlewares

__all__ = [
    "MIDDLEWARE_REGISTRY",
    "Middleware",
    "MiddlewareChain",
    "UsageMiddleware",
    "resolve_middleware",
]
