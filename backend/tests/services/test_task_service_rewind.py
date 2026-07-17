"""Tests for TaskService.rewind_task and _compute_downstream_nodes (human-node-rewind)."""
from unittest.mock import AsyncMock, patch  # noqa: F401

import pytest  # noqa: F401

from app.services.task_service import TaskService


def _wf(*nodes):
    """Build a minimal workflow doc with the given nodes (node_id → list of next targets)."""
    return {
        "nodes": [
            {
                "node_id": nid,
                "type": "agent",
                "config": {"next_nodes": [{"target": t} for t in targets]},
            }
            for nid, targets in nodes
        ],
    }


class TestComputeDownstreamNodes:
    def test_linear_chain_returns_all_downstream(self):
        wf = _wf(("start", ["a"]), ("a", ["b"]), ("b", ["human"]), ("human", []))
        result = TaskService._compute_downstream_nodes(wf, "a")
        assert result == {"b", "human"}

    def test_includes_target_neighbors_but_not_target_itself(self):
        """Per spec: returns downstream *excluding* target itself; caller unions target in."""
        wf = _wf(("start", ["a"]), ("a", ["b"]), ("b", []))
        result = TaskService._compute_downstream_nodes(wf, "a")
        assert "a" not in result
        assert result == {"b"}

    def test_parallel_branches_all_collected(self):
        wf = _wf(
            ("a", ["p"]),
            ("p", ["b1", "b2"]),
            ("b1", ["join"]),
            ("b2", ["join"]),
            ("join", ["human"]),
            ("human", []),
        )
        result = TaskService._compute_downstream_nodes(wf, "p")
        assert result == {"b1", "b2", "join", "human"}

    def test_diamond_merges_back(self):
        wf = _wf(
            ("a", ["b", "c"]),
            ("b", ["d"]),
            ("c", ["d"]),
            ("d", ["human"]),
            ("human", []),
        )
        result = TaskService._compute_downstream_nodes(wf, "a")
        assert result == {"b", "c", "d", "human"}

    def test_cycle_does_not_loop_forever(self):
        """Validator forbids cycles, but the function must be defensive."""
        wf = _wf(("a", ["b"]), ("b", ["a"]), ("a2", []))
        result = TaskService._compute_downstream_nodes(wf, "a")
        # Even with a cycle, must terminate; both a's neighbours visited once.
        assert "b" in result

    def test_cycle_does_not_leak_target_into_result(self):
        wf = _wf(("a", ["b"]), ("b", ["a"]))
        result = TaskService._compute_downstream_nodes(wf, "a")
        assert "a" not in result
        assert result == {"b"}

    def test_unknown_next_target_skipped_safely(self):
        wf = _wf(("a", ["ghost"]), ("a2", []))  # 'ghost' node not defined
        result = TaskService._compute_downstream_nodes(wf, "a")
        assert result == set()

    def test_target_with_no_downstream_returns_empty(self):
        wf = _wf(("a", ["b"]), ("b", []))
        result = TaskService._compute_downstream_nodes(wf, "b")
        assert result == set()

    def test_target_not_in_workflow_returns_empty(self):
        wf = _wf(("a", ["b"]), ("b", []))
        result = TaskService._compute_downstream_nodes(wf, "nonexistent")
        assert result == set()
