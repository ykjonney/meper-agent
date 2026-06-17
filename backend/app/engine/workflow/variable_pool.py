"""Variable pool — per-Task runtime execution context.

Each Task has an isolated variable pool that stores node outputs.
Variables are keyed by node ID and can be accessed via ``{{node_id.field}}`` expressions.

Structure::

    {
        "input": { ... },           # Task input parameters
        "node_abc123": { ... },     # Output of node "abc123"
        "node_def456": { ... },     # Output of node "def456"
    }
"""
from __future__ import annotations

from typing import Any

# Sentinel for distinguishing "path not found" from "value is None"
_MISSING = object()


class VariablePool:
    """Per-Task variable pool — thread-safe, dict-backed context.

    Usage::

        pool = VariablePool(task_input={"user": "Alice"})
        pool.set("node_1", {"result": "ok", "data": [1, 2, 3]})
        value = pool.get("node_1.result")  # "ok"
        exists = pool.has("node_1")        # True
    """

    def __init__(self, initial: dict[str, Any] | None = None) -> None:
        self._store: dict[str, Any] = dict(initial or {})

    # ── Read ──

    def get(self, path: str, default: Any = None) -> Any:
        """Get a value by dotted path (e.g. ``node_1.result.status``).

        Returns *default* if the path does not exist.
        Correctly distinguishes between a stored ``None`` and a missing path.
        """
        if "." not in path:
            result = self._store.get(path, _MISSING)
            return default if result is _MISSING else result

        parts = path.split(".")
        current: Any = self._store
        for part in parts:
            if isinstance(current, dict):
                current = current.get(part, _MISSING)
                if current is _MISSING:
                    return default
            else:
                return default
        return current

    def get_all(self) -> dict[str, Any]:
        """Return the entire variable pool (read-only snapshot)."""
        return dict(self._store)

    def has(self, node_id: str) -> bool:
        """Check if a node ID exists in the pool."""
        return node_id in self._store

    # ── Write ──

    def set(self, node_id: str, output: dict[str, Any]) -> None:
        """Store the output of a node."""
        self._store[node_id] = output

    def merge(self, variables: dict[str, Any]) -> None:
        """Merge a dict of variables into the pool (top-level keys)."""
        self._store.update(variables)

    def snapshot(self) -> dict[str, Any]:
        """Return a deep-ish copy for persistence / snapshots."""
        import copy
        return copy.deepcopy(self._store)
