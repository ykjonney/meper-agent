"""Tests for TriggerSchedulerService — polling-based trigger scheduler.

Covers the polling/claim/fire design that replaced the Celery eta self-chain.
Key guarantees under test:
  * only due, enabled triggers fire
  * claim is atomic (optimistic lock on next_trigger_at) — concurrent
    claimants don't double-fire
  * next_trigger_at advances correctly (cron → next; once → None)
  * placeholder Task creation is race-safe via DuplicateKeyError handling
"""
from datetime import datetime, timedelta, timezone

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.trigger import Trigger
from app.services.trigger_scheduler_service import TriggerSchedulerService


def _async_iter(items):
    """Helper: async iterator over a list of items."""
    for item in items:
        yield item


def _mock_cursor(items):
    """Build a mock cursor whose to_list() resolves to the given items."""
    cursor = MagicMock()
    cursor.to_list = AsyncMock(return_value=list(items))
    return cursor


def _make_trigger(
    *,
    tid: str = "trig_1",
    workflow_id: str = "wf_1",
    type_: str = "cron",
    cron: str | None = "0 9 * * *",
    enabled: bool = True,
    next_trigger_at: datetime | None = None,
    execute_at: datetime | None = None,
) -> Trigger:
    return Trigger(
        _id=tid,
        workflow_id=workflow_id,
        user_id="user_1",
        type=type_,
        enabled=enabled,
        cron_expression=cron,
        execute_at=execute_at,
        next_trigger_at=next_trigger_at,
    )


def _make_due_doc(**kwargs) -> dict:
    """Build a trigger doc dict that is due (next_trigger_at in the past)."""
    past = datetime.now(timezone.utc) - timedelta(minutes=5)
    t = _make_trigger(next_trigger_at=past, **kwargs)
    return t.model_dump(by_alias=True)


class TestComputeNext:
    """Tests for _compute_next (pure schedule arithmetic)."""

    def test_cron_returns_next_firing(self) -> None:
        """cron trigger returns the next firing after now."""
        svc = TriggerSchedulerService()
        now = datetime(2026, 7, 9, 8, 0, tzinfo=timezone.utc).astimezone()
        t = _make_trigger(cron="0 9 * * *")
        nxt = svc._compute_next(t, now)
        assert nxt is not None
        # next 09:00 local
        assert nxt.hour == 9

    def test_once_returns_none(self) -> None:
        """once triggers do not repeat."""
        svc = TriggerSchedulerService()
        now = datetime.now(timezone.utc).astimezone()
        t = _make_trigger(type_="once", cron=None, execute_at=now + timedelta(days=1))
        assert svc._compute_next(t, now) is None

    def test_cron_missing_expression_returns_none(self) -> None:
        svc = TriggerSchedulerService()
        now = datetime.now(timezone.utc).astimezone()
        t = _make_trigger(cron=None)
        assert svc._compute_next(t, now) is None


class TestProcessDueTriggers:
    """Tests for _process_due_triggers (the poll cycle)."""

    @patch("app.services.trigger_scheduler_service.TriggerSchedulerService._fire", new_callable=AsyncMock)
    async def test_disabled_trigger_not_fired(self, mock_fire) -> None:
        """Disabled triggers should never be selected by the query."""
        svc = TriggerSchedulerService()
        # Query filters enabled=True, so we simulate the DB returning nothing
        # for a disabled trigger by returning an empty cursor.
        mock_col = MagicMock()
        mock_col.find = MagicMock(return_value=_mock_cursor([]))
        mock_repo = MagicMock()
        mock_repo._collection.return_value = mock_col
        svc._repo = mock_repo

        fired = await svc._process_due_triggers()
        assert fired == 0
        mock_fire.assert_not_awaited()

    @patch("app.services.trigger_scheduler_service.TriggerSchedulerService._fire", new_callable=AsyncMock)
    async def test_due_cron_trigger_fires_and_advances(self, mock_fire) -> None:
        """A due cron trigger is claimed, fired, and next_trigger_at advanced."""
        past = datetime.now(timezone.utc) - timedelta(minutes=5)
        doc = _make_trigger(next_trigger_at=past).model_dump(by_alias=True)

        mock_col = MagicMock()
        mock_col.find = MagicMock(return_value=_mock_cursor([doc]))
        # claim succeeds: find_one_and_update returns the updated doc
        mock_col.find_one_and_update = AsyncMock(return_value={**doc, "next_trigger_at": datetime.now(timezone.utc) + timedelta(hours=1)})
        mock_repo = MagicMock()
        mock_repo._collection.return_value = mock_col
        svc = TriggerSchedulerService()
        svc._repo = mock_repo

        fired = await svc._process_due_triggers()
        assert fired == 1
        mock_fire.assert_awaited_once()

    async def test_claim_lost_returns_false(self) -> None:
        """When find_one_and_update returns None, the claim was lost (race)."""
        svc = TriggerSchedulerService()
        past = datetime.now(timezone.utc) - timedelta(minutes=5)
        t = _make_trigger(next_trigger_at=past)

        mock_col = MagicMock()
        # Another process already advanced next_trigger_at → None
        mock_col.find_one_and_update = AsyncMock(return_value=None)
        mock_repo = MagicMock()
        mock_repo._collection.return_value = mock_col
        svc._repo = mock_repo

        with patch.object(svc, "_fire", new_callable=AsyncMock) as mock_fire:
            won = await svc._claim_and_fire(t, datetime.now(timezone.utc).astimezone())
        assert won is False
        mock_fire.assert_not_awaited()

    @patch("app.services.trigger_scheduler_service.TriggerSchedulerService._fire", new_callable=AsyncMock)
    async def test_once_trigger_clears_next_trigger_at(self, mock_fire) -> None:
        """once trigger claim uses $unset on next_trigger_at."""
        past = datetime.now(timezone.utc) - timedelta(minutes=5)
        t = _make_trigger(type_="once", cron=None, execute_at=past, next_trigger_at=past)

        mock_col = MagicMock()
        mock_col.find_one_and_update = AsyncMock(return_value={"_id": t.id})
        mock_repo = MagicMock()
        mock_repo._collection.return_value = mock_col
        svc = TriggerSchedulerService()
        svc._repo = mock_repo

        won = await svc._claim_and_fire(t, datetime.now(timezone.utc).astimezone())
        assert won is True
        # Verify the update used $unset for the once branch
        call_args = mock_col.find_one_and_update.call_args
        assert "$unset" in call_args.kwargs.get("update", call_args.args[1])


