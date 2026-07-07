"""Tests for execute_scheduled_workflow Celery task."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestExecuteScheduledWorkflow:
    """Tests for execute_scheduled_workflow task."""

    @patch("app.workers.tasks.scheduled_workflow.WorkflowEngine")
    @patch("app.workers.tasks.scheduled_workflow.TaskService")
    @patch("app.workers.tasks.scheduled_workflow.render_default_input")
    @patch("app.workers.tasks.scheduled_workflow.get_database")
    async def test_execute_success(
        self,
        mock_db_func: MagicMock,
        mock_render: MagicMock,
        mock_task_service: MagicMock,
        mock_engine_class: MagicMock,
    ) -> None:
        """Should successfully execute a scheduled workflow."""
        # Mock database
        workflow_doc = {
            "_id": "wf_xxx",
            "name": "Test Workflow",
            "trigger_config": {
                "type": "cron",
                "default_input": {"date": "{{ today() }}"},
            },
        }
        mock_db = MagicMock()
        mock_db_func.return_value = mock_db
        mock_db.__getitem__ = MagicMock()
        mock_db.__getitem__.return_value.find_one = AsyncMock(return_value=workflow_doc)
        mock_db.__getitem__.return_value.update_one = AsyncMock()

        # Mock template rendering
        mock_render.return_value = {"date": "2026-07-07"}

        # Mock TaskService.create_task
        task_doc = {"_id": "task_xxx", "status": "pending"}
        mock_task_service.create_task = AsyncMock(return_value=task_doc)

        # Mock WorkflowEngine
        mock_engine = MagicMock()
        mock_engine.run_and_persist = AsyncMock(return_value={"result": "success"})
        mock_engine_class.return_value = mock_engine

        # Execute
        from app.workers.tasks.scheduled_workflow import _execute_async

        result = await _execute_async("wf_xxx")

        # Verify
        assert result["status"] == "success"
        assert result["task_id"] == "task_xxx"
        mock_task_service.create_task.assert_called_once()
        mock_engine.run_and_persist.assert_called_once_with("task_xxx")

    @patch("app.workers.tasks.scheduled_workflow.get_database")
    async def test_execute_workflow_not_found(self, mock_db_func: MagicMock) -> None:
        """Should return error if workflow not found."""
        mock_db = MagicMock()
        mock_db_func.return_value = mock_db
        mock_db.__getitem__ = MagicMock()
        mock_db.__getitem__.return_value.find_one = AsyncMock(return_value=None)

        from app.workers.tasks.scheduled_workflow import _execute_async

        result = await _execute_async("wf_not_exist")

        assert result["status"] == "error"
        assert "not found" in result["message"].lower()

    @patch("app.workers.tasks.scheduled_workflow.get_database")
    async def test_execute_disabled_trigger(self, mock_db_func: MagicMock) -> None:
        """Should return error if trigger is disabled."""
        workflow_doc = {
            "_id": "wf_xxx",
            "trigger_config": {"enabled": False},
        }
        mock_db = MagicMock()
        mock_db_func.return_value = mock_db
        mock_db.__getitem__ = MagicMock()
        mock_db.__getitem__.return_value.find_one = AsyncMock(return_value=workflow_doc)

        from app.workers.tasks.scheduled_workflow import _execute_async

        result = await _execute_async("wf_xxx")

        assert result["status"] == "error"
        assert "disabled" in result["message"].lower()
