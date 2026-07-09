"""Generic workflow execution Celery task.

This is the single entry point for executing ANY workflow Task via Celery,
unifying what was previously scattered in-process ``asyncio.create_task``
calls (TaskService._start_workflow_execution / resume_task_execution) and
the trigger-specific execute_scheduled_workflow.

Dispatched by:
    - TaskService.create_task        (newly created Task)
    - TaskService.intervene retry    (failed Task retried)
    - TaskService.intervene resume   (waiting_human Task resumed)
    - TaskSchedulerService poll loop (manual Task with scheduled_at due)
    - task_recovery timeout action   (auto_approve / auto_skip on restart)

The engine itself decides whether this is a first-time run or a resume from
checkpoint based on the Task document's ``checkpoint`` field — so this task
needs nothing but a ``task_id``.
"""
import asyncio
from typing import Any

from loguru import logger

from app.engine.workflow.engine import WorkflowEngine
from app.workers.celery_app import celery_app

# Reuse a single event loop across Celery task invocations on this worker.
# asyncio.run() closes the loop after each call, but motor caches the loop
# reference — using a closed loop on the second invocation raises RuntimeError.
_loop: asyncio.AbstractEventLoop | None = None


def _get_loop() -> asyncio.AbstractEventLoop:
    """Return a persistent event loop for async Celery tasks."""
    global _loop
    if _loop is None or _loop.is_closed():
        _loop = asyncio.new_event_loop()
    return _loop


@celery_app.task(name="app.workers.tasks.workflow_execution.run_workflow_task")
def run_workflow_task(task_id: str) -> dict[str, Any]:
    """Execute (or resume) a workflow Task.

    Celery task entry point. Delegates to the async WorkflowEngine.

    Args:
        task_id: The Task document ID. The engine loads the Task and its
                 Workflow, then either executes from the start node or
                 resumes from a saved checkpoint (for Human-node pause/resume).

    Returns:
        Task execution result summary.
    """
    return _get_loop().run_until_complete(_run_async(task_id))


async def _run_async(task_id: str) -> dict[str, Any]:
    """Async execution: run the WorkflowEngine for the given Task.

    The engine handles all state transitions (PENDING→RUNNING→COMPLETED/
    FAILED/WAITING_HUMAN) internally via TaskService.transition_task.
    """
    try:
        engine = WorkflowEngine()
        await engine.run_and_persist(task_id)
        logger.info("workflow_task_completed", task_id=task_id)
        return {"status": "success", "task_id": task_id}
    except Exception as exc:
        # The engine already marks the Task FAILED on internal exceptions
        # (see engine.run_and_persist except block). This outer guard only
        # catches errors the engine itself didn't handle.
        logger.error("workflow_task_failed", task_id=task_id, error=str(exc))
        return {"status": "error", "task_id": task_id, "message": str(exc)}
