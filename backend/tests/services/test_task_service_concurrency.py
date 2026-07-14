"""Tests for TaskService concurrency control — limits and FIFO scheduling."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.models.task import TaskStatus

# Test settings override
_GLOBAL_LIMIT = 3
_USER_LIMIT = 2


@pytest.fixture(autouse=True)
def _override_settings():
    """Override concurrency limits for test predictability."""
    with (
        patch("app.services.task_service.settings") as mock_settings,
    ):
        mock_settings.TASK_GLOBAL_MAX_RUNNING = _GLOBAL_LIMIT
        mock_settings.TASK_USER_MAX_RUNNING = _USER_LIMIT
        yield


def _fake_task(overrides: dict | None = None) -> dict:
    """Build a fake Task document dict."""
    base = {
        "_id": "task_test_001",
        "workflow_id": "wf_test",
        "status": "pending",
        "created_by": "user_001",
        "created_by_type": "user",
        "version": 1,
        "input": {},
        "timeline": [],
        "created_at": None,
        "updated_at": None,
    }
    if overrides:
        base.update(overrides)
    return base


class TestConcurrencyCheck:
    """_check_concurrency_limits — global and per-user limits."""

    @pytest.mark.asyncio
    async def test_global_limit_exceeded(self):
        """Should reject when global running count >= limit."""
        with patch(
            "app.services.task_service.get_database"
        ) as mock_db:
            col = AsyncMock()
            col.count_documents = AsyncMock(
                side_effect=lambda q: _GLOBAL_LIMIT if q.get("status") == "running" else 0
            )
            mock_db.return_value.__getitem__.return_value = col

            from app.core.errors import ConflictError
            from app.services.task_service import TaskService

            with pytest.raises(ConflictError) as exc_info:
                await TaskService._check_concurrency_limits("user_001")

            assert exc_info.value.code == "TASK_GLOBAL_CONCURRENCY_LIMIT"

    @pytest.mark.asyncio
    async def test_user_limit_exceeded(self):
        """Should reject when user running count >= limit."""
        with patch(
            "app.services.task_service.get_database"
        ) as mock_db:
            col = AsyncMock()

            def _count(q):
                if q.get("status") == "running" and not q.get("created_by"):
                    return 0  # global: OK
                if q.get("created_by") == "user_001":
                    return _USER_LIMIT  # user: at limit
                return 0

            col.count_documents = AsyncMock(side_effect=_count)
            mock_db.return_value.__getitem__.return_value = col

            from app.core.errors import ConflictError
            from app.services.task_service import TaskService

            with pytest.raises(ConflictError) as exc_info:
                await TaskService._check_concurrency_limits("user_001")

            assert exc_info.value.code == "TASK_USER_CONCURRENCY_LIMIT"

    @pytest.mark.asyncio
    async def test_system_bypasses_user_limit(self):
        """System/agent should not be subject to per-user limit."""
        with patch(
            "app.services.task_service.get_database"
        ) as mock_db:
            col = AsyncMock()
            col.count_documents = AsyncMock(return_value=0)
            mock_db.return_value.__getitem__.return_value = col

            from app.services.task_service import TaskService

            # Should not raise
            await TaskService._check_concurrency_limits("system")
            await TaskService._check_concurrency_limits("agent")

    @pytest.mark.asyncio
    async def test_under_limit_passes(self):
        """Should pass when under both limits."""
        with patch(
            "app.services.task_service.get_database"
        ) as mock_db:
            col = AsyncMock()
            col.count_documents = AsyncMock(return_value=0)
            mock_db.return_value.__getitem__.return_value = col

            from app.services.task_service import TaskService

            # Should not raise
            await TaskService._check_concurrency_limits("user_001")


class TestTransitionConcurrencyGuard:
    """transition_task concurrency check on pending → running."""

    @pytest.mark.asyncio
    async def test_pending_to_running_checks_limits(self):
        """Should call concurrency check on pending → running."""
        with (
            patch(
                "app.services.task_service.TaskService.get_task_or_404",
                return_value=_fake_task({"status": "pending"}),
            ),
            patch(
                "app.services.task_service.TaskService._check_concurrency_limits",
                new_callable=AsyncMock,
            ) as mock_check,
            patch(
                "app.services.task_service.TaskService._collection"
            ) as mock_col,
            patch(
                "app.services.task_service.TaskService._write_audit_log",
                new_callable=AsyncMock,
            ),
        ):
            mock_col.return_value.find_one_and_update = AsyncMock(
                return_value=_fake_task({"status": "running", "version": 2})
            )

            from app.services.task_service import TaskService

            await TaskService.transition_task(
                task_id="task_test_001",
                to_status=TaskStatus.RUNNING,
            )

            mock_check.assert_awaited_once_with("user_001", "manual")

    @pytest.mark.asyncio
    async def test_other_transitions_skip_concurrency(self):
        """Non pending→running transitions should skip concurrency check."""
        with (
            patch(
                "app.services.task_service.TaskService.get_task_or_404",
                return_value=_fake_task({"status": "pending"}),
            ),
            patch(
                "app.services.task_service.TaskService._check_concurrency_limits",
                new_callable=AsyncMock,
            ) as mock_check,
            patch(
                "app.services.task_service.TaskService._collection"
            ) as mock_col,
            patch(
                "app.services.task_service.TaskService._write_audit_log",
                new_callable=AsyncMock,
            ),
        ):
            mock_col.return_value.find_one_and_update = AsyncMock(
                return_value=_fake_task({"status": "cancelled", "version": 2})
            )

            from app.services.task_service import TaskService

            # pending → cancelled should NOT check concurrency
            await TaskService.transition_task(
                task_id="task_test_001",
                to_status=TaskStatus.CANCELLED,
            )

            mock_check.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_resume_cancelled_checks_concurrency(self):
        """cancelled → running (resume) SHOULD check concurrency limits."""
        with (
            patch(
                "app.services.task_service.TaskService.get_task_or_404",
                return_value=_fake_task({"status": "cancelled"}),
            ),
            patch(
                "app.services.task_service.TaskService._check_concurrency_limits",
                new_callable=AsyncMock,
            ) as mock_check,
            patch(
                "app.services.task_service.TaskService._collection"
            ) as mock_col,
            patch(
                "app.services.task_service.TaskService._write_audit_log",
                new_callable=AsyncMock,
            ),
        ):
            mock_col.return_value.find_one_and_update = AsyncMock(
                return_value=_fake_task({"status": "running", "version": 2})
            )

            from app.services.task_service import TaskService

            await TaskService.transition_task(
                task_id="task_test_001",
                to_status=TaskStatus.RUNNING,
            )

            mock_check.assert_awaited_once()


class TestFifoScheduling:
    """_schedule_next_pending — auto-start after terminal transition."""

    @pytest.mark.asyncio
    async def test_schedules_oldest_pending(self):
        """Should pick and start the oldest pending Task."""
        with (
            patch(
                "app.services.task_service.TaskService._collection"
            ) as mock_col,
            patch(
                "app.services.task_service.TaskService._write_audit_log",
                new_callable=AsyncMock,
            ),
            patch(
                "app.services.task_service.TaskService._audit_collection"
            ) as mock_audit,
        ):
            mock_audit.return_value.insert_one = AsyncMock()
            fake_updated = _fake_task({
                "status": "running",
                "version": 1,
                "_id": "task_oldest",
            })
            mock_col.return_value.find_one_and_update = AsyncMock(
                return_value=fake_updated
            )

            from app.services.task_service import TaskService

            result = await TaskService._schedule_next_pending()

            assert result is not None
            assert result["_id"] == "task_oldest"

    @pytest.mark.asyncio
    async def test_no_pending_returns_none(self):
        """Should return None when no pending Tasks exist."""
        with patch(
            "app.services.task_service.TaskService._collection"
        ) as mock_col:
            mock_col.return_value.find_one_and_update = AsyncMock(
                return_value=None
            )

            from app.services.task_service import TaskService

            result = await TaskService._schedule_next_pending()
            assert result is None

    @pytest.mark.asyncio
    async def test_running_to_terminal_triggers_schedule(self):
        """Running → completed should call schedule_next_pending."""
        with (
            patch(
                "app.services.task_service.TaskService.get_task_or_404",
                return_value=_fake_task({"status": "running", "version": 2}),
            ),
            patch(
                "app.services.task_service.TaskService._schedule_next_pending",
                new_callable=AsyncMock,
                return_value=_fake_task({"_id": "task_next", "status": "running"}),
            ) as mock_schedule,
            patch(
                "app.services.task_service.TaskService._collection"
            ) as mock_col,
            patch(
                "app.services.task_service.TaskService._write_audit_log",
                new_callable=AsyncMock,
            ),
        ):
            mock_col.return_value.find_one_and_update = AsyncMock(
                return_value=_fake_task({"status": "completed", "version": 3})
            )

            from app.services.task_service import TaskService

            await TaskService.transition_task(
                task_id="task_test_001",
                to_status=TaskStatus.COMPLETED,
            )

            mock_schedule.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_non_terminal_does_not_trigger_schedule(self):
        """Running → waiting_human should NOT trigger FIFO schedule."""
        with (
            patch(
                "app.services.task_service.TaskService.get_task_or_404",
                return_value=_fake_task({"status": "running", "version": 2}),
            ),
            patch(
                "app.services.task_service.TaskService._schedule_next_pending",
                new_callable=AsyncMock,
            ) as mock_schedule,
            patch(
                "app.services.task_service.TaskService._collection"
            ) as mock_col,
            patch(
                "app.services.task_service.TaskService._write_audit_log",
                new_callable=AsyncMock,
            ),
        ):
            mock_col.return_value.find_one_and_update = AsyncMock(
                return_value=_fake_task({"status": "waiting_human", "version": 3})
            )

            from app.services.task_service import TaskService

            await TaskService.transition_task(
                task_id="task_test_001",
                to_status=TaskStatus.WAITING_HUMAN,
            )

            mock_schedule.assert_not_awaited()


class TestStatsWithLimits:
    """get_stats should include limit info."""

    @pytest.mark.asyncio
    async def test_stats_includes_limits(self):
        """Should return limit fields."""
        with (
            patch("app.services.task_service.get_database") as mock_db,
        ):
            col = AsyncMock()
            col.count_documents = AsyncMock(return_value=0)
            # aggregate() returns an async cursor directly (not a coroutine) in Motor
            async_cursor = AsyncMock()
            async_cursor.to_list = AsyncMock(return_value=[])
            col.aggregate = MagicMock(return_value=async_cursor)
            mock_db.return_value.__getitem__.return_value = col

            from app.services.task_service import TaskService

            stats = await TaskService.get_stats()
            assert "global_max" in stats
            assert "user_limit" in stats
            assert stats["global_max"] == _GLOBAL_LIMIT
            assert stats["user_limit"] == _USER_LIMIT
