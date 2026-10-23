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
from typing import Any

from loguru import logger

from app.engine.workflow.engine import WorkflowEngine
from app.workers.celery_app import celery_app
from app.workers.loop import run_async


@celery_app.task(
    name="app.workers.tasks.workflow_execution.run_workflow_task",
    # ── 长程任务：覆盖全局超时/ACK 配置 ──
    # time_limit=None：去掉 30/31 分钟硬超时（长工作流/loop×多轮 agent 极易
    # 超过）。防卡死不靠 Celery 级 SIGKILL——节点级 timeout_ms（agent 5min/
    # tool 30s）+ 孤儿扫描（beat，updated_at 超 30min 判 FAILED）承担。
    # acks_late=False：任务开始即 ACK。acks_late + 3h visibility_timeout 在
    # 无超时上限后会双跑（消息重投给另一 worker，zombie guard 只挡已取消
    # 任务）；状态机由 DB 承担，Celery 只当触发器（对齐 scheduled_workflow
    # 的同类决策）。
    acks_late=False,
    soft_time_limit=None,
    time_limit=None,
)
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
    return run_async(_run_async(task_id))


async def _run_async(task_id: str) -> dict[str, Any]:
    """Async execution: run the WorkflowEngine for the given Task.

    The engine handles all state transitions (PENDING→RUNNING→COMPLETED/
    FAILED/WAITING_HUMAN) internally via TaskService.transition_task.
    """
    try:
        engine = WorkflowEngine()
        result = await engine.run_and_persist(task_id)
        # The engine returns an empty dict {} when the task or workflow
        # document is not found (it logs the ERROR internally but does not
        # raise). Treat that as a failure so the Celery result reflects it
        # instead of misleadingly reporting success.
        if not result:
            logger.warning("workflow_task_no_result", task_id=task_id)
            return {"status": "skipped", "task_id": task_id, "message": "task or workflow not found"}
        logger.info("workflow_task_completed", task_id=task_id)
        return {"status": "success", "task_id": task_id}
    except Exception as exc:
        # The engine already marks the Task FAILED on internal exceptions
        # (see engine.run_and_persist except block). This outer guard only
        # catches errors the engine itself didn't handle.
        logger.error("workflow_task_failed", task_id=task_id, error=str(exc))
        return {"status": "error", "task_id": task_id, "message": str(exc)}
