"""Tests for task recovery service — recover_waiting_human_tasks."""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.models.task import TaskStatus, utc_now
from app.services.task_recovery import (
    _execute_timeout_action,
    recover_waiting_human_tasks,
)


class AsyncCursorMock:
    """Async iterator mock that supports `async for`."""

    def __init__(self, items: list):
        self._items = iter(items)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._items)
        except StopIteration:
            raise StopAsyncIteration from None


class TestRecoverWaitingHumanTasks:
    """Test recover_waiting_human_tasks function."""

    @pytest.mark.asyncio
    async def test_no_tasks_to_recover(self) -> None:
        """No tasks found → no recovery needed."""
        mock_cursor = AsyncCursorMock([])

        with patch("app.services.task_recovery.get_database") as mock_db:
            mock_collection = MagicMock()
            mock_db.return_value = {"tasks": mock_collection}
            mock_collection.find = MagicMock(return_value=mock_cursor)

            # Should not raise
            await recover_waiting_human_tasks()

    @pytest.mark.asyncio
    async def test_recover_timed_out_task(self) -> None:
        """Timed-out task → execute timeout_action immediately."""
        now = utc_now()
        past_deadline = now - timedelta(minutes=10)

        task_doc = {
            "_id": "task_timeout",
            "status": TaskStatus.WAITING_HUMAN.value,
            "checkpoint": {
                "paused_at_node": "human_1",
                "timeout_deadline": past_deadline.isoformat(),
                "timeout_action": "auto_approve",
            },
        }

        mock_cursor = AsyncCursorMock([task_doc])

        with patch("app.services.task_recovery.get_database") as mock_db:
            mock_collection = MagicMock()
            mock_db.return_value = {"tasks": mock_collection}
            mock_collection.find = MagicMock(return_value=mock_cursor)

            with patch("app.services.task_recovery._execute_timeout_action", new_callable=AsyncMock) as mock_action:
                await recover_waiting_human_tasks()
                mock_action.assert_called_once_with(
                    task_id="task_timeout",
                    timeout_action="auto_approve",
                )

    @pytest.mark.asyncio
    async def test_recover_non_timed_out_task(self) -> None:
        """Non-timed-out task → restart timeout monitor with remaining time."""
        now = utc_now()
        future_deadline = now + timedelta(minutes=5)

        task_doc = {
            "_id": "task_pending",
            "status": TaskStatus.WAITING_HUMAN.value,
            "checkpoint": {
                "paused_at_node": "human_2",
                "timeout_deadline": future_deadline.isoformat(),
                "timeout_action": "fail",
            },
        }

        mock_cursor = AsyncCursorMock([task_doc])

        with patch("app.services.task_recovery.get_database") as mock_db:
            mock_collection = MagicMock()
            mock_db.return_value = {"tasks": mock_collection}
            mock_collection.find = MagicMock(return_value=mock_cursor)

            with patch("app.services.task_recovery._restart_timeout_monitor", new_callable=AsyncMock) as mock_restart:
                await recover_waiting_human_tasks()
                mock_restart.assert_called_once()
                # Verify remaining_ms is positive
                call_kwargs = mock_restart.call_args.kwargs
                assert call_kwargs["timeout_ms"] > 0

    @pytest.mark.asyncio
    async def test_recover_no_timeout_configured(self) -> None:
        """Task without timeout_deadline → just log, no action."""
        task_doc = {
            "_id": "task_no_timeout",
            "status": TaskStatus.WAITING_HUMAN.value,
            "checkpoint": {
                "paused_at_node": "human_3",
                "timeout_deadline": None,
                "timeout_action": "fail",
            },
        }

        mock_cursor = AsyncCursorMock([task_doc])

        with patch("app.services.task_recovery.get_database") as mock_db:
            mock_collection = MagicMock()
            mock_db.return_value = {"tasks": mock_collection}
            mock_collection.find = MagicMock(return_value=mock_cursor)

            with (
                patch("app.services.task_recovery._execute_timeout_action", new_callable=AsyncMock) as mock_action,
                patch("app.services.task_recovery._restart_timeout_monitor", new_callable=AsyncMock) as mock_restart,
            ):
                await recover_waiting_human_tasks()
                # Neither action should be called
                mock_action.assert_not_called()
                mock_restart.assert_not_called()


class TestExecuteTimeoutAction:
    """Test _execute_timeout_action helper."""

    @pytest.mark.asyncio
    async def test_auto_approve_transitions_to_running(self) -> None:
        """auto_approve → RUNNING + resume."""
        with (
            patch("app.services.task_service.TaskService.transition_task", new_callable=AsyncMock) as mock_transition,
            patch("app.services.task_service.TaskService.resume_task_execution") as mock_resume,
        ):
            await _execute_timeout_action("task_1", "auto_approve")

            mock_transition.assert_called_once()
            call_kwargs = mock_transition.call_args.kwargs
            assert call_kwargs["to_status"] == TaskStatus.RUNNING
            mock_resume.assert_called_once_with("task_1")

    @pytest.mark.asyncio
    async def test_fail_transitions_to_failed(self) -> None:
        """fail → FAILED (no resume)."""
        with (
            patch("app.services.task_service.TaskService.transition_task", new_callable=AsyncMock) as mock_transition,
            patch("app.services.task_service.TaskService.resume_task_execution") as mock_resume,
        ):
            await _execute_timeout_action("task_1", "fail")

            mock_transition.assert_called_once()
            call_kwargs = mock_transition.call_args.kwargs
            assert call_kwargs["to_status"] == TaskStatus.FAILED
            mock_resume.assert_not_called()

    @pytest.mark.asyncio
    async def test_auto_skip_transitions_to_running(self) -> None:
        """auto_skip → RUNNING + resume."""
        with (
            patch("app.services.task_service.TaskService.transition_task", new_callable=AsyncMock) as mock_transition,
            patch("app.services.task_service.TaskService.resume_task_execution") as mock_resume,
        ):
            await _execute_timeout_action("task_1", "auto_skip")

            mock_transition.assert_called_once()
            call_kwargs = mock_transition.call_args.kwargs
            assert call_kwargs["to_status"] == TaskStatus.RUNNING
            mock_resume.assert_called_once_with("task_1")
