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
    """Periodic task: sweep sandbox containers by label.

    两种语义按 SANDBOX_REUSE_CONTAINER 分支：
    - 复用关（每命令一次性容器）：created-at 超过 SANDBOX_ORPHAN_MAX_AGE
      即孤儿（进程崩溃遗留）→ 强删。
    - 复用开（长驻容器）：exec 读容器内 last-used（SANDBOX_LAST_USED_FILE）
      超过 SANDBOX_CONTAINER_IDLE_TIMEOUT → 闲置回收；created-at 超过
      SANDBOX_CONTAINER_MAX_LIFETIME → 寿命兜底强删；last-used 不可读但
      年龄尚小 → 保守跳过。

    Scheduled via Celery beat（60s 一轮，见 celery_app.conf.beat_schedule）。
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

    if settings.SANDBOX_REUSE_CONTAINER:
        return _sweep_reusable(client, containers)
    return _sweep_oneshot(containers)


def _sweep_oneshot(containers: list) -> dict:
    """一次性容器清扫（复用关）：created-at 年龄即孤儿依据。"""
    from app.core.config import settings

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


def _sweep_reusable(client, containers: list) -> dict:
    """长驻容器清扫（复用开）：闲置回收 + 寿命兜底。

    闲置判定 exec 读容器内 last-used 文件（与命令同一个时钟源，无偏差）。
    exec 阻塞上限为 docker client timeout（30s）——容器挂死时单轮最坏
    N×30s，beat 任务可接受。
    """
    from agent_flow_harness.sandbox.docker import SANDBOX_LAST_USED_FILE

    from app.core.config import settings

    now = time.time()
    removed = 0
    for container in containers:
        age = _container_age_seconds(container, now)
        if age is not None and age > settings.SANDBOX_CONTAINER_MAX_LIFETIME:
            with contextlib.suppress(Exception):
                container.remove(force=True)
                removed += 1
                logger.info(
                    "sandbox_container_expired",
                    container_id=(getattr(container, "id", "") or "")[:12],
                    age_seconds=round(age),
                )
            continue

        last_used: float | None = None
        try:
            code, out = container.exec_run(["cat", SANDBOX_LAST_USED_FILE], user="sandbox")
            if code == 0 and out:
                raw = out[0] if isinstance(out, tuple) else out
                if isinstance(raw, bytes):
                    last_used = float(raw.decode("utf-8", "replace").strip())
        except Exception:
            last_used = None

        if last_used is None:
            # last-used 不可读：可能是刚创建还没跑过命令（保守跳过），
            # 也可能是异常遗留——超过孤儿阈值才删
            if age is not None and age > settings.SANDBOX_ORPHAN_MAX_AGE:
                with contextlib.suppress(Exception):
                    container.remove(force=True)
                    removed += 1
                    logger.info(
                        "sandbox_container_unreadable_removed",
                        container_id=(getattr(container, "id", "") or "")[:12],
                        age_seconds=round(age),
                    )
            continue

        idle = now - last_used
        if idle > settings.SANDBOX_CONTAINER_IDLE_TIMEOUT:
            with contextlib.suppress(Exception):
                container.remove(force=True)
                removed += 1
                logger.info(
                    "sandbox_container_idle_removed",
                    container_id=(getattr(container, "id", "") or "")[:12],
                    idle_seconds=round(idle),
                )
    if removed:
        logger.info("sandbox_reusable_sweep_done", removed=removed, scanned=len(containers))
    return {"removed": removed, "scanned": len(containers)}
