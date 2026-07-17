"""Tests for TaskService.rewind_task and _compute_downstream_nodes (human-node-rewind)."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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


class TestRewindTask:
    """Tests for TaskService.rewind_task orchestration (success + variables)."""

    @pytest.fixture
    def linear_wf_doc(self):
        return {
            "_id": "wf_test",
            "nodes": [
                {"node_id": "start", "type": "start", "config": {"next_nodes": [{"target": "a"}]}},
                {"node_id": "a", "type": "agent", "config": {"next_nodes": [{"target": "human"}]}},
                {"node_id": "human", "type": "human", "config": {"next_nodes": []}},
            ],
        }

    @pytest.fixture
    def waiting_task_doc(self, linear_wf_doc):
        return {
            "_id": "task_1",
            "workflow_id": "wf_test",
            "status": "waiting_human",
            "version": 5,
            "variables": {"start": {"x": 1}, "a": {"out": "v1"}},
            "checkpoint": {
                "paused_at_node": "human",
                "completed_nodes": ["start", "a"],
                "variable_snapshot": {"start": {"x": 1}, "a": {"out": "v1"}},
                "human_context": {"node_id": "human", "title": "审"},
                "agent_thread_id": "",
            },
            "timeline": [],
            "variable_snapshots": [],
        }

    def test_rewind_trims_target_and_downstream_and_reruns(self, linear_wf_doc, waiting_task_doc):
        """Rewind to 'a': completed_nodes loses 'a' (human not in completed), paused→a, human_context cleared."""
        find_one = AsyncMock(side_effect=[waiting_task_doc, linear_wf_doc])
        find_one_and_update = AsyncMock(return_value={
            **waiting_task_doc,
            "status": "running",
            "version": 6,
            "checkpoint": {
                "paused_at_node": "a",
                "completed_nodes": ["start"],
                "variable_snapshot": {"start": {"x": 1}},
                "human_context": {},
            },
        })
        with (
            patch("app.services.task_service.get_database", MagicMock(return_value=AsyncMock(
                __getitem__=lambda self, k: _FakeColl(find_one, find_one_and_update),
            ))),
            patch.object(TaskService, "_write_audit_log", AsyncMock()),
            patch.object(TaskService, "resume_task_execution") as resume_mock,
        ):
            import asyncio
            result = asyncio.run(
                TaskService.rewind_task(
                    task_id="task_1",
                    target_node_id="a",
                    variables=None,
                    comment="回退重跑",
                    triggered_by="user_1",
                    version=5,
                )
            )

        # checkpoint trimmed: paused_at_node='a', 'a' removed from completed_nodes
        update_call = find_one_and_update.await_args
        set_ops = update_call.kwargs.get("update", update_call.args[-1] if update_call.args else {})["$set"]
        assert set_ops["status"] == "running"
        assert set_ops["version"] == 6
        assert set_ops["checkpoint.paused_at_node"] == "a"
        assert set_ops["checkpoint.completed_nodes"] == ["start"]
        assert set_ops["checkpoint.human_context"] == {}
        # 'a' output removed from variable_snapshot
        assert "a" not in set_ops["checkpoint.variable_snapshot"]
        # rewoun timeline event pushed
        push_ops = update_call.kwargs.get("update", update_call.args[-1] if update_call.args else {})["$push"]
        tl_entry = push_ops["timeline"]
        assert tl_entry["event_type"] == "rewoun"
        assert tl_entry["data"]["node_id"] == "a"
        assert "a" in tl_entry["data"]["rewound_nodes"]
        # resume triggered
        assert resume_mock.call_count == 1

    def test_rewind_with_variables_merges_and_snapshots(self, linear_wf_doc, waiting_task_doc):
        """Providing variables merges into pool and pushes a variable_snapshots entry."""
        find_one = AsyncMock(side_effect=[waiting_task_doc, linear_wf_doc])
        find_one_and_update = AsyncMock(return_value={**waiting_task_doc, "status": "running", "version": 6})
        with (
            patch("app.services.task_service.get_database", MagicMock(return_value=AsyncMock(
                __getitem__=lambda self, k: _FakeColl(find_one, find_one_and_update),
            ))),
            patch.object(TaskService, "_write_audit_log", AsyncMock()),
            patch.object(TaskService, "resume_task_execution"),
        ):
            import asyncio
            asyncio.run(
                TaskService.rewind_task(
                    task_id="task_1",
                    target_node_id="a",
                    variables={"start": {"x": 999}},
                    comment=None,
                    triggered_by="user_1",
                    version=5,
                )
            )

        update_call = find_one_and_update.await_args
        set_ops = update_call.kwargs.get("update", update_call.args[-1] if update_call.args else {})["$set"]
        # variables.start.x overridden to 999
        assert set_ops["variables.start"] == {"x": 999}
        # Fix 1 regression guard: override must also land in checkpoint.variable_snapshot
        # so resume (which reads only the snapshot) picks it up.
        assert set_ops["checkpoint.variable_snapshot"]["start"] == {"x": 999}
        # variable_snapshots pushed
        push_ops = update_call.kwargs.get("update", update_call.args[-1] if update_call.args else {})["$push"]
        snap = push_ops["variable_snapshots"]
        assert snap["reason"] == "rewind to a"
        assert snap["triggered_by"] == "user_1"
        assert snap["variables"] == {"start": {"x": 999}}
        # timeline records overridden keys
        tl_entry = push_ops["timeline"]
        assert "start" in tl_entry["data"]["variables_overridden"]


class _FakeColl:
    """Minimal fake MongoDB collection capturing find_one / find_one_and_update."""
    def __init__(self, find_one, find_one_and_update):
        self.find_one = find_one
        self.find_one_and_update = find_one_and_update