class TestCreatePlaceholderTask:
    """Tests for _create_placeholder_task race-safety."""

    @patch("app.db.mongodb.get_database")
    @patch("app.utils.template_renderer.render_default_input")
    @patch("app.services.task_service.TaskService")
    async def test_duplicate_key_reuses_existing(
        self, mock_task_service, mock_render, mock_get_db
    ) -> None:
        """DuplicateKeyError → reuse the existing placeholder."""
        from pymongo.errors import DuplicateKeyError

        mock_render.return_value = {}
        mock_task_service.create_task = AsyncMock(side_effect=DuplicateKeyError("dup"))

        existing_id = "task_existing"
        mock_col = MagicMock()
        mock_col.find_one = AsyncMock(return_value={"_id": existing_id})
        mock_col.update_one = AsyncMock()
        mock_db = MagicMock()
        mock_db.__getitem__.return_value = mock_col
        mock_get_db.return_value = mock_db

        svc = TriggerSchedulerService()
        t = _make_trigger()
        fire_at = datetime.now(timezone.utc)

        # Should not raise — reuses existing placeholder instead
        await svc._create_placeholder_task(t, fire_at)

        mock_col.update_one.assert_awaited_once()
        mock_task_service.create_task.assert_awaited_once()

    @patch("app.utils.template_renderer.render_default_input")
    @patch("app.services.task_service.TaskService")
    async def test_normal_insert_creates_placeholder(
        self, mock_task_service, mock_render
    ) -> None:
        """No conflict → create_task is called normally."""
        mock_render.return_value = {}
        mock_task_service.create_task = AsyncMock(return_value={"_id": "task_new"})

        svc = TriggerSchedulerService()
        t = _make_trigger()
        fire_at = datetime.now(timezone.utc)

        await svc._create_placeholder_task(t, fire_at)

        mock_task_service.create_task.assert_awaited_once()
        # Verify source=trigger so it enters the partial unique index
        _, kwargs = mock_task_service.create_task.call_args
        assert kwargs["source"] == "trigger"
        assert kwargs["trigger_id"] == t.id


class TestLifecycle:
    """Tests for start/stop lifecycle."""

    async def test_start_stop_sets_running_flag(self) -> None:
        svc = TriggerSchedulerService()
        # Avoid real poll loop interactions
        with patch.object(svc, "_backfill_next_trigger_at", new_callable=AsyncMock):
            with patch("app.services.trigger_scheduler_service.settings") as mock_settings:
                mock_settings.TRIGGER_SCHEDULER_POLL_INTERVAL = 0  # disables loop
                await svc.start()
                # poll_interval <= 0 → loop returns immediately
                assert svc._task is not None
                await svc.stop()
        assert not svc.is_running

    async def test_start_idempotent(self) -> None:
        svc = TriggerSchedulerService()
        with patch.object(svc, "_backfill_next_trigger_at", new_callable=AsyncMock):
            with patch("app.services.trigger_scheduler_service.settings") as mock_settings:
                mock_settings.TRIGGER_SCHEDULER_POLL_INTERVAL = 0
                await svc.start()
                first_task = svc._task
                await svc.start()  # no-op
                assert svc._task is first_task
        await svc.stop()
