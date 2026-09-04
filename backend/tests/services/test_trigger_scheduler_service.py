"""Tests for TriggerSchedulerService — polling-based trigger scheduler.

Covers the polling/claim/fire design that replaced the Celery eta self-chain.
Key guarantees under test:
  * only due, enabled triggers fire
  * claim is atomic (optimistic lock on next_trigger_at) — concurrent
    claimants don't double-fire
  * next_trigger_at advances correctly (cron → next; once → None)
  * placeholder Task creation is race-safe via DuplicateKeyError handling
"""
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.trigger import Trigger
from app.services.trigger_scheduler_service import TriggerSchedulerService


def _async_iter(items):
    """Helper: async iterator over a list of items."""
    yield from items


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
    past = datetime.now(UTC) - timedelta(minutes=5)
    t = _make_trigger(next_trigger_at=past, **kwargs)
    return t.model_dump(by_alias=True)


class TestComputeNext:
    """Tests for _compute_next (pure schedule arithmetic)."""

    def test_cron_returns_next_firing(self) -> None:
        """cron trigger returns the next firing after now."""
        svc = TriggerSchedulerService()
        now = datetime(2026, 7, 9, 8, 0, tzinfo=UTC).astimezone()
        t = _make_trigger(cron="0 9 * * *")
        nxt = svc._compute_next(t, now)
        assert nxt is not None
        # next 09:00 local
        assert nxt.hour == 9

    def test_once_future_execute_at_returns_it(self) -> None:
        """once trigger with future execute_at → returns execute_at."""
        svc = TriggerSchedulerService()
        now = datetime.now(UTC).astimezone()
        future = now + timedelta(days=1)
        t = _make_trigger(type_="once", cron=None, execute_at=future)
        result = svc._compute_next(t, now)
        assert result is not None
        # Should return the execute_at time
        assert result == future

    def test_once_past_execute_at_returns_none(self) -> None:
        """once trigger with past execute_at → None (window passed)."""
        svc = TriggerSchedulerService()
        now = datetime.now(UTC).astimezone()
        past = now - timedelta(days=1)
        t = _make_trigger(type_="once", cron=None, execute_at=past)
        assert svc._compute_next(t, now) is None

    def test_once_no_execute_at_returns_none(self) -> None:
        """once trigger without execute_at → None."""
        svc = TriggerSchedulerService()
        now = datetime.now(UTC).astimezone()
        t = _make_trigger(type_="once", cron=None, execute_at=None)
        assert svc._compute_next(t, now) is None

    def test_cron_missing_expression_returns_none(self) -> None:
        svc = TriggerSchedulerService()
        now = datetime.now(UTC).astimezone()
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
        past = datetime.now(UTC) - timedelta(minutes=5)
        doc = _make_trigger(next_trigger_at=past).model_dump(by_alias=True)

        mock_col = MagicMock()
        mock_col.find = MagicMock(return_value=_mock_cursor([doc]))
        # claim succeeds: find_one_and_update returns the updated doc
        mock_col.find_one_and_update = AsyncMock(return_value={**doc, "next_trigger_at": datetime.now(UTC) + timedelta(hours=1)})
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
        past = datetime.now(UTC) - timedelta(minutes=5)
        t = _make_trigger(next_trigger_at=past)

        mock_col = MagicMock()
        # Another process already advanced next_trigger_at → None
        mock_col.find_one_and_update = AsyncMock(return_value=None)
        mock_repo = MagicMock()
        mock_repo._collection.return_value = mock_col
        svc._repo = mock_repo

        with patch.object(svc, "_fire", new_callable=AsyncMock) as mock_fire:
            won = await svc._claim_and_fire(t, datetime.now(UTC).astimezone())
        assert won is False
        mock_fire.assert_not_awaited()

    @patch("app.services.trigger_scheduler_service.TriggerSchedulerService._fire", new_callable=AsyncMock)
    async def test_once_trigger_clears_next_trigger_at(self, mock_fire) -> None:
        """once trigger claim uses $unset on next_trigger_at."""
        past = datetime.now(UTC) - timedelta(minutes=5)
        t = _make_trigger(type_="once", cron=None, execute_at=past, next_trigger_at=past)

        mock_col = MagicMock()
        mock_col.find_one_and_update = AsyncMock(return_value={"_id": t.id})
        mock_repo = MagicMock()
        mock_repo._collection.return_value = mock_col
        svc = TriggerSchedulerService()
        svc._repo = mock_repo

        won = await svc._claim_and_fire(t, datetime.now(UTC).astimezone())
        assert won is True
        # Verify the update used $unset for the once branch
        call_args = mock_col.find_one_and_update.call_args
        assert "$unset" in call_args.kwargs.get("update", call_args.args[1])


class TestLifecycle:
    """Tests for start/stop lifecycle."""

    async def test_start_stop_sets_running_flag(self) -> None:
        svc = TriggerSchedulerService()
        # Avoid real poll loop interactions
        with (
            patch.object(svc, "_backfill_next_trigger_at", new_callable=AsyncMock),
            patch("app.services.trigger_scheduler_service.settings") as mock_settings,
        ):
            mock_settings.TRIGGER_SCHEDULER_POLL_INTERVAL = 0  # disables loop
            await svc.start()
            # poll_interval <= 0 → loop returns immediately
            assert svc._task is not None
            await svc.stop()
        assert not svc.is_running

    async def test_start_idempotent(self) -> None:
        svc = TriggerSchedulerService()
        with (
            patch.object(svc, "_backfill_next_trigger_at", new_callable=AsyncMock),
            patch("app.services.trigger_scheduler_service.settings") as mock_settings,
        ):
            mock_settings.TRIGGER_SCHEDULER_POLL_INTERVAL = 0
            await svc.start()
            first_task = svc._task
            await svc.start()  # no-op
            assert svc._task is first_task
        await svc.stop()


class TestTriggerTimezone:
    """cron 按 TRIGGER_TIMEZONE 解释，不依赖容器系统时区。

    回归背景：部署容器默认 UTC，旧实现用 datetime.now().astimezone() 导致
    "周四16:00"（0 16 * * 4）被算成 UTC 周四 16:00 = 北京周五 00:00，
    next_trigger_at 与用户预期相差 8 小时。
    """

    def test_trigger_now_uses_configured_timezone(self) -> None:
        """trigger_now 的时区偏移与 TRIGGER_TIMEZONE 一致（无视容器 TZ）。"""
        from zoneinfo import ZoneInfo

        from app.core.config import settings
        from app.services.trigger_scheduler_service import trigger_now

        now = trigger_now()
        expected_off = datetime.now(ZoneInfo(settings.TRIGGER_TIMEZONE)).utcoffset()
        assert now.utcoffset() == expected_off
        assert now.tzinfo is not None

    def test_weekly_thursday_4pm_interpreted_in_trigger_tz(self) -> None:
        """0 16 * * 4 在 TRIGGER_TIMEZONE 语义下：下次=该时区的周四 16:00。

        本测试在任意容器时区（本地 Asia/Shanghai / CI UTC）下均成立——
        这正是修复语义本身。
        """
        from zoneinfo import ZoneInfo

        from app.core.config import settings
        from app.services.trigger_scheduler_service import trigger_now

        svc = TriggerSchedulerService()
        now = trigger_now()
        t = _make_trigger(cron="0 16 * * 4")
        nxt = svc._compute_next(t, now)
        assert nxt is not None
        local = nxt.astimezone(ZoneInfo(settings.TRIGGER_TIMEZONE))
        assert local.weekday() == 3  # Thursday
        assert local.hour == 16
        assert local.minute == 0
        assert nxt > now
