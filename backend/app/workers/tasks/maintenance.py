"""Celery tasks — workspace lifecycle and maintenance."""
import contextlib
import re
import time
from datetime import datetime

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


# 孤儿沙盒容器清扫 ────────────────────────────────────────────────────────
# label 约定与 harness DockerSandbox._execute_docker 打的 labels 一致。
_SANDBOX_LABEL = "agent-flow.sandbox"
_CREATED_AT_LABEL = "agent-flow.created-at"

# Docker Created 格式形如 2024-01-01T00:00:00.123456789Z（纳秒），裁到 6 位
# 以便 fromisoformat 解析。
_CREATED_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}")


def _container_age_seconds(container, now: float) -> float | None:
    """容器年龄（秒）：优先 label（本代码恒打），回退 daemon Created。

    两者都不可得时返回 None——调用方保守跳过（不删年龄不明的容器）。
    """
    raw = (container.labels or {}).get(_CREATED_AT_LABEL)
    if raw:
        try:
            return now - float(raw)
        except (TypeError, ValueError):
            pass
    created = (getattr(container, "attrs", None) or {}).get("Created")
    if created:
        match = _CREATED_RE.match(created)
        if match:
            try:
                created_dt = datetime.fromisoformat(match.group(0) + "+00:00")
                return now - created_dt.timestamp()
            except ValueError:
                return None
    return None


@celery_app.task(name="app.workers.tasks.maintenance.cleanup_orphan_sandboxes")
def cleanup_orphan_sandboxes() -> dict:
    """Periodic task: force-remove orphan sandbox containers.

    正常路径容器执行完即删（DockerSandbox._execute_docker），但进程在
    wait 前崩溃会遗留容器。按 harness 打的 ``agent-flow.sandbox=true``
    label 扫描，年龄超过 ``SANDBOX_ORPHAN_MAX_AGE`` 的强删。
    Scheduled via Celery beat (10 分钟)。
    """
    from app.core.config import settings

    if not settings.SANDBOX_ENABLED:
        return {"removed": 0, "disabled": True}

    try:
        import docker
    except ImportError:
        logger.warning("sandbox_orphan_scan_skipped", reason="docker package not installed")
        return {"removed": 0, "docker_unavailable": True}

    try:
        client = docker.from_env(timeout=30)
        containers = client.containers.list(filters={"label": f"{_SANDBOX_LABEL}=true"})
    except Exception as exc:
        logger.warning("sandbox_orphan_scan_failed", error=str(exc))
        return {"removed": 0, "error": str(exc)}

    now = time.time()
    removed = 0
    for container in containers:
        age = _container_age_seconds(container, now)
        if age is None:
            # 年龄不明（label 缺失且 Created 不可解析）→ 保守跳过，不删
            continue
        if age <= settings.SANDBOX_ORPHAN_MAX_AGE:
            continue
        with contextlib.suppress(Exception):
            container.remove(force=True)
            removed += 1
            logger.info(
                "sandbox_orphan_removed",
                container_id=(getattr(container, "id", "") or "")[:12],
                sandbox_id=(container.labels or {}).get("agent-flow.sandbox-id"),
                age_seconds=round(age),
            )
    if removed:
        logger.info("sandbox_orphan_sweep_done", removed=removed, scanned=len(containers))
    return {"removed": removed, "scanned": len(containers)}
