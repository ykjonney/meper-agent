"""Tests for TaskSchedulerService — background scheduling of timed Tasks."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _fake_task(overrides: dict | None = None) -> dict:
    """Build a fake Task document dict."""
    base = {
        "_id": "task_sched_001",
        "workflow_id": "wf_test",
        "status": "pending",
        "created_by": "user_001",
        "created_by_type": "user",
        "version": 1,
        "input": {},
        "scheduled_at": None,
        "timeline": [],
        "created_at": None,
        "updated_at": None,
    }
    if overrides:
        base.update(overrides)
    return base


# Patch path for TaskService (lazy-imported inside _process_due_tasks)
_TASK_SERVICE = "app.services.task_service.TaskService"


class TestTaskSchedulerLifecycle:
    """TaskSchedulerService lifecycle: start, stop, is_running."""

    @pytest.mark.asyncio
    async def test_start(self):
        """Should start the poll loop."""
        from app.services.task_scheduler_service import TaskSchedulerService

        sched = TaskSchedulerService()
        assert not sched.is_running

        await sched.start()
        assert sched.is_running

        await sched.stop()
        assert not sched.is_running

    @pytest.mark.asyncio
    async def test_start_idempotent(self):
        """Starting twice should be a no-op."""
        from app.services.task_scheduler_service import TaskSchedulerService

        sched = TaskSchedulerService()
        await sched.start()
        task_id = id(sched._task)

        await sched.start()  # second start
        assert id(sched._task) == task_id  # same task

        await sched.stop()

    @pytest.mark.asyncio
    async def test_stop_not_started(self):
        """Stopping before start should not error."""
        from app.services.task_scheduler_service import TaskSchedulerService

        sched = TaskSchedulerService()
        await sched.stop()  # should not raise


class TestProcessDueTasks:
    """_process_due_tasks — finding and starting due Tasks."""

    @pytest.mark.asyncio
    async def test_process_due_tasks(self):
        """Should find and start due Tasks."""
        with (
            patch("app.services.task_scheduler_service.get_database") as mock_db,
            patch(
                "app.services.task_service.TaskService.transition_task",
                new_callable=AsyncMock,
            ) as mock_transition,
            patch(
                "app.services.task_service.TaskService._check_concurrency_limits",
                new_callable=AsyncMock,
            ),
        ):
            col = AsyncMock()
            cursor = MagicMock()
            cursor.sort.return_value = cursor
            cursor.limit.return_value = cursor
            cursor.to_list = AsyncMock(
                return_value=[
                    _fake_task({
                        "_id": "task_due_1",
                        "scheduled_at": "2024-01-01T00:00:00",
                    }),
                    _fake_task({
                        "_id": "task_due_2",
                        "scheduled_at": "2024-01-01T00:00:00",
                    }),
                ]
            )
            col.find = MagicMock(return_value=cursor)
            mock_db.return_value.__getitem__.return_value = col

            from app.services.task_scheduler_service import TaskSchedulerService

            sched = TaskSchedulerService()
            started = await sched._process_due_tasks()

            assert started == 2
            assert mock_transition.await_count == 2

    @pytest.mark.asyncio
    async def test_no_due_tasks(self):
        """Should return 0 when no Tasks are due."""
        with patch("app.services.task_scheduler_service.get_database") as mock_db:
            col = AsyncMock()
            cursor = MagicMock()
            cursor.sort.return_value = cursor
            cursor.limit.return_value = cursor
            cursor.to_list = AsyncMock(return_value=[])
            col.find = MagicMock(return_value=cursor)
            mock_db.return_value.__getitem__.return_value = col

            from app.services.task_scheduler_service import TaskSchedulerService

            sched = TaskSchedulerService()
            started = await sched._process_due_tasks()
            assert started == 0

    @pytest.mark.asyncio
    async def test_skip_when_concurrency_exceeded(self):
        """Should skip Tasks when concurrency limit is hit."""
        with (
            patch("app.services.task_scheduler_service.get_database") as mock_db,
            patch(
                "app.services.task_service.TaskService._check_concurrency_limits",
                new_callable=AsyncMock,
                side_effect=Exception("limit exceeded"),
            ),
            patch(
                "app.services.task_service.TaskService.transition_task",
                new_callable=AsyncMock,
            ) as mock_transition,
        ):
            col = AsyncMock()
            cursor = MagicMock()
            cursor.sort.return_value = cursor
            cursor.limit.return_value = cursor
            cursor.to_list = AsyncMock(
                return_value=[
                    _fake_task({"_id": "task_skipped", "scheduled_at": "2024-01-01"})
                ]
            )
            col.find = MagicMock(return_value=cursor)
            mock_db.return_value.__getitem__.return_value = col

            from app.services.task_scheduler_service import TaskSchedulerService

            sched = TaskSchedulerService()
            started = await sched._process_due_tasks()

            assert started == 0
            mock_transition.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_continue_on_transition_error(self):
        """Should continue processing other tasks if one fails."""
        with (
            patch("app.services.task_scheduler_service.get_database") as mock_db,
            patch(
                "app.services.task_service.TaskService._check_concurrency_limits",
                new_callable=AsyncMock,
            ),
            patch(
                "app.services.task_service.TaskService.transition_task",
                new_callable=AsyncMock,
                side_effect=[Exception("first failed"), None],
            ) as mock_transition,
        ):
            col = AsyncMock()
            cursor = MagicMock()
            cursor.sort.return_value = cursor
            cursor.limit.return_value = cursor
            cursor.to_list = AsyncMock(
                return_value=[
                    _fake_task({"_id": "task_fail", "scheduled_at": "2024-01-01"}),
                    _fake_task({"_id": "task_ok", "scheduled_at": "2024-01-01"}),
                ]
            )
            col.find = MagicMock(return_value=cursor)
            mock_db.return_value.__getitem__.return_value = col

            from app.services.task_scheduler_service import TaskSchedulerService

            sched = TaskSchedulerService()
            started = await sched._process_due_tasks()

            # Only the second task succeeded
            assert started == 1
            assert mock_transition.await_count == 2


class TestSchedulerPollLoop:
    """Poll loop integration with config."""

    @pytest.mark.asyncio
    async def test_disabled_when_interval_zero(self):
        """Should not poll when TASK_SCHEDULER_POLL_INTERVAL is 0."""
        with patch(
            "app.services.task_scheduler_service.settings.TASK_SCHEDULER_POLL_INTERVAL",
            0,
        ):
            from app.services.task_scheduler_service import TaskSchedulerService

            sched = TaskSchedulerService()
            await sched.start()

            # The poll loop should return immediately since interval <= 0
            # Give it a moment to process
            import asyncio
            await asyncio.sleep(0.01)

            assert not sched.is_running  # task finished immediately
