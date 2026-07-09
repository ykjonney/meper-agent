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
from app.workers.loop import run_async


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
    return run_async(_execute_async(trigger_id))


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

    # 4. Find the placeholder "template" Task (always pending — it represents
    #    the trigger configuration, not a single execution). The template is
    #    never executed directly; instead we snapshot a fresh execution Task
    #    from it so that modifying the trigger mid-execution doesn't affect
    #    the run in progress, and the template stays pending for the user to
    #    see/cancel at any time.
    template_doc = await db["tasks"].find_one(
        {"trigger_id": trigger_id, "status": "pending", "source": "trigger"},
    )
    if not template_doc:
        # No template — trigger was cancelled or never had a placeholder.
        logger.warning("trigger_template_not_found", trigger_id=trigger_id)
        return {"status": "skipped", "message": "template task not found"}

    # 5. Snapshot a fresh execution Task from the template. This Task is the
    #    one that actually runs. It carries source="trigger_scheduled" so it's
    #    distinguishable from the always-pending template (source="trigger").
    from app.models.base import generate_id, utc_now as _utc_now
    from app.models.task import TaskStatus

    snapshot_id = generate_id("task")
    snapshot_doc = {
        "_id": snapshot_id,
        "workflow_id": template_doc["workflow_id"],
        "input": rendered_input,
        "created_by": template_doc.get("created_by", ""),
        "created_by_type": template_doc.get("created_by_type", "system"),
        "call_chain": [],
        "status": TaskStatus.PENDING.value,
        "source": "trigger_scheduled",
        "trigger_id": trigger_id,
        "scheduled_at": template_doc.get("scheduled_at"),
        "timeline": [
            {
                "timestamp": _utc_now().isoformat(),
                "event_type": "created",
                "data": {"workflow_id": template_doc["workflow_id"], "from_trigger": trigger_id},
                "actor": "system",
            }
        ],
        "created_at": _utc_now(),
        "updated_at": _utc_now(),
        "version": 1,
    }
    await db["tasks"].insert_one(snapshot_doc)
    task_id = snapshot_id

    logger.info(
        "scheduled_workflow_snapshot_created",
        trigger_id=trigger_id,
        template_id=template_doc["_id"],
        snapshot_task_id=task_id,
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
