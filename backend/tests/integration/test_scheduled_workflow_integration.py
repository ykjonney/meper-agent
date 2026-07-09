"""End-to-end integration test for the scheduled workflow trigger flow.

Exercises the full chain:

    Workflow (with trigger_config)
        → TriggerSchedulerService.start() loads & registers triggers
        → execute_scheduled_workflow() is invoked manually
        → TaskService.create_task() persists a Task document
        → WorkflowEngine.run_and_persist() runs the workflow
        → trigger_config.last_triggered_at is updated

External dependencies (MongoDB, Celery, WorkflowEngine) are mocked so
the test can run without a real database or worker process while still
verifying cross-component integration.
"""
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.trigger_scheduler_service import TriggerSchedulerService
from app.workers.tasks.scheduled_workflow import _execute_async

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _async_iter(items: list) -> AsyncIterator:
    """Helper: async iterator over a list of items."""
    for item in items:
        yield item


def _make_mock_db(
    find_result: list | None = None,
    find_one_result: dict | None = None,
) -> MagicMock:
    """Build a mocked ``get_database()`` return value."""
    mock_db = MagicMock()
    mock_col = MagicMock()
    if find_result is not None:
        mock_col.find = MagicMock(return_value=_async_iter(find_result))
    if find_one_result is not None or find_result is None:
        mock_col.find_one = AsyncMock(return_value=find_one_result)
    # update_one / insert_one return a dummy result
    mock_col.update_one = AsyncMock(return_value=MagicMock(modified_count=1))
    mock_col.insert_one = AsyncMock(
        return_value=MagicMock(inserted_id="task_001"),
    )
    mock_db.__getitem__.return_value = mock_col
    return mock_db


def _sample_workflow(workflow_id: str = "wf_scheduled") -> dict:
    """Return a minimal workflow document with trigger_config."""
    return {
        "_id": workflow_id,
        "name": "Scheduled Demo Workflow",
        "trigger_config": {
            "enabled": True,
            "type": "cron",
            "cron_expression": "0 9 * * *",
            "default_input": {"greeting": "hello"},
        },
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestScheduledWorkflowEndToEnd:
    """Full lifecycle: load trigger → execute → create Task → update."""

    @patch("app.workers.tasks.scheduled_workflow.WorkflowEngine")
    @patch("app.workers.tasks.scheduled_workflow.TaskService")
    @patch("app.workers.tasks.scheduled_workflow.get_database")
    @patch("app.services.trigger_scheduler_service.get_database")
    async def test_end_to_end_scheduled_trigger(
        self,
        mock_scheduler_get_db: MagicMock,
        mock_exec_get_db: MagicMock,
        mock_task_service: MagicMock,
        mock_engine_cls: MagicMock,
    ) -> None:
        """AC: Scheduled trigger flow creates a Task and runs the engine.

        1. Create workflow with trigger_config (simulated in DB mock).
        2. Start TriggerSchedulerService → trigger is loaded.
        3. Manually invoke execute_scheduled_workflow.
        4. Verify TaskService.create_task is called with correct args.
        5. Verify WorkflowEngine.run_and_persist is called with the task_id.
        6. Verify trigger_config.last_triggered_at update is issued.
        """
        workflow_doc = _sample_workflow()
        workflow_id = workflow_doc["_id"]

        # --- DB for the scheduler ---
        mock_scheduler_get_db.return_value = _make_mock_db(
            find_result=[workflow_doc],
        )

        # --- DB for execute_async (separate call) ---
        mock_exec_get_db.return_value = _make_mock_db(
            find_one_result=workflow_doc,
        )

        # --- TaskService.create_task returns a fake task doc ---
        fake_task = {"_id": "task_001", "workflow_id": workflow_id}
        mock_task_service.create_task = AsyncMock(return_value=fake_task)

        # --- Engine mock ---
        mock_engine = MagicMock()
        mock_engine.run_and_persist = AsyncMock(return_value={"status": "success"})
        mock_engine_cls.return_value = mock_engine

        # ---- Step 1: Start scheduler & verify trigger loaded ----
        service = TriggerSchedulerService()
        await service.start()

        assert service._started is True
        assert workflow_id in service._workflows
        assert (
            service._workflows[workflow_id]["trigger_config"]["type"] == "cron"
        )

        # ---- Step 2: Execute scheduled workflow ----
        result = await _execute_async(workflow_id)

        # ---- Step 3: Assertions ----
        assert result["status"] == "success"
        assert result["task_id"] == "task_001"

        mock_task_service.create_task.assert_awaited_once()
        create_kwargs = mock_task_service.create_task.call_args.kwargs
        assert create_kwargs["workflow_id"] == workflow_id
        assert create_kwargs["created_by"] == "system"
        assert create_kwargs["created_by_type"] == "system"

        mock_engine.run_and_persist.assert_awaited_once_with("task_001")

        # Verify last_triggered_at update was issued
        exec_db = mock_exec_get_db.return_value
        exec_db.__getitem__.return_value.update_one.assert_awaited_once()
        update_call = (
            exec_db.__getitem__.return_value.update_one.call_args.args
        )
        assert update_call[0] == {"_id": workflow_id}
        assert "trigger_config.last_triggered_at" in update_call[1]["$set"]

        # Cleanup
        await service.stop()
        assert service._started is False

    @patch("app.workers.tasks.scheduled_workflow.get_database")
    async def test_execute_disabled_trigger_returns_error(
        self,
        mock_get_db: MagicMock,
    ) -> None:
        """Disabled trigger_config should short-circuit with an error."""
        workflow_doc = _sample_workflow()
        workflow_doc["trigger_config"]["enabled"] = False
        mock_get_db.return_value = _make_mock_db(find_one_result=workflow_doc)

        result = await _execute_async("wf_scheduled")
        assert result["status"] == "error"
        assert "disabled" in result["message"].lower()

    @patch("app.workers.tasks.scheduled_workflow.get_database")
    async def test_execute_missing_workflow_returns_error(
        self,
        mock_get_db: MagicMock,
    ) -> None:
        """Missing workflow doc should short-circuit with not-found error."""
        mock_get_db.return_value = _make_mock_db(find_one_result=None)

        result = await _execute_async("wf_not_exist")
        assert result["status"] == "error"
        assert "not found" in result["message"].lower()
