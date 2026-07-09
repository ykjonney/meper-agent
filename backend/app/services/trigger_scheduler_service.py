"""Trigger scheduler service — bridges cron expressions to Celery eta tasks.

Refactored: operates on independent Trigger documents (triggers collection)
instead of embedded trigger_config in workflows collection.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from croniter import croniter
from loguru import logger

from app.models.trigger import Trigger
from app.services.trigger_repo import TriggerRepository


class TriggerSchedulerService:
    """Scheduled trigger scheduler service.

    Uses Celery `apply_async(eta=...)` for precise scheduling.
    No in-memory state — all config is read from MongoDB via TriggerRepository.
    """

    def __init__(self, repo: TriggerRepository | None = None) -> None:
        self._repo: TriggerRepository | None = repo
        self._started: bool = False

    @property
    def repo(self) -> TriggerRepository:
        if self._repo is None:
            raise RuntimeError("TriggerSchedulerService not initialized — repo is None")
        return self._repo

    def set_repo(self, repo: TriggerRepository) -> None:
        """Set the repository (called during startup)."""
        self._repo = repo

    async def start(self) -> None:
        """Initialize scheduler on service startup.

        Re-sends Celery messages for all enabled triggers to ensure
        the scheduling chain survives queue loss (e.g., Redis restart).
        Idempotency is guaranteed by the worker's Task status check:
        if a Task has already been executed, the stale message will
        find no pending placeholder and skip.
        """
        if self._started:
            logger.warning("trigger_scheduler_already_started")
            return

        self._started = True
        logger.info("trigger_scheduler_started")

        # Re-send Celery messages for all enabled triggers
        triggers = await self.repo.find_enabled()

        for trigger in triggers:
            await self.schedule_next(trigger.id, send_celery=True)

        logger.info("trigger_scheduler_rescheduled", count=len(triggers))

    async def stop(self) -> None:
        """Stop the scheduler."""
        self._started = False
        logger.info("trigger_scheduler_stopped")

    async def schedule_next(
        self, trigger_id: str, send_celery: bool = True, *, exclude_task_id: str | None = None
    ) -> datetime | None:
        """Compute next trigger time, create/update placeholder Task, optionally send Celery.

        Args:
            trigger_id: Trigger ID.
            send_celery: Whether to dispatch Celery task. Set False for disabled triggers
                         where we only want to create the placeholder Task for visibility.
            exclude_task_id: Task ID to exclude from the "existing pending" check.
                             Used during self-chain so the currently-executing placeholder
                             isn't mistaken for the *next* one.

        Returns the scheduled time, or None if nothing should be scheduled.
        """
        trigger = await self.repo.find_by_id(trigger_id)
        if not trigger:
            return None

        # Use local timezone so cron expressions match user expectation
        # (e.g. "0 9 * * *" means 09:00 local time, not 09:00 UTC)
        now = datetime.now().astimezone()

        if trigger.type == "cron":
            cron_expr = trigger.cron_expression or ""
            if not cron_expr:
                return None
            cron = croniter(cron_expr, now)
            next_at = cron.get_next(datetime)
            # Preserve local timezone from croniter
            if next_at.tzinfo is None:
                next_at = next_at.astimezone()
        elif trigger.type == "once":
            execute_at = trigger.execute_at
            if not execute_at:
                return None
            next_at = (
                execute_at
                if isinstance(execute_at, datetime)
                else datetime.fromisoformat(str(execute_at))
            )
            # Timezone handling:
            # - Frontend sends ISO format with offset (e.g. "2026-07-08T15:30:00+08:00")
            #   → Pydantic parses as aware datetime → no conversion needed
            # - Legacy naive datetimes (no tzinfo) are treated as local time
            if next_at.tzinfo is None:
                next_at = next_at.astimezone()
            # Skip if already past
            if next_at <= now:
                return None
        else:
            return None

        # Create or update placeholder Task (always, for visibility)
        await self._create_placeholder_task(trigger, next_at, exclude_task_id=exclude_task_id)

        # Dispatch Celery task only if requested (i.e., trigger is enabled)
        # Always send on startup — the worker's schedule_version check ensures
        # stale duplicates are safely skipped. This guarantees the scheduling
        # chain survives queue loss (Redis restart, message expiry, etc.)
        celery_task_id = None
        if send_celery and trigger.enabled:
            from app.workers.tasks.scheduled_workflow import execute_scheduled_workflow

            result = execute_scheduled_workflow.apply_async(
                args=[trigger_id, trigger.schedule_version],
                eta=next_at,
                expires=next_at + timedelta(hours=1),
            )
            celery_task_id = result.id

        # Persist next_trigger_at + Celery task ID
        await self.repo.update(
            trigger_id,
            next_trigger_at=next_at,
            celery_task_id=celery_task_id,
        )

        logger.info(
            "trigger_scheduled",
            trigger_id=trigger_id,
            next_at=next_at.isoformat(),
            send_celery=send_celery and trigger.enabled,
        )
        return next_at

    async def _create_placeholder_task(
        self,
        trigger: Trigger,
        next_at: datetime,
        *,
        exclude_task_id: str | None = None,
    ) -> None:
        """Create a placeholder Task for the next scheduled execution.

        Skips if a pending placeholder already exists for this trigger
        (e.g. on service restart when start() re-schedules all triggers).
        """
        from app.db.mongodb import get_database
        from app.services.task_service import TaskService
        from app.utils.template_renderer import render_default_input

        db = get_database()
        query: dict = {"trigger_id": trigger.id, "status": "pending", "source": "trigger"}
        if exclude_task_id is not None:
            query["_id"] = {"$ne": exclude_task_id}
        existing = await db["tasks"].find_one(query, {"_id": 1})
        if existing is not None:
            # Update scheduled_at to match the new next_at so the task
            # list shows the correct scheduled time.
            from app.models.base import utc_now

            await db["tasks"].update_one(
                {"_id": existing["_id"]},
                {"$set": {"scheduled_at": next_at, "updated_at": utc_now()}},
            )
            logger.debug(
                "trigger_placeholder_already_exists_updated",
                trigger_id=trigger.id,
                new_scheduled_at=next_at.isoformat(),
            )
            return

        rendered_input = render_default_input(trigger.default_input)
        await TaskService.create_task(
            workflow_id=trigger.workflow_id,
            input_data=rendered_input,
            created_by=trigger.user_id,
            created_by_type="system",
            scheduled_at=next_at,
            skip_execution=True,
            source="trigger",
            trigger_id=trigger.id,
        )
        logger.info(
            "trigger_placeholder_created",
            trigger_id=trigger.id,
            scheduled_at=next_at.isoformat(),
        )


# Module-level singleton
_scheduler: TriggerSchedulerService | None = None


def get_trigger_scheduler() -> TriggerSchedulerService:
    """Get the trigger scheduler singleton."""
    global _scheduler
    if _scheduler is None:
        _scheduler = TriggerSchedulerService()
    return _scheduler
