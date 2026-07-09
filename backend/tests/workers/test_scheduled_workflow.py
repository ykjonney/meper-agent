"""Tests for execute_scheduled_workflow Celery task.

The simplified execute (post eta-self-chain removal) only:
  loads trigger → loads workflow → renders input → finds placeholder Task
  → runs engine → updates last_triggered_at.

The placeholder Task and next firing are owned by TriggerSchedulerService,
so these tests verify that execute consumes the placeholder correctly and
does NOT re-schedule.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.trigger import Trigger


def _make_trigger_doc(*, enabled: bool = True, default_input: dict | None = None) -> dict:
    """Build a trigger document dict as stored in MongoDB."""
    t = Trigger(
        _id="trig_xxx",
        workflow_id="wf_xxx",
        user_id="user_1",
        type="cron",
        enabled=enabled,
        cron_expression="0 9 * * *",
        default_input=default_input or {"date": "{{ today() }}"},
    )
    return t.model_dump(by_alias=True)


class TestExecuteScheduledWorkflow:
    """Tests for execute_scheduled_workflow task."""

    @patch("app.workers.tasks.scheduled_workflow.WorkflowEngine")
    @patch("app.workers.tasks.scheduled_workflow.render_default_input")
    @patch("app.workers.tasks.scheduled_workflow.TriggerRepository")
    @patch("app.workers.tasks.scheduled_workflow.get_database")
    async def test_execute_success(
        self,
        mock_db_func: MagicMock,
        mock_repo_cls: MagicMock,
        mock_render: MagicMock,
        mock_engine_class: MagicMock,
    ) -> None:
        """Should execute a trigger's placeholder task via the engine."""
        trigger_doc = _make_trigger_doc()
        workflow_doc = {"_id": "wf_xxx", "name": "Test"}
        placeholder = {"_id": "task_xxx", "status": "pending"}

        # repo.find_by_id returns the Trigger
        mock_repo = MagicMock()
        mock_repo.find_by_id = AsyncMock(return_value=Trigger(**trigger_doc))
        mock_repo.update = AsyncMock()
        mock_repo_cls.return_value = mock_repo

        # db["workflows"].find_one returns workflow; db["tasks"].find_one returns placeholder
        mock_db = MagicMock()

        workflows_col = MagicMock()
        workflows_col.find_one = AsyncMock(return_value=workflow_doc)

        tasks_col = MagicMock()
        tasks_col.find_one = AsyncMock(return_value=placeholder)

        # __getitem__ routes to the right collection
        def getitem(name):
            return {"workflows": workflows_col, "tasks": tasks_col}[name]

        mock_db.__getitem__ = MagicMock(side_effect=getitem)
        mock_db_func.return_value = mock_db

        mock_render.return_value = {"date": "2026-07-09"}

        mock_engine = MagicMock()
        mock_engine.run_and_persist = AsyncMock()
        mock_engine_class.return_value = mock_engine

        from app.workers.tasks.scheduled_workflow import _execute_async

        result = await _execute_async("trig_xxx")

        assert result["status"] == "success"
        assert result["task_id"] == "task_xxx"
        mock_engine.run_and_persist.assert_awaited_once_with("task_xxx")
        mock_render.assert_called_once()
        # last_triggered_at updated
        mock_repo.update.assert_awaited()

    @patch("app.workers.tasks.scheduled_workflow.TriggerRepository")
    @patch("app.workers.tasks.scheduled_workflow.get_database")
    async def test_trigger_not_found(self, mock_db_func, mock_repo_cls) -> None:
        """Should return error if trigger does not exist."""
        mock_repo = MagicMock()
        mock_repo.find_by_id = AsyncMock(return_value=None)
        mock_repo_cls.return_value = mock_repo

        from app.workers.tasks.scheduled_workflow import _execute_async

        result = await _execute_async("trig_missing")
        assert result["status"] == "error"
        assert "not found" in result["message"].lower()

    @patch("app.workers.tasks.scheduled_workflow.TriggerRepository")
    @patch("app.workers.tasks.scheduled_workflow.get_database")
    async def test_disabled_trigger_skipped(self, mock_db_func, mock_repo_cls) -> None:
        """Should skip a disabled trigger."""
        trigger_doc = _make_trigger_doc(enabled=False)
        mock_repo = MagicMock()
        mock_repo.find_by_id = AsyncMock(return_value=Trigger(**trigger_doc))
        mock_repo_cls.return_value = mock_repo

        from app.workers.tasks.scheduled_workflow import _execute_async

        result = await _execute_async("trig_xxx")
        assert result["status"] == "skipped"

    @patch("app.workers.tasks.scheduled_workflow.render_default_input")
    @patch("app.workers.tasks.scheduled_workflow.TriggerRepository")
    @patch("app.workers.tasks.scheduled_workflow.get_database")
    async def test_workflow_not_found(self, mock_db_func, mock_repo_cls, mock_render) -> None:
        """Should return error if workflow is missing."""
        trigger_doc = _make_trigger_doc()
        mock_repo = MagicMock()
        mock_repo.find_by_id = AsyncMock(return_value=Trigger(**trigger_doc))
        mock_repo_cls.return_value = mock_repo

        mock_db = MagicMock()
        workflows_col = MagicMock()
        workflows_col.find_one = AsyncMock(return_value=None)
        mock_db.__getitem__ = MagicMock(return_value=workflows_col)
        mock_db_func.return_value = mock_db

        from app.workers.tasks.scheduled_workflow import _execute_async

        result = await _execute_async("trig_xxx")
        assert result["status"] == "error"
        assert "workflow" in result["message"].lower()

    @patch("app.workers.tasks.scheduled_workflow.render_default_input")
    @patch("app.workers.tasks.scheduled_workflow.TriggerRepository")
    @patch("app.workers.tasks.scheduled_workflow.get_database")
    async def test_placeholder_not_found_skips(self, mock_db_func, mock_repo_cls, mock_render) -> None:
        """If no pending placeholder exists (duplicate dispatch), skip gracefully."""
        trigger_doc = _make_trigger_doc()
        mock_repo = MagicMock()
        mock_repo.find_by_id = AsyncMock(return_value=Trigger(**trigger_doc))
        mock_repo_cls.return_value = mock_repo

        mock_db = MagicMock()
        workflows_col = MagicMock()
        workflows_col.find_one = AsyncMock(return_value={"_id": "wf_xxx"})
        tasks_col = MagicMock()
        tasks_col.find_one = AsyncMock(return_value=None)  # no placeholder

        def getitem(name):
            return {"workflows": workflows_col, "tasks": tasks_col}[name]

        mock_db.__getitem__ = MagicMock(side_effect=getitem)
        mock_db_func.return_value = mock_db
        mock_render.return_value = {}

        from app.workers.tasks.scheduled_workflow import _execute_async

        result = await _execute_async("trig_xxx")
        # No placeholder → skip (not error), next firing handled by poller
        assert result["status"] == "skipped"

    @patch("app.workers.tasks.scheduled_workflow.WorkflowEngine")
    @patch("app.workers.tasks.scheduled_workflow.render_default_input")
    @patch("app.workers.tasks.scheduled_workflow.TriggerRepository")
    @patch("app.workers.tasks.scheduled_workflow.get_database")
    async def test_engine_failure_returns_error(
        self,
        mock_db_func: MagicMock,
        mock_repo_cls: MagicMock,
        mock_render: MagicMock,
        mock_engine_class: MagicMock,
    ) -> None:
        """Engine exception → result status error with task_id."""
        trigger_doc = _make_trigger_doc()
        mock_repo = MagicMock()
        mock_repo.find_by_id = AsyncMock(return_value=Trigger(**trigger_doc))
        mock_repo.update = AsyncMock()
        mock_repo_cls.return_value = mock_repo

        mock_db = MagicMock()
        workflows_col = MagicMock()
        workflows_col.find_one = AsyncMock(return_value={"_id": "wf_xxx"})
        tasks_col = MagicMock()
        tasks_col.find_one = AsyncMock(return_value={"_id": "task_xxx"})

        def getitem(name):
            return {"workflows": workflows_col, "tasks": tasks_col}[name]

        mock_db.__getitem__ = MagicMock(side_effect=getitem)
        mock_db_func.return_value = mock_db
        mock_render.return_value = {}

        mock_engine = MagicMock()
        mock_engine.run_and_persist = AsyncMock(side_effect=Exception("Engine boom"))
        mock_engine_class.return_value = mock_engine

        from app.workers.tasks.scheduled_workflow import _execute_async

        result = await _execute_async("trig_xxx")
        assert result["status"] == "error"
        assert result["task_id"] == "task_xxx"
        assert "Engine boom" in result["message"]
