"""Task recovery service — restores waiting_human tasks after server restart.

On startup, scans for tasks stuck in waiting_human status and executes
``timeout_action`` for already-timed-out tasks. Tasks not yet timed out are
left for the periodic beat task ``sweep_timed_out_human_tasks`` to handle
(see ``app/workers/tasks/human_timeout.py``) — there is no longer a process-
local monitor, because the Celery worker's event loop is only driven for the
duration of ``run_until_complete(engine)`` and cannot keep an asyncio.sleep
alive past a Human-node pause.

Also cleans up orphan ``running`` tasks left behind by a process restart:
workflow execution runs in a Celery worker process, so a worker crash/restart
orphans any task still in ``running``. Only ``human`` nodes persist a
checkpoint, so a ``running`` task interrupted mid-``agent``/``gateway``/``tool``
node has no resumable state and is marked ``failed``.
"""
from __future__ import annotations

from typing import Any

from loguru import logger

from app.db.mongodb import get_database
from app.models.task import TaskStatus, utc_now

# running 任务要被视为孤儿，其 updated_at 必须早于「现在 - 此阈值」。
# 阈值留出余量，避免误伤本进程刚启动时正在执行的任务（例如 lifespan 之前
# 由定时调度触发、或上一进程退出与本进程启动几乎同时发生的边界情况）。
ORPHAN_RUNNING_GRACE_SECONDS = 60


