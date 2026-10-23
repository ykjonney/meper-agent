"""Running task scan — 慢任务警告 + 孤儿清理（beat 每 5 分钟）。

Celery 去硬超时（workflow_execution.py 覆盖 time_limit/acks_late）后的
两道巡检防线：

1. 慢任务警告（TASK_SLOW_WARN_MINUTES，默认 30 分钟）：
   RUNNING 超阈值 → 站内信（NotificationKind.TASK_SLOW）+ timeline 事件。
   只提醒不干预——长任务合法（loop×多轮 agent 数小时），用户自行决定
   等待或取消。slow_warned_at 判重（TASK_SLOW_WARN_REPEAT_MINUTES 内
   不重复发）。

2. 孤儿清理（TASK_ORPHAN_MINUTES，默认 30 分钟）：
   RUNNING 且 updated_at 超阈值 → FAILED（ORPHAN_RUNNING_TASK）。
   acks_early 后 worker 被 SIGKILL 不重投，此项是"卡 RUNNING"的唯一
   常驻防线（FastAPI lifespan 的启动清理保留，幂等先到先得）。
   阈值大于 agent 节点默认 timeout（5min）+ loop 轮间隙——正常执行的
   任务每节点边界/token 累加都会 touch updated_at。
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from loguru import logger

from app.core.config import settings
from app.models.base import utc_now
from app.workers.celery_app import celery_app
from app.workers.loop import run_async


async def _notify_slow(task: dict[str, Any], elapsed_min: int) -> None:
    """发慢任务站内信 + timeline 事件 + 判重标记。"""
    from app.db.mongodb import get_database
    from app.models.notification import Notification, NotificationKind
    from app.services.notification_repo import NotificationRepository

    db = get_database()
    task_id = str(task["_id"])
    user_id = str(task.get("created_by") or "")

    now = utc_now()
    # 判重 + 标记（原子：只有本次争到才发——$gt 条件并发安全）。
    repeat_ms = settings.TASK_SLOW_WARN_REPEAT_MINUTES * 60 * 1000
    claimed = await db["tasks"].update_one(
        {
            "_id": task_id,
            "$or": [
                {"slow_warned_at": {"$exists": False}},
                {"slow_warned_at": None},
                {"slow_warned_at": {"$lt": (now - timedelta(milliseconds=repeat_ms)).isoformat()}},
            ],
        },
        {"$set": {"slow_warned_at": now.isoformat()}},
    )
    if claimed.modified_count == 0:
        return

    if user_id:
        try:
            repo = NotificationRepository(get_database())
            notif = Notification(
                user_id=user_id,
                kind=NotificationKind.TASK_SLOW,
                title=f"任务运行已超过 {elapsed_min} 分钟",
                body=(
                    f"工作流任务 {task.get('workflow_id', '')}（{task_id}）仍在运行。"
                    f"长任务属正常现象（多轮循环/大量节点），可继续等待或在任务详情页取消。"
                ),
                related_task_id=task_id,
                related_workflow_id=str(task.get("workflow_id") or "") or None,
            )
            await repo.create(notif)
        except Exception as exc:
            logger.debug("slow_warn_notification_failed", task_id=task_id, error=str(exc))

    from app.services.task_service import TaskService

    await TaskService.append_timeline_event(
        task_id=task_id,
        event_type="task_running_slow",
        data={"elapsed_minutes": elapsed_min, "warn_minutes": settings.TASK_SLOW_WARN_MINUTES},
    )
    logger.warning("task_running_slow", task_id=task_id, elapsed_minutes=elapsed_min)


async def _scan_async() -> dict[str, int]:
    from app.db.mongodb import get_database
    from app.services.task_recovery import recover_orphan_running_tasks

    db = get_database()
    now = utc_now()

    # ── 慢任务警告 ──
    slow_cutoff = (
        now - timedelta(minutes=settings.TASK_SLOW_WARN_MINUTES)
    ).isoformat()
    slow_tasks = db["tasks"].find(
        {
            "status": "running",
            "started_at": {"$lt": slow_cutoff},
        },
        {"workflow_id": 1, "created_by": 1, "started_at": 1},
    ).limit(100)
    warned = 0
    async for task in slow_tasks:
        try:
            started = str(task.get("started_at") or "")
            elapsed_min = settings.TASK_SLOW_WARN_MINUTES
            if started:
                try:
                    from datetime import datetime

                    started_dt = datetime.fromisoformat(started)
                    elapsed_min = int((now - started_dt).total_seconds() // 60)
                except ValueError:
                    pass
            await _notify_slow(task, elapsed_min)
            warned += 1
        except Exception:
            logger.exception("slow_warn_failed", task_id=str(task.get("_id")))

    # ── 孤儿清理 ──
    orphaned = await recover_orphan_running_tasks(
        idle_seconds=settings.TASK_ORPHAN_MINUTES * 60, limit=100,
    )

    return {"warned": warned, "orphaned": orphaned}


@celery_app.task(name="app.workers.tasks.running_task_scan.scan_running_tasks")
def scan_running_tasks() -> dict[str, int]:
    """Periodic: slow-task warnings + orphan RUNNING cleanup (every 5 min)."""
    return run_async(_scan_async())
