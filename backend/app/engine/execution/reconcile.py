"""执行域影子双写对账（E4，PR #73 验收：新旧状态一致性可识别）。

用法：
    cd backend && uv run python -m app.engine.execution.reconcile [--fix-status]

对比权威（tasks.checkpoint）与影子（execution_checkpoints Manifest）：
- **漂移**：task 有 checkpoint（pause/progress/cancel）但影子缺对应最新边界；
- **悬空**：task 无 checkpoint（完成清除后）但影子最新边界非 complete；
- **多影**：同一 task 存在多条活跃影子 Execution（并发创建缺陷）。

双写期这是预期的短暂窗口（影子尽力而为），对账用于量化漂移率与发现
系统性缺陷；``--fix-status`` 只标记需要人工复核的项，不根据 Task.status 伪造 Execution 成功。
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
    report = {
        "drifted": 0,
        "dangling": 0,
        "multi_shadow": 0,
        "missing_shadow": 0,
        "fixed": 0,
        "manual_repair_required": 0,
    }

    shadows: dict[str, list[dict[str, Any]]] = {}
    async for doc in db[EXECUTIONS].find(
        {"trigger": "workflow", "task_id": {"$ne": None}}
    ):
        shadows.setdefault(doc["task_id"], []).append(doc)

    # Scan from the authoritative Task side as well: a best-effort shadow
    # write can fail before an Execution document exists.
    async for task in db["tasks"].find({}):
        task_id = task.get("_id")
        if not task_id:
            continue
        legacy_cp = task.get("checkpoint")
        completed = task.get("status") == "completed"
        if not legacy_cp and not completed:
            continue

        execs = shadows.get(task_id, [])
        active = [e for e in execs if e.get("status") not in _TERMINAL]
        if len(active) > 1:
            report["multi_shadow"] += 1
            logger.warning(
                "reconcile_multi_shadow task={} count={}", task_id, len(active)
            )

        if not execs:
            report["missing_shadow"] += 1
            logger.warning("reconcile_missing_shadow task={}", task_id)
            continue

        # Prefer the active shadow for an in-flight Task; for completed Tasks,
        # inspect the most recently created shadow, including terminal records.
        candidates = active if active else execs
        candidate = max(candidates, key=lambda e: (e.get("created_at") is not None, e.get("created_at")))
        execution_id = candidate["_id"]
        latest_manifest = await db[CHECKPOINT_MANIFESTS].find_one(
            {"execution_id": execution_id}, sort=[("checkpoint_seq", -1)]
        )

        if legacy_cp:
            if latest_manifest is None or latest_manifest.get("kind") == "complete":
                report["drifted"] += 1
                logger.warning(
                    "reconcile_drift task={} legacy_kind={} shadow={}",
                    task_id,
                    legacy_cp.get("kind"),
                    "none" if latest_manifest is None else latest_manifest.get("kind"),
                )
        elif completed:
            manifest_complete = (
                latest_manifest is not None
                and latest_manifest.get("kind") == "complete"
            )
            execution_complete = candidate.get("status") == "succeeded"
            if not manifest_complete or not execution_complete:
                report["dangling"] += 1
                logger.warning(
                    "reconcile_dangling task={} manifest_kind={} execution_status={}",
                    task_id,
                    None if latest_manifest is None else latest_manifest.get("kind"),
                    candidate.get("status"),
                )
                # Never infer success from Task.status alone. Repair requires
                # a reviewed terminal transition with event/lease semantics.
                if fix_status:
                    report["manual_repair_required"] += 1

    logger.info("reconcile_report {}", report)
    return report


def main() -> None:
    fix = "--fix-status" in sys.argv
    report = asyncio.run(reconcile(fix_status=fix))
    print(report)
    unresolved = ("drifted", "dangling", "multi_shadow", "missing_shadow")
    sys.exit(0 if all(report[key] == 0 for key in unresolved) else 1)


if __name__ == "__main__":
    main()
