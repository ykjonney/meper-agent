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
      3. Dispatches an *immediate* Celery task (no eta) to execute it.

No placeholder tasks:
    The trigger document is the sole management entity (shown in the task
    board's "scheduled tasks" column). Each firing forks a fresh execution
    Task (source="trigger_scheduled") from the trigger via
    ``execute_scheduled_workflow``. There are no persistent pending
    placeholder tasks.

Why not Celery eta?
    Redis broker re-delivers unacked messages after ``visibility_timeout``.
    For long-eta jobs (e.g. monthly cron, eta ≈ 30 days) the eta message
    is cycled "consumed → restored → consumed" every visibility_timeout,
    causing duplicate executions. Polling keeps no broker state for future
    firings, so the problem disappears.
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

        # Fire the current firing: create the placeholder Task + dispatch
        # immediate Celery execution. The placeholder is transient — it
        # exists only from creation until the engine transitions it to
        # running→completed. We do NOT pre-create a placeholder for the
        # NEXT firing; trigger.next_trigger_at serves that purpose (it was
        # already advanced above). This avoids the impossible problem of
        # needing two pending placeholders for one trigger at once.
        await self._fire(trigger, old_next)

        logger.info(
            "trigger_fired",
            trigger_id=trigger.id,
            kind="cron",
            next_at=new_next.isoformat() if new_next else None,
        )
        return True

    async def _fire(self, trigger: Trigger, fire_at: datetime) -> None:
        """Dispatch immediate Celery execution for this trigger.

        No placeholder task is involved — the trigger document is the sole
        management entity. Celery forks a fresh execution Task from the
        trigger at execution time (see scheduled_workflow._execute_async).
        """
        if trigger.enabled:
            from app.workers.tasks.scheduled_workflow import execute_scheduled_workflow

            result = execute_scheduled_workflow.apply_async(args=[trigger.id])
            await self.repo.update(trigger.id, celery_task_id=result.id)

    # ── Schedule computation ──

    def _compute_next(self, trigger: Trigger, now: datetime) -> datetime | None:
        """Compute the next firing time AFTER ``now`` for a trigger.

        - cron: uses croniter to find the next match after now.
        - once: returns execute_at if it's still in the future; None if it
          has already passed (the trigger already fired or is stale).
        - Returns None when the cron expression / execute_at is missing.
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
            execute_at = trigger.execute_at
            if not execute_at:
                return None
            if isinstance(execute_at, str):
                execute_at = datetime.fromisoformat(execute_at)
            if execute_at.tzinfo is None:
                execute_at = execute_at.astimezone()
            # Only schedule if execute_at is still in the future.
            # A past execute_at means the one-time window has passed.
            if execute_at > now:
                return execute_at
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
            # _compute_next handles both cron and once (returns execute_at
            # if still in the future, None if past).
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
