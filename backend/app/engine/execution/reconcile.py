"""执行域影子双写对账（E4，PR #73 验收：新旧状态一致性可识别）。

用法：
    cd backend && uv run python -m app.engine.execution.reconcile [--fix-status]

对比权威（tasks.checkpoint）与影子（execution_checkpoints Manifest）：
- **漂移**：task 有 checkpoint（pause/progress/cancel）但影子缺对应最新边界；
- **悬空**：task 无 checkpoint（完成清除后）但影子最新边界非 complete；
- **多影**：同一 task 存在多条活跃影子 Execution（并发创建缺陷）。

双写期这是预期的短暂窗口（影子尽力而为），对账用于量化漂移率与发现
系统性缺陷；``--fix-status`` 将影子执行状态对齐终态（不删数据）。
"""
from __future__ import annotations

import asyncio
import sys
from typing import Any

from loguru import logger

from app.db.mongodb import get_database
from app.engine.execution.collections import (
    CHECKPOINT_MANIFESTS,
    EXECUTIONS,
)

_TERMINAL = {"succeeded", "failed", "cancelled", "timed_out", "expired"}


async def reconcile(fix_status: bool = False) -> dict[str, int]:
    db = get_database()
    report = {"drifted": 0, "dangling": 0, "multi_shadow": 0, "fixed": 0}

    # 每个 task 的活跃影子执行
    shadows: dict[str, list[dict[str, Any]]] = {}
    async for doc in db[EXECUTIONS].find(
        {"trigger": "workflow", "task_id": {"$ne": None}}
    ):
        shadows.setdefault(doc["task_id"], []).append(doc)

    for task_id, execs in shadows.items():
        active = [e for e in execs if e.get("status") not in _TERMINAL]
        if len(active) > 1:
            report["multi_shadow"] += 1
            logger.warning(
                "reconcile_multi_shadow task={} count={}", task_id, len(active)
            )
        if not active:
            continue
        execution_id = active[0]["_id"]

        latest_manifest = await db[CHECKPOINT_MANIFESTS].find_one(
            {"execution_id": execution_id}, sort=[("checkpoint_seq", -1)]
        )
        task = await db["tasks"].find_one({"_id": task_id}, {"checkpoint": 1, "status": 1})
        if task is None:
            continue
        legacy_cp = task.get("checkpoint")

        if legacy_cp:
            # 权威有暂停/进度边界 → 影子应有对应非 complete 边界
            if latest_manifest is None or latest_manifest.get("kind") == "complete":
                report["drifted"] += 1
                logger.warning(
                    "reconcile_drift task={} legacy_kind={} shadow={}",
                    task_id,
                    legacy_cp.get("kind"),
                    "none" if latest_manifest is None else latest_manifest.get("kind"),
                )
        elif task.get("status") == "completed":
            # 权威已完成（checkpoint 已清）→ 影子最新边界应为 complete 且执行终态
            if latest_manifest is None or latest_manifest.get("kind") != "complete":
                report["dangling"] += 1
                logger.warning(
                    "reconcile_dangling task={} shadow_kind={}",
                    task_id,
                    "none" if latest_manifest is None else latest_manifest.get("kind"),
                )
            if fix_status and active[0].get("status") != "succeeded":
                await db[EXECUTIONS].update_one(
                    {"_id": execution_id},
                    {"$set": {"status": "succeeded"}},
                )
                report["fixed"] += 1

    logger.info("reconcile_report {}", report)
    return report


def main() -> None:
    fix = "--fix-status" in sys.argv
    report = asyncio.run(reconcile(fix_status=fix))
    print(report)
    sys.exit(0 if report["drifted"] == 0 and report["multi_shadow"] == 0 else 1)


if __name__ == "__main__":
    main()
