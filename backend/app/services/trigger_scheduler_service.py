"""Trigger scheduler service — polls for due triggers and fires them.

Design (polling-based, replaces the previous Celery eta self-chain):
    A background asyncio loop polls the ``triggers`` collection every
    ``TRIGGER_SCHEDULER_POLL_INTERVAL`` seconds for triggers whose
    ``next_trigger_at <= now``. For each due trigger it:

      1. Atomically claims the trigger via ``find_one_and_update`` with an
         optimistic-lock filter on the *current* ``next_trigger_at``. Only
         one process wins the claim; losers get ``None`` and skip.
      2. Computes the *next* firing time and writes it back as the new
         ``next_trigger_at`` (so the poll loop picks it up next cycle).
      3. Creates / reuses the placeholder Task for this firing.
      4. Dispatches an *immediate* Celery task (no eta) to execute it.

Why not Celery eta?
    Redis broker re-delivers unacked messages after ``visibility_timeout``.
    For long-eta jobs (e.g. monthly cron, eta ≈ 30 days) the eta message
    is cycled "consumed → restored → consumed" every visibility_timeout
    (default 7 days here), and combined with ``task_acks_late`` this can
    cause duplicate executions and duplicate placeholder creation. Polling
    keeps no broker state for future firings, so the problem disappears.

DB-level guard:
    A partial unique index (see ``TriggerRepository.ensure_indexes``) on
    ``tasks`` ensures at most one pending placeholder per trigger, so even
    if two pollers race past the claim, only one placeholder is inserted.
"""
from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime

from croniter import croniter
from loguru import logger

from app.core.config import settings
from app.models.trigger import Trigger
from app.services.trigger_repo import TriggerRepository


