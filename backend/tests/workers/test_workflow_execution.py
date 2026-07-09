"""Tests for run_workflow_task Celery task — generic workflow execution.

Verifies that the task correctly delegates to WorkflowEngine.run_and_persist
and handles success/failure. Follows the project pattern of awaiting the
internal async function directly with mocked dependencies.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestRunWorkflowTask:
    """Tests for run_workflow_task."""

    @patch("app.workers.tasks.workflow_execution.WorkflowEngine")
    async def test_run_success(self, mock_engine_class: MagicMock) -> None:
        """Should run the engine and return success."""
        mock_engine = MagicMock()
        mock_engine.run_and_persist = AsyncMock()
        mock_engine_class.return_value = mock_engine

        from app.workers.tasks.workflow_execution import _run_async

        result = await _run_async("task_xxx")

        assert result["status"] == "success"
        assert result["task_id"] == "task_xxx"
        mock_engine.run_and_persist.assert_awaited_once_with("task_xxx")

    @patch("app.workers.tasks.workflow_execution.WorkflowEngine")
    async def test_run_engine_raises(self, mock_engine_class: MagicMock) -> None:
        """Should return error if engine raises (engine usually handles its
        own FAILED transition, but this guards the outer boundary)."""
        mock_engine = MagicMock()
        mock_engine.run_and_persist = AsyncMock(side_effect=RuntimeError("boom"))
        mock_engine_class.return_value = mock_engine

        from app.workers.tasks.workflow_execution import _run_async

        result = await _run_async("task_fail")

        assert result["status"] == "error"
        assert result["task_id"] == "task_fail"
        assert "boom" in result["message"]


class TestTaskServiceDispatch:
    """Verify TaskService._start/resume dispatch to Celery, not asyncio."""

    @patch("app.workers.tasks.workflow_execution.run_workflow_task")
    def test_start_dispatches_celery(self, mock_celery_task: MagicMock) -> None:
        """_start_workflow_execution should call run_workflow_task.delay."""
        from app.services.task_service import TaskService

        TaskService._start_workflow_execution("task_123")

        mock_celery_task.delay.assert_called_once_with("task_123")

    @patch("app.workers.tasks.workflow_execution.run_workflow_task")
    def test_resume_dispatches_celery(self, mock_celery_task: MagicMock) -> None:
        """resume_task_execution should call run_workflow_task.delay."""
        from app.services.task_service import TaskService

        TaskService.resume_task_execution("task_456")

        mock_celery_task.delay.assert_called_once_with("task_456")
