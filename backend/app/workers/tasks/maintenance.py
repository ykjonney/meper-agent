"""Celery tasks — workspace lifecycle and maintenance."""
from loguru import logger

from app.workers.celery_app import celery_app


@celery_app.task(name="app.workers.tasks.maintenance.cleanup_expired_workspaces")
def cleanup_expired_workspaces() -> dict:
    """Periodic task: remove expired workspace files.

    Strategy:
      - ``tmp/`` cleaned after ``WORKSPACE_RETENTION_DAYS / 2`` days.
      - Full workspace removed after ``WORKSPACE_RETENTION_DAYS`` days.

    Scheduled via Celery beat (see celery_app.conf.beat_schedule).
    """
    from app.engine.tool.workspace import WorkspaceManager

    logger.info("celery_task_cleanup_workspaces_start")
    result = WorkspaceManager.cleanup_expired_workspaces()
    logger.info(
        "celery_task_cleanup_workspaces_done",
        **result,
    )
    return result


@celery_app.task(name="app.workers.tasks.maintenance.cleanup_channel_sessions")
def cleanup_channel_sessions() -> dict:
    """Periodic task: cascade-delete channel sessions past their retention.

    渠道旧会话（channel: 前缀身份）轮换后永不再读，仅保留
    CHANNEL_SESSION_RETENTION_DAYS 天供排障回溯；超期级联清理
    （session + messages + checkpointer thread + workspace）。
    Web 会话不受影响。Scheduled via Celery beat (04:00 daily).
    """
    from app.core.config import settings
    from app.services.session_service import SessionService
    from app.workers.loop import run_async

    days = settings.CHANNEL_SESSION_RETENTION_DAYS
    if days <= 0:
        logger.info("celery_task_cleanup_channel_sessions_disabled")
        return {"deleted": 0, "retention_days": days, "disabled": True}

    deleted = run_async(SessionService.cleanup_channel_sessions(days))
    logger.info(
        "celery_task_cleanup_channel_sessions_done",
        deleted=deleted,
        retention_days=days,
    )
    return {"deleted": deleted, "retention_days": days}
