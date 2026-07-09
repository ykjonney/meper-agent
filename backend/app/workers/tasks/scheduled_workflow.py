"""Scheduled workflow execution Celery task.

Trigger firing is driven by TriggerSchedulerService's polling loop, which
atomically claims due triggers and dispatches this task *immediately* (no
eta). This avoids the Redis visibility_timeout re-delivery problem that
plagued the previous eta self-chain design for long schedules.

Responsibilities here are intentionally minimal:
    load trigger → load workflow → render input → find placeholder Task
    → run engine → update last_triggered_at.

The *next* firing is already scheduled by the poller (it advanced
next_trigger_at when it claimed the trigger), so there is no self-chain.
"""
import asyncio
from typing import Any

from loguru import logger

from app.db.mongodb import get_database
from app.engine.workflow.engine import WorkflowEngine
from app.models.base import utc_now
from app.services.trigger_repo import TriggerRepository
from app.utils.template_renderer import render_default_input
from app.workers.celery_app import celery_app

# Reuse a single event loop across Celery task invocations.
# asyncio.run() closes the loop after each call, but motor caches the loop
# reference — using a closed loop on the second invocation raises RuntimeError.
_loop: asyncio.AbstractEventLoop | None = None


def _get_loop() -> asyncio.AbstractEventLoop:
    """Return a persistent event loop for async Celery tasks."""
    global _loop
    if _loop is None or _loop.is_closed():
        _loop = asyncio.new_event_loop()
    return _loop


@celery_app.task(name="app.workers.tasks.scheduled_workflow.execute_scheduled_workflow")
def execute_scheduled_workflow(trigger_id: str) -> dict[str, Any]:
    """Execute a scheduled workflow for the given trigger.

    Celery task entry point. Delegates to async implementation. The
    placeholder Task and next firing are managed by TriggerSchedulerService;
    this task only executes the current firing.

    Args:
        trigger_id: Trigger document ID.

    Returns:
        Task execution result summary.
    """
    return _get_loop().run_until_complete(_execute_async(trigger_id))


async def _execute_async(trigger_id: str) -> dict[str, Any]:
    """Async execution logic.

    Load trigger → load workflow → render input → find placeholder Task
    → run engine.
    """
    db = get_database()
    repo = TriggerRepository(db)

    # 1. Load trigger
    trigger_doc = await repo.find_by_id(trigger_id)
    if not trigger_doc:
        logger.error("trigger_not_found", trigger_id=trigger_id)
        return {"status": "error", "message": "trigger not found"}

    if not trigger_doc.enabled:
        logger.warning("trigger_disabled", trigger_id=trigger_id)
        return {"status": "skipped", "message": "disabled"}

    # 2. Load workflow
    workflow_doc = await db["workflows"].find_one({"_id": trigger_doc.workflow_id})
    if not workflow_doc:
        logger.error(
            "workflow_not_found",
            workflow_id=trigger_doc.workflow_id,
            trigger_id=trigger_id,
        )
        return {"status": "error", "message": "workflow not found"}

    # 3. Render default input parameters
    rendered_input = render_default_input(trigger_doc.default_input)

    logger.info(
        "scheduled_workflow_starting",
        trigger_id=trigger_id,
        workflow_id=trigger_doc.workflow_id,
        rendered_input=rendered_input,
    )

    # 4. Find placeholder Task (created by the poller when it claimed the trigger)
    task_doc = await db["tasks"].find_one(
        {"trigger_id": trigger_id, "status": "pending", "source": "trigger"},
    )
    if not task_doc:
        # The placeholder was already consumed (e.g. a duplicate dispatch
        # raced ahead) — nothing to do. The next firing is already scheduled
        # via next_trigger_at, so no recovery action is needed here.
        logger.warning("trigger_placeholder_not_found", trigger_id=trigger_id)
        return {"status": "skipped", "message": "placeholder task not found"}

    task_id = task_doc["_id"]

    logger.info(
        "scheduled_workflow_starting_placeholder",
        trigger_id=trigger_id,
        task_id=task_id,
    )

    # 5. Execute the workflow
    result: dict[str, Any] = {"status": "error", "task_id": task_id, "message": "unknown"}
    try:
        engine = WorkflowEngine()
        await engine.run_and_persist(task_id)

        # Update last_triggered_at
        await repo.update(trigger_id, last_triggered_at=utc_now())

        logger.info(
            "scheduled_workflow_completed",
            trigger_id=trigger_id,
            task_id=task_id,
        )

        result = {"status": "success", "task_id": task_id}

    except Exception as e:
        logger.error(
            "scheduled_workflow_failed",
            trigger_id=trigger_id,
            task_id=task_id,
            error=str(e),
        )
        result = {"status": "error", "task_id": task_id, "message": str(e)}

    return result
