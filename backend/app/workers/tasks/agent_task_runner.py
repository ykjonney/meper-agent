"""Agent 目标 Task 的后台执行器（Celery worker 侧）。

与 WorkflowEngine.run_and_persist 平行的 agent 执行路径：
- 状态机转换 / 并发限制 / FIFO 调度：复用 TaskService.transition_task
- REACT 循环：复用 AgentExecutionService.invoke（execution_context="workflow"
  ——无人值守语义，剥离交互工具，后台任务不会挂起等人）
- 协作式取消：cancel_checker 每轮 REACT 边界查 task DB status（Redis flag
  方案是 API 进程 request_id 维度，这里以 DB 状态为准更直接，revoke 仍兜底）
- 结果回写守卫：回写前复查 status，已 cancelled 则丢弃（用户取消先于完成）
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from loguru import logger

from app.models.task import TaskStatus
from app.schemas.execution import ExecutionRequest
from app.services.agent_execution_service import AgentExecutionService
from app.services.session_service import SessionService
from app.services.task_service import TaskService


async def run_agent_async(task_id: str) -> dict[str, Any]:
    """Execute an agent-target Task: running → invoke → completed/failed.

    Returns a Celery result summary dict (status: success/error/skipped/cancelled).
    """
    task_doc = await TaskService.get_task(task_id)
    if task_doc is None:
        logger.warning("agent_task_not_found", task_id=task_id)
        return {"status": "skipped", "task_id": task_id, "message": "task not found"}

    agent_id = task_doc.get("agent_id", "")
    instruction = str((task_doc.get("input") or {}).get("instruction") or "")

    async def _cancel_checker() -> bool:
        fresh = await TaskService.get_task(task_id)
        return bool(fresh) and fresh.get("status") == TaskStatus.CANCELLED.value

    try:
        await TaskService.transition_task(
            task_id, TaskStatus.RUNNING, timeline_event_type="started",
        )
    except Exception as exc:  # 并发满等 ConflictError——保持 pending 等下轮
        logger.warning("agent_task_start_deferred", task_id=task_id, error=str(exc))
        return {"status": "skipped", "task_id": task_id, "message": str(exc)}
    # started_at 与 workflow 引擎同语义（慢任务警告扫描时间基准）
    await TaskService.update_task_output(
        task_id, {}, extra={"started_at": datetime.now(UTC).isoformat()},
    )

    try:
        resp = await AgentExecutionService.invoke(
            agent_id,
            ExecutionRequest(input=instruction),
            task_doc.get("created_by", ""),
            execution_context="workflow",
            cancel_checker=_cancel_checker,
        )
    except Exception as exc:
        logger.error("agent_task_failed", task_id=task_id, error=str(exc))
        await TaskService.transition_task(
            task_id, TaskStatus.FAILED,
            error_info={"error_message": str(exc)[:2000], "error_code": "AGENT_INVOKE_ERROR"},
        )
        return {"status": "error", "task_id": task_id, "message": str(exc)}

    # 回写守卫：取消先于完成 → 丢弃结果，保持 cancelled
    fresh = await TaskService.get_task(task_id)
    if fresh is None or fresh.get("status") == TaskStatus.CANCELLED.value:
        logger.info("agent_task_result_discarded", task_id=task_id)
        return {"status": "cancelled", "task_id": task_id}

    await SessionService.update_session(resp.session_id, {"task_id": task_id})
    await TaskService.update_task_output(task_id, {
        "output": resp.output,
        "session_id": resp.session_id,
        "step_count": resp.step_count,
        "agent_id": agent_id,
    })
    if resp.total_tokens:
        await TaskService.add_total_tokens(task_id, resp.total_tokens)
    await TaskService.transition_task(task_id, TaskStatus.COMPLETED)
    logger.info("agent_task_completed", task_id=task_id, session_id=resp.session_id)
    return {"status": "success", "task_id": task_id}
