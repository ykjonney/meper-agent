"""执行域周期扫描（E3）：Celery beat → RecoverySupervisor。

发现通道与故障恢复不再依赖任何单一进程（对齐 human_timeout 的
设计教训——进程内 asyncio monitor 在 Celery worker 上不可靠）。
"""
from typing import Any

from app.workers.celery_app import celery_app
from app.workers.loop import run_async


@celery_app.task(name="app.workers.tasks.execution_recovery.scan")
def execution_recovery_scan() -> dict[str, Any]:
    """周期任务：三类扫描（待派发/过期接管/活跃防重）。

    调度频率 = settings.EXECUTION_SCAN_INTERVAL_SECONDS（beat_schedule）。
    """
    return run_async(_scan_async())


async def _scan_async() -> dict[str, Any]:
    from app.engine.execution.recovery import RecoverySupervisor

    report = await RecoverySupervisor().scan_once()
    return {
        "redispatched": report.redispatched,
        "taken_over": report.taken_over,
        "skipped_active": report.skipped_active,
    }
