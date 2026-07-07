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
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
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
