"""Tests for WorkflowEngine checkpoint save and resume_from_checkpoint."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from app.engine.workflow.engine import WorkflowEngine


class TestGetDownstreamNodes:
    """Test _get_downstream_nodes helper."""

    def test_downstream_from_config(self) -> None:
        """Reads downstream nodes from config.next_nodes."""
        engine = WorkflowEngine()
        engine._node_map = {
            "human_1": {
                "node_id": "human_1",
                "type": "human",
                "config": {
                    "next_nodes": [
                        {"target": "gateway_1", "label": "approve"},
                        {"target": "end_1", "label": "reject"},
                    ]
                },
            }
        }
        engine._out_edges = {}

        result = engine._get_downstream_nodes("human_1")
        assert result == ["gateway_1", "end_1"]

    def test_downstream_from_legacy_edges(self) -> None:
        """Falls back to legacy edges when no config.next_nodes."""
        engine = WorkflowEngine()
        engine._node_map = {
            "human_1": {
                "node_id": "human_1",
                "type": "human",
                "config": {},
            }
        }
        engine._out_edges = {
            "human_1": [
                {"source": "human_1", "target": "agent_2"},
                {"source": "human_1", "target": "end_1"},
            ]
        }

        result = engine._get_downstream_nodes("human_1")
        assert result == ["agent_2", "end_1"]

    def test_downstream_unknown_node(self) -> None:
        """Returns empty list for unknown node."""
        engine = WorkflowEngine()
        engine._node_map = {}
        engine._out_edges = {}

        result = engine._get_downstream_nodes("nonexistent")
        assert result == []

    def test_downstream_no_next(self) -> None:
        """Returns empty list when node has no outgoing edges."""
        engine = WorkflowEngine()
        engine._node_map = {
            "end_1": {"node_id": "end_1", "type": "end", "config": {}}
        }
        engine._out_edges = {}

        result = engine._get_downstream_nodes("end_1")
        assert result == []


class TestResumeFromCheckpoint:
    """Test resume_from_checkpoint method."""

    @pytest.mark.asyncio
    async def test_resume_no_checkpoint_returns_empty(self) -> None:
        """Returns empty dict when no checkpoint exists."""
        engine = WorkflowEngine()
        with patch("app.db.mongodb.get_database") as mock_db:
            mock_collection = AsyncMock()
            mock_db.return_value = {"tasks": mock_collection}
            mock_collection.find_one = AsyncMock(return_value={
                "_id": "task_1",
                "workflow_id": "wf_1",
                "checkpoint": None,
            })

            result = await engine.resume_from_checkpoint("task_1")
            assert result == {}

    @pytest.mark.asyncio
    async def test_resume_task_not_found(self) -> None:
        """Returns empty dict when task not found."""
        engine = WorkflowEngine()
        with patch("app.db.mongodb.get_database") as mock_db:
            mock_collection = AsyncMock()
            mock_db.return_value = {"tasks": mock_collection}
            mock_collection.find_one = AsyncMock(return_value=None)

            result = await engine.resume_from_checkpoint("task_nonexistent")
            assert result == {}

    @pytest.mark.asyncio
    async def test_resume_restores_completed_nodes(self) -> None:
        """Resume restores completed_nodes from checkpoint."""
        engine = WorkflowEngine()

        checkpoint_data = {
            "paused_at_node": "human_1",
            "completed_nodes": ["start_1", "agent_1"],
            "variable_snapshot": {"input": {"q": "test"}, "agent_1": {"result": "ok"}},
            "human_context": {"title": "审批"},
            "timeout_action": "fail",
        }

        workflow_doc = {
            "_id": "wf_1",
            "nodes": [
                {"node_id": "start_1", "type": "start", "config": {"next_nodes": [{"target": "agent_1"}]}},
                {"node_id": "agent_1", "type": "agent", "config": {"next_nodes": [{"target": "human_1"}]}},
                {"node_id": "human_1", "type": "human", "config": {"next_nodes": [{"target": "end_1"}]}},
                {"node_id": "end_1", "type": "end", "config": {}},
            ],
            "edges": [],
        }

        with patch("app.db.mongodb.get_database") as mock_db:
            mock_tasks_col = AsyncMock()
            mock_workflows_col = AsyncMock()
            mock_db.return_value = {
                "tasks": mock_tasks_col,
                "workflows": mock_workflows_col,
            }
            mock_tasks_col.find_one = AsyncMock(return_value={
                "_id": "task_1",
                "workflow_id": "wf_1",
                "checkpoint": checkpoint_data,
            })
            mock_workflows_col.find_one = AsyncMock(return_value=workflow_doc)

            # Mock _execute_node to avoid actual execution
            with (
                patch.object(engine, "_execute_node", new_callable=AsyncMock) as mock_exec,
                patch.object(engine, "_migrate_edges_to_next_nodes"),
                patch("app.services.task_service.TaskService.transition_task", new_callable=AsyncMock),
            ):
                await engine.resume_from_checkpoint("task_1")

            # Verify completed_nodes restored (plus human_1 added)
            assert "start_1" in engine._completed_nodes
            assert "agent_1" in engine._completed_nodes
            assert "human_1" in engine._completed_nodes

            # Verify pool restored
            assert engine._pool is not None
            assert engine._pool.get("agent_1") == {"result": "ok"}

            # Verify downstream node was executed
            mock_exec.assert_called_once_with("end_1")