class TriggerSchedulerService:
    """Polling-based scheduler for cron/once triggers."""

    def __init__(self, repo: TriggerRepository | None = None) -> None:
        self._repo: TriggerRepository | None = repo
        self._task: asyncio.Task | None = None
        self._stopped: bool = False

    @property
    def repo(self) -> TriggerRepository:
        if self._repo is None:
            raise RuntimeError("TriggerSchedulerService not initialized — repo is None")
        return self._repo

    def set_repo(self, repo: TriggerRepository) -> None:
        """Set the repository (called during startup)."""
        self._repo = repo

    @property
    def is_running(self) -> bool:
        """Whether the poll loop is currently active."""
        return self._task is not None and not self._task.done()

    # ── Lifecycle ──

    async def start(self) -> None:
        """Start the scheduler: backfill missing next_trigger_at, then poll.

        On startup we compute ``next_trigger_at`` for any enabled trigger
        that is missing one (e.g. legacy data, or newly created). This is
        pure DB bookkeeping — no Celery dispatch — the poll loop takes over
        from there.
        """
        if self.is_running:
            logger.warning("trigger_scheduler_already_running")
            return

        # Backfill: ensure every enabled trigger has a next_trigger_at.
        try:
            await self._backfill_next_trigger_at()
        except Exception as exc:
            logger.error("trigger_scheduler_backfill_failed", error=str(exc))

        self._stopped = False
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("trigger_scheduler_started")

    async def stop(self) -> None:
        """Stop the scheduler gracefully."""
        self._stopped = True
        if self._task is not None and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        self._task = None
        logger.info("trigger_scheduler_stopped")

    # ── Poll loop ──

    async def _poll_loop(self) -> None:
        """Main poll loop — runs until stopped."""
        poll_interval = settings.TRIGGER_SCHEDULER_POLL_INTERVAL
        if poll_interval <= 0:
            logger.info("trigger_scheduler_disabled_by_config")
            return

        logger.info(
            "trigger_scheduler_poll_loop_started",
            poll_interval_s=poll_interval,
        )

        while not self._stopped:
            try:
                await self._process_due_triggers()
            except Exception as exc:
                logger.error("trigger_scheduler_poll_error", error=str(exc))

            await asyncio.sleep(poll_interval)

        logger.info("trigger_scheduler_poll_loop_ended")

    async def _process_due_triggers(self) -> int:
        """Find and fire all due triggers.

        For each due trigger: atomically claim it (optimistic lock on
        next_trigger_at), advance next_trigger_at to the *next* firing,
        then create the placeholder Task + dispatch immediate execution.

        Returns:
            Number of triggers successfully fired this cycle.
        """
        now = datetime.now().astimezone()

        # Find due enabled triggers. type=cron keeps next_trigger_at;
        # type=once fires once and next_trigger_at becomes None.
        cursor = self.repo._collection().find(
            {
                "enabled": True,
                "next_trigger_at": {"$lte": now},
            }
        )
        due = await cursor.to_list(length=100)
        if not due:
            return 0

        fired = 0
        for doc in due:
            trigger = Trigger(**doc)
            try:
                if await self._claim_and_fire(trigger, now):
                    fired += 1
            except Exception as exc:
                logger.error(
                    "trigger_fire_error",
                    trigger_id=trigger.id,
                    error=str(exc),
                )
        return fired

    async def _claim_and_fire(self, trigger: Trigger, now: datetime) -> bool:
        """Atomically claim a trigger and fire it.

        Optimistic lock: the update only succeeds if next_trigger_at is
        still the value we read. If another process already advanced it,
        ``find_one_and_update`` returns None and we skip.

        Returns True if this caller won the claim and fired the trigger.
        """
        old_next = trigger.next_trigger_at

        # Compute the NEXT firing time (after the current due one).
        new_next = self._compute_next(trigger, now)

        # Atomic claim: advance next_trigger_at + mark last_triggered_at.
        # The filter on next_trigger_at == old_next guarantees only one
        # concurrent caller wins.
        update_set: dict = {"last_triggered_at": now}
        if new_next is not None:
            update_set["next_trigger_at"] = new_next
        else:
            # once-type trigger fired: clear next_trigger_at so it never
            # fires again. Use $unset to fully remove the field.
            claimed = await self.repo._collection().find_one_and_update(
                {"_id": trigger.id, "next_trigger_at": old_next},
                {
                    "$set": update_set,
                    "$unset": {"next_trigger_at": ""},
                },
                return_document=True,
            )
            if claimed is None:
                logger.debug("trigger_claim_lost", trigger_id=trigger.id)
                return False
            # Reflect the cleared state on the in-memory object for firing.
            trigger.next_trigger_at = None
            await self._fire(trigger, old_next)
            logger.info("trigger_fired", trigger_id=trigger.id, kind="once")
            return True

        claimed = await self.repo._collection().find_one_and_update(
            {"_id": trigger.id, "next_trigger_at": old_next},
            {"$set": update_set},
            return_document=True,
        )
        if claimed is None:
            logger.debug("trigger_claim_lost", trigger_id=trigger.id)
            return False

        # Reflect the advanced state on the in-memory object for firing.
        trigger.next_trigger_at = new_next

        # Dispatch execution of the *current* firing. The pending placeholder
        # for this firing was pre-created in the previous cycle (or by the
        # API on create/update). We do NOT create a new one here — _fire
        # just dispatches Celery to consume the existing pending placeholder.
        await self._fire(trigger, old_next)

        # Pre-create the placeholder Task for the NEXT firing (new_next).
        # This must happen AFTER _fire dispatches, but the current placeholder
        # may still be pending (Celery hasn't transitioned it to running yet).
        # That's fine: _create_placeholder_task catches DuplicateKeyError and
        # reuses the existing one, updating its scheduled_at to new_next.
        # When Celery picks it up, execute_scheduled_workflow finds the pending
        # placeholder (regardless of scheduled_at) and runs it. After it
        # transitions to running/completed, the index slot frees up and the
        # next cycle's pre-create inserts a fresh one.
        if new_next is not None:
            await self._create_placeholder_task(trigger, new_next)

        logger.info(
            "trigger_fired",
            trigger_id=trigger.id,
            kind="cron",
            next_at=new_next.isoformat(),
        )
        return True

    async def _fire(self, trigger: Trigger, fire_at: datetime) -> None:
        """Dispatch immediate Celery execution for this trigger's current firing.

        The pending placeholder Task should already exist (pre-created in the
        previous poll cycle, or by the API). If it doesn't (e.g. first-ever
        firing with no pre-created placeholder), create one on the fly.
        """
        from app.db.mongodb import get_database

        # Ensure a pending placeholder exists for this firing.
        db = get_database()
        existing = await db["tasks"].find_one(
            {"trigger_id": trigger.id, "status": "pending", "source": "trigger"},
            {"_id": 1},
        )
        if existing is None:
            await self._create_placeholder_task(trigger, fire_at)

        # Dispatch immediate Celery execution (no eta → no visibility_timeout
        # re-delivery risk for long schedules).
        if trigger.enabled:
            from app.workers.tasks.scheduled_workflow import execute_scheduled_workflow

            result = execute_scheduled_workflow.apply_async(args=[trigger.id])
            await self.repo.update(trigger.id, celery_task_id=result.id)

    # ── Placeholder Task creation (race-safe via DB index) ──

    async def _create_placeholder_task(
        self,
        trigger: Trigger,
        fire_at: datetime,
    ) -> None:
        """Create a placeholder Task for this firing.

        Race safety: the partial unique index on tasks
        (trigger_id unique where source=trigger & status=pending) makes the
        insert atomic. If a concurrent caller already inserted one, we catch
        ``DuplicateKeyError`` and reuse the existing placeholder.
        """
        from pymongo.errors import DuplicateKeyError

        from app.services.task_service import TaskService
        from app.utils.template_renderer import render_default_input

        rendered_input = render_default_input(trigger.default_input)
        try:
            await TaskService.create_task(
                workflow_id=trigger.workflow_id,
                input_data=rendered_input,
                created_by=trigger.user_id,
                created_by_type="system",
                scheduled_at=fire_at,
                skip_execution=True,
                source="trigger",
                trigger_id=trigger.id,
            )
            logger.info(
                "trigger_placeholder_created",
                trigger_id=trigger.id,
                scheduled_at=fire_at.isoformat(),
            )
        except DuplicateKeyError:
            # Another process won the race — reuse their placeholder by
            # updating its scheduled_at for display consistency.
            from app.db.mongodb import get_database
            from app.models.base import utc_now

            db = get_database()
            existing = await db["tasks"].find_one(
                {"trigger_id": trigger.id, "status": "pending", "source": "trigger"},
                {"_id": 1},
            )
            if existing is not None:
                await db["tasks"].update_one(
                    {"_id": existing["_id"]},
                    {"$set": {"scheduled_at": fire_at, "updated_at": utc_now()}},
                )
            logger.debug(
                "trigger_placeholder_already_exists_reused",
                trigger_id=trigger.id,
            )

    # ── Schedule computation ──

    def _compute_next(self, trigger: Trigger, now: datetime) -> datetime | None:
        """Compute the next firing time AFTER ``now`` for a trigger.

        Returns None for once-type triggers (they fire only once) or when
        the cron expression / execute_at is missing.
        """
        if trigger.type == "cron":
            cron_expr = trigger.cron_expression or ""
            if not cron_expr:
                return None
            cron = croniter(cron_expr, now)
            next_at = cron.get_next(datetime)
            if next_at.tzinfo is None:
                next_at = next_at.astimezone()
            return next_at
        elif trigger.type == "once":
            # once triggers do not repeat
            return None
        return None

    # ── Backfill ──

    async def _backfill_next_trigger_at(self) -> None:
        """Ensure every enabled trigger has a next_trigger_at.

        Handles triggers created before the polling scheduler existed, or
        ones whose next_trigger_at was cleared. Disabled triggers are left
        alone.
        """
        now = datetime.now().astimezone()
        cursor = self.repo._collection().find({"enabled": True})
        async for doc in cursor:
            if doc.get("next_trigger_at") is not None:
                continue
            trigger = Trigger(**doc)
            # For once-type, honor execute_at if it's still in the future.
            if trigger.type == "once" and trigger.execute_at:
                execute_at = trigger.execute_at
                if isinstance(execute_at, str):
                    execute_at = datetime.fromisoformat(execute_at)
                if execute_at.tzinfo is None:
                    execute_at = execute_at.astimezone()
                if execute_at > now:
                    await self.repo.update(trigger.id, next_trigger_at=execute_at)
                # past execute_at → leave None (won't fire)
                continue
            next_at = self._compute_next(trigger, now)
            if next_at is not None:
                await self.repo.update(trigger.id, next_trigger_at=next_at)
                logger.info(
                    "trigger_backfilled_next_trigger_at",
                    trigger_id=trigger.id,
                    next_at=next_at.isoformat(),
                )


# Module-level singleton
_scheduler: TriggerSchedulerService | None = None


def get_trigger_scheduler() -> TriggerSchedulerService:
    """Get the trigger scheduler singleton."""
    global _scheduler
    if _scheduler is None:
        _scheduler = TriggerSchedulerService()
    return _scheduler
