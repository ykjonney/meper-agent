"""VariablePool unit tests — get, set, has, merge, snapshot, None distinction."""
from __future__ import annotations

import pytest

from app.engine.workflow.variable_pool import VariablePool


class TestVariablePool:
    """Tests for VariablePool get/set operations."""

    def test_set_get_simple(self) -> None:
        pool = VariablePool()
        pool.set("node_1", {"result": "ok"})
        assert pool.get("node_1") == {"result": "ok"}

    def test_set_get_dotted_path(self) -> None:
        pool = VariablePool()
        pool.set("node_1", {"result": {"status": "ok"}})
        assert pool.get("node_1.result.status") == "ok"

    def test_get_missing_path_returns_default(self) -> None:
        pool = VariablePool()
        assert pool.get("nonexistent") is None

    def test_get_missing_dotted_path_returns_default(self) -> None:
        pool = VariablePool()
        pool.set("node_1", {"result": "ok"})
        assert pool.get("node_1.result.missing") is None

    def test_get_explicit_none_vs_missing(self) -> None:
        """Stored None should be returned as None, not as default."""
        pool = VariablePool()
        # Use merge to set a key with None value (set only accepts dict)
        pool.merge({"node_1": None})
        # Value is explicitly None — should return None
        assert pool.get("node_1") is None
        # With custom default, still returns the stored None
        assert pool.get("node_1", default="MISSING") is None
        # Path doesn't exist — should return default
        assert pool.get("node_1.nonexistent", default="MISSING") == "MISSING"

    def test_get_simple_none_vs_missing(self) -> None:
        """Top-level None vs missing key."""
        pool = VariablePool()
        pool.merge({"key_a": None})
        assert pool.get("key_a") is None
        assert pool.get("key_a", default="MISSING") is None
        assert pool.get("key_b", default="MISSING") == "MISSING"

    def test_get_custom_default(self) -> None:
        pool = VariablePool()
        assert pool.get("missing", default=0) == 0
        assert pool.get("missing", default="fallback") == "fallback"

    def test_initial_data(self) -> None:
        pool = VariablePool(initial={"input": {"user": "Alice"}})
        assert pool.get("input.user") == "Alice"

    def test_get_all_returns_shallow_copy(self) -> None:
        pool = VariablePool()
        pool.set("node_1", {"result": "ok"})
        snapshot = pool.get_all()
        # Shallow copy: top-level keys are independent
        snapshot["new_key"] = "added"
        assert not pool.has("new_key")
        # Note: nested dicts are shared (shallow copy) — this is expected

    def test_has_exists(self) -> None:
        pool = VariablePool()
        pool.set("node_1", {"result": "ok"})
        assert pool.has("node_1") is True

    def test_has_not_exists(self) -> None:
        pool = VariablePool()
        assert pool.has("nonexistent") is False

    def test_merge(self) -> None:
        pool = VariablePool()
        pool.set("node_1", {"result": "a"})
        pool.merge({"node_2": {"result": "b"}, "extra": "c"})
        assert pool.get("node_1") == {"result": "a"}
        assert pool.get("node_2.result") == "b"
        assert pool.get("extra") == "c"

    def test_merge_overwrites(self) -> None:
        pool = VariablePool()
        pool.set("node_1", {"v": 1})
        pool.merge({"node_1": {"v": 2}})
        assert pool.get("node_1.v") == 2

    def test_snapshot_deep_copy(self) -> None:
        pool = VariablePool()
        pool.set("node_1", {"nested": {"deep": "value"}})
        snap = pool.snapshot()
        # Modify deep snapshot — should not affect pool
        snap["node_1"]["nested"]["deep"] = "changed"
        assert pool.get("node_1.nested.deep") == "value"

    def test_dotted_path_with_list(self) -> None:
        pool = VariablePool()
        pool.set("node_1", {"items": [1, 2, 3]})
        assert pool.get("node_1.items") == [1, 2, 3]
