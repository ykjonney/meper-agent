"""Scheduled workflow execution Celery task.

Trigger firing is driven by TriggerSchedulerService's polling loop, which
atomically claims due triggers and dispatches this task *immediately* (no
eta). This avoids the Redis visibility_timeout re-delivery problem that
plagued the previous eta self-chain design for long schedules.

Re-delivery hardening (two layers):
    1. Early ack — this task overrides the global ``task_acks_late=True``
       with ``acks_late=False``: the message is acknowledged on receipt, so
       a SIGKILL (task_time_limit) or worker crash mid-execution can NOT
       leave an unacked message that Redis re-delivers every
       visibility_timeout. A single firing may be lost that way, but the
       next cron period fires on schedule — infinitely preferable to the
       hourly zombie loop.
    2. Idempotency guard — if a re-delivered message still slips through
       (e.g. an old late-ack message already sitting in the unacked set),
       the fork step is skipped while another PENDING/RUNNING task from the
       same trigger is in flight.

Responsibilities here are intentionally minimal:
    load trigger → load workflow → render input → find placeholder Task
    → run engine → update last_triggered_at.

The *next* firing is already scheduled by the poller (it advanced
next_trigger_at when it claimed the trigger), so there is no self-chain.
"""
from typing import Any

from loguru import logger

from app.db.mongodb import get_database
from app.engine.workflow.engine import WorkflowEngine
from app.models.base import utc_now
from app.models.task import TaskStatus
from app.services.trigger_repo import TriggerRepository
from app.utils.template_renderer import render_default_input
from app.workers.celery_app import celery_app
from app.workers.loop import run_async


@celery_app.task(
    name="app.workers.tasks.scheduled_workflow.execute_scheduled_workflow",
    acks_late=False,
)
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

    # 4. Idempotency guard — skip if another task forked from this trigger is
    #    still in flight (PENDING/RUNNING). WAITING_HUMAN does NOT count: the
    #    engine returns promptly on WorkflowPausedError, so that task's Celery
    #    message was already acked and the pause is a legitimate long-lived
    #    state. This guard catches broker re-deliveries (visibility_timeout)
    #    that would otherwise fork duplicate executions.
    inflight = await db["tasks"].find_one(
        {
            "trigger_id": trigger_id,
            "source": "trigger_scheduled",
            "status": {"$in": [TaskStatus.PENDING.value, TaskStatus.RUNNING.value]},
        }
    )
    if inflight is not None:
        logger.warning(
            "scheduled_workflow_skip_inflight",
            trigger_id=trigger_id,
            inflight_task_id=inflight["_id"],
            inflight_status=inflight.get("status"),
        )
        return {
            "status": "skipped",
            "message": "in-flight task exists for trigger",
            "task_id": inflight["_id"],
        }

    # 5. Fork a fresh execution Task directly from the trigger document.
    #    No placeholder/template task is used — the trigger IS the management
    #    entity. Each firing creates an independent task that runs to
    #    completion. The task starts in PENDING because the engine's
    #    execute_task performs a PENDING→RUNNING transition internally.
    from app.models.base import generate_id
    from app.models.base import utc_now as _utc_now

    snapshot_id = generate_id("task")
    now = _utc_now()
    snapshot_doc = {
        "_id": snapshot_id,
        "workflow_id": trigger_doc.workflow_id,
        "input": rendered_input,
        "created_by": trigger_doc.user_id,
        "created_by_type": "system",
        "call_chain": [],
        "status": TaskStatus.PENDING.value,
        "source": "trigger_scheduled",
        "trigger_id": trigger_id,
        "scheduled_at": trigger_doc.next_trigger_at,
        "timeline": [
            {
                "timestamp": now.isoformat(),
                "event_type": "created",
                "data": {"workflow_id": trigger_doc.workflow_id, "from_trigger": trigger_id},
                "actor": "system",
            },
        ],
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    await db["tasks"].insert_one(snapshot_doc)
    task_id = snapshot_id

    logger.info(
        "scheduled_workflow_task_forked",
        trigger_id=trigger_id,
        task_id=task_id,
    )

    # 6. Execute the workflow
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