async def recover_waiting_human_tasks() -> None:
    """Recover tasks stuck in waiting_human status after server restart.

    Called during application startup (lifespan).

    Steps:
    1. Find all tasks with status=waiting_human that have a checkpoint
    2. For each task already past its timeout_deadline: execute timeout_action
       immediately. Tasks not yet timed out are left for the periodic beat
       task ``sweep_timed_out_human_tasks`` to handle.
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
                    await execute_timeout_action(
                        task_id=task_id,
                        timeout_action=timeout_action,
                        checkpoint=checkpoint if isinstance(checkpoint, dict) else None,
                    )
                else:
                    # Not yet timed out — leave it to the periodic sweep task.
                    logger.info(
                        "recover_task_leave_to_sweep",
                        task_id=task_id,
                        timeout_action=timeout_action,
                    )
            else:
                # No timeout configured — just log
                logger.info(
                    "recover_task_no_timeout",
                    task_id=task_id,
                    paused_node=checkpoint.get("paused_at_node", ""),
                )

        except Exception as exc:
            logger.error(
                "recover_task_failed",
                task_id=task_id,
                error=str(exc),
            )


async def execute_timeout_action(
    task_id: str,
    timeout_action: str,
    checkpoint: dict[str, Any] | None = None,
) -> None:
    """Execute the configured timeout action for a waiting_human task.

    Shared by startup recovery (``recover_waiting_human_tasks``) and the
    periodic sweep task (``sweep_timed_out_human_tasks``).

    Args:
        task_id: The Task ID.
        timeout_action: One of auto_approve, auto_reject, auto_skip, fail.
        checkpoint: The task's checkpoint (callers already hold the task doc).
            Its ``paused_at_node`` is attached to the timeline event so the
            frontend can attribute the timeout decision to the human node.
    """
    from app.services.task_service import TaskService

    action_map = {
        "auto_approve": TaskStatus.RUNNING,
        "auto_reject": TaskStatus.FAILED,
        "auto_skip": TaskStatus.RUNNING,
        "fail": TaskStatus.FAILED,
    }

    target_status = action_map.get(timeout_action, TaskStatus.FAILED)

    _ckpt = checkpoint or {}
    decision_node_data: dict[str, Any] = {}
    if _ckpt.get("paused_at_node"):
        decision_node_data = {"node_id": str(_ckpt["paused_at_node"]), "node_type": "human"}

    await TaskService.transition_task(
        task_id=task_id,
        to_status=target_status,
        triggered_by="system",
        triggered_by_type="system",
        timeline_event_type="timeout",
        timeline_data={
            "timeout_action": timeout_action,
            "message": f"Recovery: 任务超时，执行 {timeout_action}",
            **decision_node_data,
        },
    )

    # For auto_approve / auto_skip, also resume execution
    if target_status == TaskStatus.RUNNING:
        await TaskService.resume_task_execution(task_id)


async def recover_orphan_running_tasks(
    *,
    idle_seconds: int | None = None,
    limit: int | None = None,
) -> int:
    """Mark ``running`` tasks orphaned by a previous process as ``failed``.

    On startup, any task still in ``running`` is an orphan: its execution
    coroutine lived in the previous process and is gone. Only ``human`` nodes
    persist a checkpoint (see ``engine._execute_node``), so a ``running`` task
    interrupted mid-``agent``/``gateway``/``tool`` node has no resumable state
    and would otherwise sit in ``running`` forever.

    To avoid racing with tasks that the *current* process legitimately started
    during/just before lifespan, only tasks whose ``updated_at`` is older than
    the idle window are swept.

    Args:
        idle_seconds: 判定窗口（默认 ORPHAN_RUNNING_GRACE_SECONDS=60s，供
            FastAPI lifespan 启动清理用；beat 巡检传 TASK_ORPHAN_MINUTES
            的分钟级窗口——acks_early 后 worker 被杀不重投，这是"卡
            RUNNING"的唯一常驻防线）。
        limit: 单轮处理上限（beat 巡检分批用）。

    Returns:
        本轮标记为 FAILED 的任务数。
    """
    db = get_database()
    from datetime import timedelta

    idle = idle_seconds if idle_seconds is not None else ORPHAN_RUNNING_GRACE_SECONDS
    cutoff = utc_now() - timedelta(seconds=idle)

    query = {"status": TaskStatus.RUNNING.value, "updated_at": {"$lt": cutoff}}
    cursor = db["tasks"].find(
        query,
        {"_id": 1, "timeline": {"$slice": -3}, "updated_at": 1},
    )
    if limit is not None:
        cursor = cursor.limit(limit)
    orphans = await cursor.to_list(length=None)
    if not orphans:
        logger.debug("recover_orphan_running_tasks_none_found")
        return 0

    logger.warning("recover_orphan_running_tasks_starting", count=len(orphans))

    marked = 0
    for doc in orphans:
        task_id = doc["_id"]
        # 从 timeline 末尾推断卡住的节点（最后一条 node_start 无对应 node_complete）
        stuck_node_id = ""
        stuck_node_type = ""
        timeline = doc.get("timeline") or []
        for ev in reversed(timeline):
            data = ev.get("data") or {}
            if ev.get("event_type") == "node_start":
                stuck_node_id = data.get("node_id", "")
                stuck_node_type = data.get("node_type", "")
                break

        await _mark_orphan_running_failed(
            task_id=task_id,
            node_id=stuck_node_id,
            node_type=stuck_node_type,
        )
        marked += 1
    return marked


async def _mark_orphan_running_failed(
    task_id: str,
    node_id: str,
    node_type: str,
) -> None:
    """Transition an orphaned running task to ``failed`` with a clear error."""
    now = utc_now()
    db = get_database()
    res = await db["tasks"].update_one(
        {"_id": task_id, "status": TaskStatus.RUNNING.value},
        {
            "$set": {
                "status": TaskStatus.FAILED.value,
                # 终态清空 checkpoint：残留的 paused_at_node 会让前端把
                # 暂停过的 human 节点误显示为「审批中」。
                "checkpoint": None,
                "error": {
                    "node_id": node_id,
                    "node_type": node_type,
                    "error_message": "执行中断：后端进程重启导致运行时协程丢失（僵尸任务自动恢复）",
                    "error_code": "ORPHAN_RUNNING_TASK",
                    "timestamp": now,
                },
                "updated_at": now,
            },
            "$inc": {"version": 1},
            "$push": {
                "timeline": {
                    "timestamp": now,
                    "event_type": "failed",
                    "data": {
                        "message": "僵尸任务清理：进程重启后 running 状态无协程推进，标记为失败",
                        "node_id": node_id,
                        "node_type": node_type,
                        "recovery": True,
                    },
                    "actor": "system",
                }
            },
        },
    )
    if res.modified_count:
        logger.warning(
            "orphan_running_task_marked_failed",
            task_id=task_id,
            node_id=node_id,
            node_type=node_type,
        )
    else:
        # 状态已被其他路径推进（例如人工/超时已转移），跳过
        logger.info("orphan_running_task_skipped", task_id=task_id)


async def redispatch_orphan_pending_tasks(
    *,
    idle_seconds: int | None = None,
    limit: int | None = None,
) -> int:
    """Re-dispatch ``pending`` tasks whose Celery message was lost.

    acks_late=False（收到消息即 ack）下，worker 崩溃/SIGKILL/消费异常会让
    任务停在 ``pending`` 且永远无人拉起——孤儿 RUNNING 有 beat 判 FAILED
    兜底，孤儿 PENDING 此前没有任何恢复通道（worker 重启不会重投已 ack
    的消息）。

    恢复 = 重新 dispatch 统一入口 ``run_workflow_task``（内部按 agent_id
    分流）+ touch updated_at。幂等由状态机版本锁承担：若原消息其实还在
    排队，双消费方仅一方 pending→running 成功，另一方 skipped 无副作用。
    ``scheduled_at`` 未到期的合法待执行任务被排除（只扫无计划时间或已到期）。

    Args:
        idle_seconds: 判定窗口（启动恢复传 60s 宽限；beat 巡检传
            TASK_ORPHAN_PENDING_MINUTES 分钟级窗口）。
        limit: 单轮派发上限。

    Returns:
        本轮重派的任务数。
    """
    from datetime import timedelta

    db = get_database()
    idle = idle_seconds if idle_seconds is not None else ORPHAN_RUNNING_GRACE_SECONDS
    cutoff = utc_now() - timedelta(seconds=idle)

    query = {
        "status": TaskStatus.PENDING.value,
        "updated_at": {"$lt": cutoff},
        "$or": [{"scheduled_at": None}, {"scheduled_at": {"$lte": utc_now()}}],
    }
    cursor = db["tasks"].find(query, {"_id": 1})
    if limit is not None:
        cursor = cursor.limit(limit)
    orphans = await cursor.to_list(length=None)
    if not orphans:
        logger.debug("redispatch_orphan_pending_none_found")
        return 0

    logger.warning("redispatch_orphan_pending_starting", count=len(orphans))

    from app.workers.tasks.workflow_execution import run_workflow_task

    redispatched = 0
    for doc in orphans:
        task_id = str(doc["_id"])
        try:
            run_workflow_task.delay(task_id)
        except Exception as exc:
            # broker 不可达等：本轮跳过该任务，下一轮扫描继续（updated_at
            # 未 touch，仍处于超龄窗口）
            logger.error("orphan_pending_redispatch_failed", task_id=task_id, error=str(exc))
            continue
        # touch updated_at：若重派消息再次丢失，updated_at 重新超龄后下一轮
        # 扫描会再次重派（自愈循环）。
        await db["tasks"].update_one(
            {"_id": doc["_id"]}, {"$set": {"updated_at": utc_now()}},
        )
        redispatched += 1
        logger.info("orphan_pending_redispatched", task_id=task_id)
    return redispatched
