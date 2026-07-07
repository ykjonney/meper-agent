"""Scheduled workflow execution Celery task."""
from loguru import logger

from app.db.mongodb import get_database
from app.engine.workflow.engine import WorkflowEngine
from app.models.base import utc_now
from app.services.task_service import TaskService
from app.utils.template_renderer import render_default_input
from app.workers.celery_app import celery_app


@celery_app.task(name="app.workers.tasks.scheduled_workflow.execute_scheduled_workflow")
def execute_scheduled_workflow(workflow_id: str) -> dict:
    """Execute a scheduled workflow.

    Celery task entry point. Delegates to async implementation.

    Args:
        workflow_id: Workflow ID to execute.

    Returns:
        Task execution result summary.
    """
    import asyncio

    return asyncio.run(_execute_async(workflow_id))


async def _execute_async(workflow_id: str) -> dict:
    """Async execution logic."""
    db = get_database()

    # 1. Load Workflow
    workflow_doc = await db["workflows"].find_one({"_id": workflow_id})
    if not workflow_doc:
        logger.error("scheduled_workflow_not_found", workflow_id=workflow_id)
        return {"status": "error", "message": f"Workflow {workflow_id} not found"}

    trigger_config = workflow_doc.get("trigger_config", {})
    if trigger_config.get("enabled") is False:
        logger.warning("scheduled_workflow_disabled", workflow_id=workflow_id)
        return {"status": "error", "message": "Trigger is disabled"}

    # 2. Render default input parameters
    default_input = trigger_config.get("default_input", {})
    rendered_input = render_default_input(default_input)

    logger.info(
        "scheduled_workflow_starting",
        workflow_id=workflow_id,
        rendered_input=rendered_input,
    )

    # 3. Create Task instance
    task_doc = await TaskService.create_task(
        workflow_id=workflow_id,
        input_data=rendered_input,
        created_by="system",
        created_by_type="system",
    )
    task_id = task_doc["_id"]

    logger.info(
        "scheduled_workflow_task_created",
        workflow_id=workflow_id,
        task_id=task_id,
    )

    # 4. Execute Workflow
    try:
        engine = WorkflowEngine()
        await engine.run_and_persist(task_id)

        # 5. Update last_triggered_at
        await db["workflows"].update_one(
            {"_id": workflow_id},
            {"$set": {"trigger_config.last_triggered_at": utc_now()}},
        )

        logger.info(
            "scheduled_workflow_completed",
            workflow_id=workflow_id,
            task_id=task_id,
        )
        return {"status": "success", "task_id": task_id}

    except Exception as e:
        logger.error(
            "scheduled_workflow_failed",
            workflow_id=workflow_id,
            task_id=task_id,
            error=str(e),
        )
        return {"status": "error", "task_id": task_id, "message": str(e)}
