"""Celery application instance and configuration."""
from celery import Celery  # type: ignore[import-untyped]
from celery.schedules import crontab  # type: ignore[import-untyped]
from celery.signals import worker_process_init  # type: ignore[import-untyped]
from loguru import logger

from app.core.config import settings

celery_app = Celery(
    "agent_flow",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=[
        "app.workers.tasks.maintenance",
        "app.workers.tasks.webhook_delivery",
        "app.workers.tasks.scheduled_workflow",
        "app.workers.tasks.workflow_execution",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Shanghai",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    # 兜底超时：防卡死的工作流永久占用 worker（30 分钟软超时）。
    # 与取消功能正交，但提升健壮性。
    task_soft_time_limit=1800,
    task_time_limit=1860,
    # Redis visibility_timeout must exceed the longest eta delay.
    # Default is 3600s (1h) — eta messages consumed by the worker sit in
    # an in-memory timer until the eta arrives, but Redis restores unacked
    # messages after visibility_timeout expires.  For daily cron jobs the
    # eta can be ~24h away, so the message gets endlessly cycled between
    # "consumed → restored → consumed" and never executes.
    broker_transport_options={"visibility_timeout": 86400 * 7},  # 7 days
    # Periodic tasks (Celery Beat)
    beat_schedule={
        "cleanup-expired-workspaces": {
            "task": "app.workers.tasks.maintenance.cleanup_expired_workspaces",
            # Run daily at 03:00 UTC
            "schedule": crontab(hour=3, minute=0),
        },
    },
)


@worker_process_init.connect
def _configure_checkpointer(**_kwargs: object) -> None:
    """在每个 Celery worker 子进程启动时配置 MongoDB checkpointer。

    Celery worker 是独立进程，不走 FastAPI 的 lifespan，因此必须在
    ``worker_process_init`` 信号中显式配置，否则 harness 默认使用
    ``InMemorySaver``——agent 节点的 checkpoint 只存在于内存中，
    进程重启后丢失，前端无法按 task+node 反查执行详情。
    """
    try:
        from agent_flow_harness import build_mongo_saver, configure_checkpointer

        from app.db.mongodb import get_mongodb_client

        saver = build_mongo_saver(
            client=get_mongodb_client().delegate,
            db_name=settings.MONGODB_DB_NAME,
        )
        configure_checkpointer(saver, overwrite=True)
        logger.info("celery_checkpointer_configured", db=settings.MONGODB_DB_NAME)
    except Exception as exc:
        logger.error("celery_checkpointer_config_failed", error=str(exc))


__all__ = ["celery_app"]
