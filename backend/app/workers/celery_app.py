"""Celery application instance and configuration."""
from celery import Celery  # type: ignore[import-untyped]
from celery.schedules import crontab  # type: ignore[import-untyped]

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

__all__ = ["celery_app"]
