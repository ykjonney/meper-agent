"""TaskSchedulerService — background scheduler for timed Task execution.

Polls MongoDB periodically for pending Tasks whose ``scheduled_at`` has
passed and transitions them to ``running`` status (subject to concurrency
limits).

Usage::

    scheduler = TaskSchedulerService()
    await scheduler.start()   # begins background polling
    ...
    await scheduler.stop()    # clean shutdown
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from loguru import logger

from app.core.config import settings
from app.db.mongodb import get_database
from app.models.task import TaskStatus


class TaskSchedulerService:
    """Background scheduler for timed Task execution.

    Polls MongoDB periodically for due Tasks and transitions them to
    ``running`` status (subject to concurrency limits).

    Poll interval configured via ``TASK_SCHEDULER_POLL_INTERVAL`` in settings.
    Set to 0 to disable.

    Attributes:
        _task: The running ``asyncio.Task`` for the poll loop.
        _stopped: Event flag for graceful shutdown.
    """

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stopped: bool = False

    # ── Lifecycle ──

    async def start(self) -> None:
        """Start the background scheduler poll loop.

        Idempotent — safe to call multiple times.
        """
        if self._task is not None and not self._task.done():
            logger.info("task_scheduler_already_running")
            return

        self._stopped = False
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("task_scheduler_started")

    async def stop(self) -> None:
        """Stop the background scheduler poll loop gracefully."""
        self._stopped = True

        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        self._task = None
        logger.info("task_scheduler_stopped")

    @property
    def is_running(self) -> bool:
        """Whether the scheduler poll loop is currently active."""
        return self._task is not None and not self._task.done()

    # ── Poll loop ──

    async def _poll_loop(self) -> None:
        """Main poll loop — runs until stopped."""
        poll_interval = settings.TASK_SCHEDULER_POLL_INTERVAL
        if poll_interval <= 0:
            logger.info("task_scheduler_disabled_by_config")
            return

        logger.info(
            "task_scheduler_poll_loop_started",
            poll_interval_s=poll_interval,
        )

        while not self._stopped:
            try:
                await self._process_due_tasks()
            except Exception as exc:
                logger.error("task_scheduler_poll_error", error=str(exc))

            await asyncio.sleep(poll_interval)

        logger.info("task_scheduler_poll_loop_ended")

    async def _process_due_tasks(self) -> int:
        """Find and auto-start all due scheduled Tasks.

        Finds pending Tasks where ``scheduled_at <= now()`` and
        transitions them to ``running`` status, respecting concurrency
        limits (via ``TaskService.transition_task``).

        Returns:
            Number of Tasks successfully started.
        """
        col = get_database()["tasks"]
        now = datetime.now(timezone.utc)

        # Find due tasks — query for pending with scheduled_at <= now
        cursor = col.find(
            {
                "status": TaskStatus.PENDING.value,
                "scheduled_at": {"$lte": now, "$ne": None},
            }
        ).sort("scheduled_at", 1).limit(50)

        due_tasks = await cursor.to_list(length=50)
        if not due_tasks:
            return 0

        started = 0
        for doc in due_tasks:
            task_id = doc["_id"]
            try:
                # Import here to avoid circular import
                from app.services.task_service import TaskService

                # Check concurrency limits first — skip (don't fail) if exceeded
                created_by = doc.get("created_by", "")
                try:
                    await TaskService._check_concurrency_limits(created_by)
                except Exception:
                    logger.warning(
                        "task_scheduler_skip_concurrency_limit",
                        task_id=task_id,
                        created_by=created_by,
                    )
                    continue

                await TaskService.transition_task(
                    task_id=task_id,
                    to_status=TaskStatus.RUNNING,
                    triggered_by="system",
                    triggered_by_type="system",
                    timeline_event_type="scheduled_start",
                    timeline_data={"scheduled_at": str(doc.get("scheduled_at", ""))},
                )
                started += 1
                logger.info(
                    "task_scheduled_started",
                    task_id=task_id,
                    scheduled_at=str(doc.get("scheduled_at", "")),
                )

            except Exception as exc:
                logger.error(
                    "task_scheduler_start_error",
                    task_id=task_id,
                    error=str(exc),
                )

        return started


# Module-level singleton
_scheduler: TaskSchedulerService | None = None


def get_scheduler() -> TaskSchedulerService:
    """Return the process-level TaskSchedulerService singleton."""
    global _scheduler
    if _scheduler is None:
        _scheduler = TaskSchedulerService()
    return _scheduler
