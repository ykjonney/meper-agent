"""Nested-call depth guard for the Agent execution engine.

Enforces two layers of protection against runaway recursion:

* **Depth limit** — rejects execution when ``current_depth`` reaches
  ``MAX_DEPTH`` (configurable via the ``AGENT_MAX_DEPTH`` env var).
* **Cycle detection** — rejects execution when the ``call_chain``
  contains a repeated entity ID (circular call).

The module is intentionally framework-agnostic so it can be unit-tested
in isolation and reused by future Workflow / subflow executors.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from loguru import logger

from app.engine.state import AgentState


def _resolve_max_depth() -> int:
    """Read ``AGENT_MAX_DEPTH`` from the environment, defaulting to 3."""
    raw = os.environ.get("AGENT_MAX_DEPTH", "3")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return 3
    return value if value > 0 else 3


MAX_DEPTH: int = _resolve_max_depth()
"""Maximum allowed Agent→Workflow→Agent nesting depth.

Overridable at launch time via the ``AGENT_MAX_DEPTH`` environment
variable.  Defaults to ``3``.
"""


@dataclass(frozen=True)
class DepthCheckResult:
    """Outcome of a :func:`check_depth` invocation."""

    allowed: bool
    """Whether the execution may continue."""

    current_depth: int
    """Depth at the time of the check."""

    max_depth: int
    """Effective ceiling used for the check."""

    reason: str | None = None
    """Human-readable explanation when ``allowed`` is ``False``."""

    cycle: list[str] | None = None
    """When a circular call is detected, the offending sub-chain."""


def check_depth(state: AgentState) -> DepthCheckResult:
    """Verify that ``state`` is within depth and cycle constraints.

    Args:
        state: The current :class:`AgentState`.  ``call_chain`` and
            ``current_depth`` are read but not mutated.

    Returns:
        A :class:`DepthCheckResult`.  ``allowed`` is ``True`` when the
        execution may proceed.
    """
    call_chain: list[str] = state.get("call_chain") or []
    current_depth: int = state.get("current_depth", 0) or 0
    max_depth = MAX_DEPTH

    # 1. Circular-call detection — takes priority because a cycle
    #    indicates a logic bug regardless of depth.
    cycle = detect_cycle(call_chain)
    if cycle is not None:
        reason = (
            "Circular call detected: " + format_call_chain(cycle)
        )
        logger.warning(
            "circular_call_detected",
            agent_id=state.get("agent_id"),
            current_depth=current_depth,
            call_chain=call_chain,
            cycle=cycle,
            reason=reason,
        )
        return DepthCheckResult(
            allowed=False,
            current_depth=current_depth,
            max_depth=max_depth,
            reason=reason,
            cycle=cycle,
        )

    # 2. Depth-ceiling check.
    if current_depth >= max_depth:
        reason = (
            f"Depth limit exceeded: current depth {current_depth} "
            f">= max depth {max_depth}. Call chain: "
            + format_call_chain(call_chain)
        )
        logger.warning(
            "depth_limit_exceeded",
            agent_id=state.get("agent_id"),
            current_depth=current_depth,
            max_depth=max_depth,
            call_chain=call_chain,
            reason=reason,
        )
        return DepthCheckResult(
            allowed=False,
            current_depth=current_depth,
            max_depth=max_depth,
            reason=reason,
        )

    return DepthCheckResult(
        allowed=True,
        current_depth=current_depth,
        max_depth=max_depth,
    )


def detect_cycle(call_chain: list[str]) -> list[str] | None:
    """Return the cyclic sub-chain if ``call_chain`` repeats an entity.

    The detection walks the chain left-to-right and returns the slice
    from the first occurrence of the repeated entity up to (and
    including) its second occurrence.  Returns ``None`` when no cycle
    exists or the chain is shorter than two entries.
    """
    if len(call_chain) < 2:
        return None

    seen: dict[str, int] = {}
    for idx, entity_id in enumerate(call_chain):
        if entity_id in seen:
            start = seen[entity_id]
            return call_chain[start : idx + 1]
        seen[entity_id] = idx
    return None


def format_call_chain(call_chain: list[str]) -> str:
    """Render a call chain as a human-readable arrow-joined string.

    Example::

        >>> format_call_chain(["agent_a", "task_x", "agent_a"])
        'agent_a → task_x → agent_a'
    """
    if not call_chain:
        return "(empty)"
    return " → ".join(call_chain)
