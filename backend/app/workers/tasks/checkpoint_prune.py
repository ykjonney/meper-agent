"""Checkpoint prune — LangGraph checkpoints 集合的历史堆积治理。

checkpoints/checkpoint_writes 是 chat 会话与 workflow agent 节点共用的
集合，每个 superstep 存一条全量 state 快照（含截至该步全部消息序列化）
——存储 O(N²)，且除"删会话/删任务"外无任何清理路径。

两个策略（均为历史堆积性质，beat 每日一次足够——不存在"聊天中撞墙"
的时序问题，16MB 单文档限制不适用于 checkpoint 分文档存储）：

1. 每 thread 保最新 KEEP_LATEST 条：
   resume/interrupt 恢复只用最新一条（挂起点即最新）、get_thread_messages
   读最新、LangGraph time-travel 未使用——保 5 条余量充分。
   O(N²) → O(N)。

2. 完结 task 保留期（TASK_CHECKPOINT_RETENTION_DAYS，0=禁用）：
   completed/failed/cancelled 任务超期后删其全部 agent threads
   （thread_id 前缀 ``{task_id}_``）。代价：到期后前端"节点执行明细"
   不可回看（任务结果/timeline 不受影响）。
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from loguru import logger

from app.core.config import settings
from app.models.base import utc_now
from app.workers.celery_app import celery_app
from app.workers.loop import run_async

KEEP_LATEST = 5
"""每 thread 保留的最新 checkpoint 条数（resume 只用最新，5 条留余量）。"""


def _sync_prune_threads(saver: Any, thread_ids: list[str]) -> int:
    """同步删 checkpoints/writes 中指定 thread 的旧快照（线程池内执行）。

    pymongo 同步驱动，motor 异步环境下经 to_thread 卸载。
    """
    cp_col = getattr(saver, "checkpoint_collection", None)
    writes_col = getattr(saver, "writes_collection", None)
    if cp_col is None:
        return 0
    deleted = 0
    for thread_id in thread_ids:
        # 保最新 KEEP_LATEST 条 checkpoint_id，删更早的。
        keep_ids = [
            doc["checkpoint_id"]
            for doc in cp_col.find(
                {"thread_id": thread_id},
                {"checkpoint_id": 1},
            ).sort("checkpoint_id", -1).limit(KEEP_LATEST)
        ]
        query: dict[str, Any] = {"thread_id": thread_id}
        if keep_ids:
            query["checkpoint_id"] = {"$nin": keep_ids}
        res = cp_col.delete_many(query)
        deleted += res.deleted_count
        if writes_col is not None:
            if keep_ids:
                writes_col.delete_many({
                    "thread_id": thread_id,
                    "checkpoint_id": {"$nin": keep_ids},
                })
            else:
                writes_col.delete_many({"thread_id": thread_id})
    return deleted


def _sync_delete_task_threads(saver: Any, task_ids: list[str]) -> int:
    """删完结任务的全部 agent threads（前缀 {task_id}_）。"""
    cp_col = getattr(saver, "checkpoint_collection", None)
    writes_col = getattr(saver, "writes_collection", None)
    deleted = 0
    for task_id in task_ids:
        prefix = f"{task_id}_"
        if cp_col is not None:
            deleted += cp_col.delete_many({"thread_id": {"$regex": f"^{prefix}"}}).deleted_count
        if writes_col is not None:
            writes_col.delete_many({"thread_id": {"$regex": f"^{prefix}"}})
    return deleted


async def _prune_async() -> dict[str, int]:
    import asyncio

    from app.db.mongodb import get_database

    try:
        from app.engine.harness_integration import get_checkpointer

        saver = get_checkpointer()
    except Exception:
        return {"threads_pruned": 0, "task_threads_deleted": 0}

    db = get_database()

    # ── 策略 1：每 thread 保最新 K 条 ──
    # pymongo 同步集合：聚合找 checkpoint 数 > KEEP_LATEST 的 thread，
    # 经 to_thread 执行（batch 限量控扫描成本）。
    def _find_prunable() -> list[str]:
        cp_col = getattr(saver, "checkpoint_collection", None)
        if cp_col is None:
            return []
        return [
            doc["_id"]
            for doc in cp_col.aggregate([
                {"$group": {"_id": "$thread_id", "count": {"$sum": 1}}},
                {"$match": {"count": {"$gt": KEEP_LATEST}}},
                {"$limit": 500},
            ])
        ]

    threads_to_prune = await asyncio.to_thread(_find_prunable)
    pruned = 0
    if threads_to_prune:
        pruned = await asyncio.to_thread(_sync_prune_threads, saver, threads_to_prune)

    # ── 策略 2：完结 task 保留期 ──
    task_threads_deleted = 0
    retention_days = settings.TASK_CHECKPOINT_RETENTION_DAYS
    if retention_days > 0:
        cutoff = (utc_now() - timedelta(days=retention_days)).isoformat()
        finished = db["tasks"].find(
            {
                "status": {"$in": ["completed", "failed", "cancelled"]},
                "updated_at": {"$lt": cutoff},
            },
            {"_id": 1},
        ).limit(200)
        task_ids = [str(doc["_id"]) async for doc in finished]
        if task_ids:
            task_threads_deleted = await asyncio.to_thread(
                _sync_delete_task_threads, saver, task_ids,
            )

    if pruned or task_threads_deleted:
        logger.info(
            "checkpoint_prune_done",
            threads_pruned=pruned,
            task_threads_deleted=task_threads_deleted,
        )
    return {
        "threads_pruned": pruned,
        "task_threads_deleted": task_threads_deleted,
    }


@celery_app.task(name="app.workers.tasks.checkpoint_prune.prune_checkpoints")
def prune_checkpoints() -> dict[str, int]:
    """Periodic: prune old checkpoints (daily)."""
    return run_async(_prune_async())
