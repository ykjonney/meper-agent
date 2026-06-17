"""Task recovery service — restores waiting_human tasks after server restart.

On startup, scans for tasks stuck in waiting_human status and:
1. Executes timeout_action for already-timed-out tasks
2. Restarts timeout monitors for tasks with remaining time
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from loguru import logger

from app.db.mongodb import get_database
from app.models.task import TaskStatus, utc_now


async def recover_waiting_human_tasks() -> None:
    """Recover tasks stuck in waiting_human status after server restart.

    Called during application startup (lifespan).

    Steps:
    1. Find all tasks with status=waiting_human that have a checkpoint
    2. For each task:
       - If timed out (timeout_deadline < now): execute timeout_action
       - If not timed out: restart timeout monitor with remaining time
    """
    db = get_database()
    now = utc_now()

    cursor = db["tasks"].find({
        "status": TaskStatus.WAITING_HUMAN.value,
        "checkpoint": {"$exists": True, "$ne": None},
    })

    tasks_to_recover: list[dict[str, Any]] = []
    async for doc in cursor:
        tasks_to_recover.append(doc)

    if not tasks_to_recover:
        logger.debug("recover_waiting_human_tasks_none_found")
        return

    logger.info("recover_waiting_human_tasks_starting", count=len(tasks_to_recover))

    for doc in tasks_to_recover:
        task_id = doc["_id"]
        checkpoint = doc.get("checkpoint", {})
        timeout_deadline = checkpoint.get("timeout_deadline")
        timeout_action = checkpoint.get("timeout_action", "fail")
        paused_node_id = checkpoint.get("paused_at_node", "")

        try:
            if timeout_deadline:
                # Parse deadline (might be string from MongoDB)
                if isinstance(timeout_deadline, str):
                    from datetime import datetime as dt
                    deadline = dt.fromisoformat(timeout_deadline.replace("Z", "+00:00"))
                else:
                    deadline = timeout_deadline

                if deadline <= now:
                    # Already timed out — execute timeout_action immediately
                    logger.warning(
                        "recover_task_already_timed_out",
                        task_id=task_id,
                        timeout_action=timeout_action,
                    )
                    await _execute_timeout_action(
                        task_id=task_id,
                        timeout_action=timeout_action,
                    )
                else:
                    # Not yet timed out — restart monitor with remaining time
                    remaining_ms = int((deadline - now).total_seconds() * 1000)
                    logger.info(
                        "recover_task_restart_monitor",
                        task_id=task_id,
                        remaining_ms=remaining_ms,
                    )
                    await _restart_timeout_monitor(
                        task_id=task_id,
                        node_id=paused_node_id,
                        timeout_ms=remaining_ms,
                        timeout_action=timeout_action,
                    )
            else:
                # No timeout configured — just log
                logger.info(
                    "recover_task_no_timeout",
                    task_id=task_id,
                    paused_node=paused_node_id,
                )

        except Exception as exc:
            logger.error(
                "recover_task_failed",
                task_id=task_id,
                error=str(exc),
            )


async def _execute_timeout_action(task_id: str, timeout_action: str) -> None:
    """Execute the configured timeout action for a task.

    Args:
        task_id: The Task ID.
        timeout_action: One of auto_approve, auto_reject, auto_skip, fail.
    """
    from app.services.task_service import TaskService

    action_map = {
        "auto_approve": TaskStatus.RUNNING,
        "auto_reject": TaskStatus.FAILED,
        "auto_skip": TaskStatus.RUNNING,
        "fail": TaskStatus.FAILED,
    }

    target_status = action_map.get(timeout_action, TaskStatus.FAILED)

    await TaskService.transition_task(
        task_id=task_id,
        to_status=target_status,
        triggered_by="system",
        triggered_by_type="system",
        timeline_event_type="timeout",
        timeline_data={
            "timeout_action": timeout_action,
            "message": f"Recovery: 任务超时，执行 {timeout_action}",
        },
    )

    # For auto_approve / auto_skip, also resume execution
    if target_status == TaskStatus.RUNNING:
        TaskService.resume_task_execution(task_id)


async def _restart_timeout_monitor(
    task_id: str,
    node_id: str,
    timeout_ms: int,
    timeout_action: str,
) -> None:
    """Restart the timeout monitor for a recovered task.

    Args:
        task_id: The Task ID.
        node_id: The paused Human node ID.
        timeout_ms: Remaining timeout in milliseconds.
        timeout_action: Action on timeout.
    """
    from app.engine.workflow.nodes.human import get_human_timeout_monitor

    monitor = get_human_timeout_monitor()
    await monitor.start_monitor(
        task_id=task_id,
        node_id=node_id,
        timeout_ms=timeout_ms,
        timeout_action=timeout_action,
    )
