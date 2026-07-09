"""Scheduled workflow execution Celery task.

Refactored: operates on independent Trigger documents instead of
embedded trigger_config in workflows collection. Uses schedule_version
to detect stale tasks after config changes.
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
def execute_scheduled_workflow(
    trigger_id: str,
    expected_version: int,
) -> dict[str, Any]:
    """Execute a scheduled workflow.

    Celery task entry point. Delegates to async implementation.

    Args:
        trigger_id: Trigger document ID.
        expected_version: The schedule_version at the time of scheduling.

    Returns:
        Task execution result summary.
    """
    return _get_loop().run_until_complete(
        _execute_async(trigger_id, expected_version)
    )


async def _execute_async(
    trigger_id: str,
    expected_version: int,
) -> dict[str, Any]:
    """Async execution logic.

    Load trigger → version check → load workflow → render input
    → create Task → run engine → self-chain.
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

    # 2. Version check — user modified config, skip this execution
    if trigger_doc.schedule_version != expected_version:
        logger.info(
            "trigger_version_mismatch",
            trigger_id=trigger_id,
            expected=expected_version,
            actual=trigger_doc.schedule_version,
        )
        # Do NOT re-schedule here — the API endpoint that bumped the
        # version already called schedule_next with the new version.
        # Re-scheduling would duplicate Celery tasks in the queue.
        return {"status": "skipped", "message": "version mismatch"}

    # 3. Load workflow
    workflow_doc = await db["workflows"].find_one({"_id": trigger_doc.workflow_id})
    if not workflow_doc:
        logger.error(
            "workflow_not_found",
            workflow_id=trigger_doc.workflow_id,
            trigger_id=trigger_id,
        )
        return {"status": "error", "message": "workflow not found"}

    # 4. Render default input parameters
    rendered_input = render_default_input(trigger_doc.default_input)

    logger.info(
        "scheduled_workflow_starting",
        trigger_id=trigger_id,
        workflow_id=trigger_doc.workflow_id,
        rendered_input=rendered_input,
    )

    # 5. Find placeholder Task
    task_doc = await db["tasks"].find_one(
        {"trigger_id": trigger_id, "status": "pending", "source": "trigger"},
    )
    if not task_doc:
        logger.warning(
            "trigger_placeholder_not_found",
            trigger_id=trigger_id,
        )
        # Do NOT re-schedule here — could duplicate Celery tasks.
        # The trigger's next execution will be set up by:
        # - the API endpoint (if user updates the trigger), or
        # - TriggerSchedulerService.start() on next server restart.
        return {"status": "error", "message": "placeholder task not found"}

    task_id = task_doc["_id"]

    logger.info(
        "scheduled_workflow_starting_placeholder",
        trigger_id=trigger_id,
        task_id=task_id,
    )

    # 6. Self-chain: schedule next execution BEFORE running the workflow,
    # so the next Celery eta is dispatched immediately and doesn't drift
    # if the current execution takes a long time.
    if trigger_doc.type == "cron" and trigger_doc.enabled:
        try:
            from app.services.trigger_scheduler_service import TriggerSchedulerService

            chain_scheduler = TriggerSchedulerService(repo=repo)
            await chain_scheduler.schedule_next(trigger_id, exclude_task_id=task_id)
            logger.info("trigger_self_chain_scheduled", trigger_id=trigger_id)
        except Exception as chain_err:
            logger.error(
                "trigger_self_chain_failed",
                trigger_id=trigger_id,
                error=str(chain_err),
            )

    # 7. Execute the workflow
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
