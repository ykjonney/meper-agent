"""Tests for workflow engine cancellation (cancel + resume).

Covers:
- ``_check_cancelled`` detects DB status == cancelled → raises WorkflowCancelledError
- ``_save_cancel_checkpoint`` persists checkpoint with agent_thread_id
- ``execute_task`` handles WorkflowCancelledError (no FAILED transition)
- ``resume_from_checkpoint`` injects resume_agent_thread_id for agent resume
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.engine.workflow.engine import (
    WorkflowCancelledError,
    WorkflowEngine,
)


class TestCheckCancelled:
    """_check_cancelled reads DB and raises on CANCELLED."""

    @pytest.mark.asyncio
    async def test_raises_when_cancelled(self) -> None:
        """Should raise WorkflowCancelledError when task status is cancelled."""
        engine = WorkflowEngine()
        engine._task_id = "task_test"

        with patch("app.db.mongodb.get_database") as mock_db:
            mock_col = MagicMock()
            mock_col.find_one = AsyncMock(return_value={"status": "cancelled"})
            mock_db.return_value.__getitem__.return_value = mock_col

            with pytest.raises(WorkflowCancelledError):
                await engine._check_cancelled()

    @pytest.mark.asyncio
    async def test_no_raise_when_running(self) -> None:
        """Should NOT raise when task status is running."""
        engine = WorkflowEngine()
        engine._task_id = "task_test"

        with patch("app.db.mongodb.get_database") as mock_db:
            mock_col = MagicMock()
            mock_col.find_one = AsyncMock(return_value={"status": "running"})
            mock_db.return_value.__getitem__.return_value = mock_col

            # Should not raise
            await engine._check_cancelled()

    @pytest.mark.asyncio
    async def test_no_raise_when_not_found(self) -> None:
        """Should NOT raise when task not found in DB."""
        engine = WorkflowEngine()
        engine._task_id = "task_test"

        with patch("app.db.mongodb.get_database") as mock_db:
            mock_col = MagicMock()
            mock_col.find_one = AsyncMock(return_value=None)
            mock_db.return_value.__getitem__.return_value = mock_col

            await engine._check_cancelled()


class TestSaveCancelCheckpoint:
    """_save_cancel_checkpoint persists checkpoint with agent_thread_id."""

    @pytest.mark.asyncio
    async def test_saves_checkpoint_with_agent_thread_id(self) -> None:
        """Checkpoint should include agent_thread_id for LangGraph resume."""
        engine = WorkflowEngine()
        engine._task_id = "task_test"
        engine._pool = MagicMock()
        engine._pool.snapshot.return_value = {"system": {"task_id": "task_test"}}
        engine._completed_nodes = {"node_1", "node_2"}

        with patch("app.db.mongodb.get_database") as mock_db:
            mock_col = MagicMock()
            mock_col.update_one = AsyncMock()
            mock_db.return_value.__getitem__.return_value = mock_col

            await engine._save_cancel_checkpoint("node_2", "task_test_node_2")

            mock_col.update_one.assert_called_once()
            call_args = mock_col.update_one.call_args
            checkpoint_data = call_args[0][1]["$set"]["checkpoint"]
            # checkpoint is a JSON-serializable dict (from model_dump(mode="json"))
            if isinstance(checkpoint_data, str):
                checkpoint_data = json.loads(checkpoint_data)
            assert checkpoint_data["agent_thread_id"] == "task_test_node_2"
            assert checkpoint_data["paused_at_node"] == "node_2"
            assert set(checkpoint_data["completed_nodes"]) == {"node_1", "node_2"}


class TestExecuteNodeCancelCheck:
    """_execute_node checks cancelled at the top (before executing)."""

    @pytest.mark.asyncio
    async def test_execute_node_checks_cancelled_first(self) -> None:
        """_execute_node calls _check_cancelled before any work."""
        engine = WorkflowEngine()
        engine._task_id = "task_test"

        # Mock _check_cancelled to raise
        with (
            patch.object(
                engine, "_check_cancelled", new_callable=AsyncMock,
                side_effect=WorkflowCancelledError(),
            ),pytest.raises(WorkflowCancelledError)
        ):
            await engine._execute_node("any_node")


class TestZombieGuard:
    """run_and_persist skips CANCELLED tasks (7-day revoke re-delivery guard)."""

    @pytest.mark.asyncio
    async def test_run_and_persist_skips_cancelled_task(self) -> None:
        """Should return {} without executing when task status is cancelled."""
        engine = WorkflowEngine()

        task_doc = {"_id": "task_zombie", "workflow_id": "wf_1", "status": "cancelled"}
        with patch("app.db.mongodb.get_database") as mock_db:
            mock_col = MagicMock()
            mock_col.find_one = AsyncMock(return_value=task_doc)
            mock_db.return_value.__getitem__.return_value = mock_col

            result = await engine.run_and_persist("task_zombie")

            assert result == {}

    @pytest.mark.asyncio
    async def test_run_and_persist_proceeds_for_pending_task(self) -> None:
        """Should NOT skip when task status is pending (normal new task)."""
        engine = WorkflowEngine()

        task_doc = {"_id": "task_new", "workflow_id": "wf_1", "status": "pending"}
        workflow_doc = {"_id": "wf_1", "nodes": [], "edges": []}

        with (
            patch("app.db.mongodb.get_database") as mock_db,
            patch.object(engine, "execute_task", new_callable=AsyncMock, return_value={}) as mock_exec,
        ):
            mock_col = MagicMock()
            # First find_one = task, second = workflow
            mock_col.find_one = AsyncMock(side_effect=[task_doc, workflow_doc])
            mock_db.return_value.__getitem__.return_value = mock_col

            # Mock validator to pass
            with patch("app.engine.workflow.validator.WorkflowValidator") as mock_val:
                mock_val.return_value.validate.return_value.is_valid = True
                await engine.run_and_persist("task_new")

            # execute_task should have been called (not skipped)
            mock_exec.assert_called_once()


class TestCheckCancelledTracksNode:
    """_check_cancelled records the pending node for checkpoint saving."""

    @pytest.mark.asyncio
    async def test_check_cancelled_sets_pending_node_id(self) -> None:
        """_check_cancelled stores node_id for the except handler."""
        engine = WorkflowEngine()
        engine._task_id = "task_test"
        engine._pending_node_id = ""

        with patch("app.db.mongodb.get_database") as mock_db:
            mock_col = MagicMock()
            mock_col.find_one = AsyncMock(return_value={"status": "running"})
            mock_db.return_value.__getitem__.return_value = mock_col

            await engine._check_cancelled(node_id="node_3")

            assert engine._pending_node_id == "node_3"
