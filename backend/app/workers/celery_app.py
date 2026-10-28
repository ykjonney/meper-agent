"""Celery application instance and configuration."""
# Cython 兼容补丁最先安装（任何 pydantic 模型类创建之前）。
from app import _cycompat as _cycompat_module

_cycompat_module.install()

import threading

from celery import Celery  # type: ignore[import-untyped]
from celery.schedules import crontab  # type: ignore[import-untyped]
from celery.signals import (  # type: ignore[import-untyped]
    task_prerun,
    worker_process_init,
)
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
        "app.workers.tasks.channel_inbound",
        "app.workers.tasks.kb_indexing",
        "app.workers.tasks.human_timeout",
        "app.workers.tasks.wiki_source_extract",
        "app.workers.tasks.wiki_build",
        "app.workers.tasks.checkpoint_prune",
        "app.workers.tasks.running_task_scan",
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
    # Redis visibility_timeout: if a worker takes a message but doesn't ack
    # within this window, Redis restores it to the ready queue for re-delivery.
    # The project no longer uses Celery eta (scheduling is polling-based via
    # TriggerSchedulerService), so the default 1h is sufficient — kept at 3h
    # for safety margin. The zombie guard in run_and_persist handles any
    # re-delivered cancelled tasks.
    broker_transport_options={"visibility_timeout": 3600 * 3},  # 3 hours
    # Periodic tasks (Celery Beat)
    beat_schedule={
        "cleanup-expired-workspaces": {
            "task": "app.workers.tasks.maintenance.cleanup_expired_workspaces",
            # Run daily at 03:00 UTC
            "schedule": crontab(hour=3, minute=0),
        },
        # 渠道旧会话按保留期级联清理（session+checkpointer+workspace）。
        "cleanup-channel-sessions": {
            "task": "app.workers.tasks.maintenance.cleanup_channel_sessions",
            # Run daily at 04:00 UTC（错开 03:00 的 workspace 清理）
            "schedule": crontab(hour=4, minute=0),
        },
        # 扫描已超时的 waiting_human 任务并执行 timeout_action。
        # 取代了原先进程内的 asyncio monitor —— 后者在 Celery worker 的事件
        # 循环停止驱动后无法触发，导致超时不生效。频率即超时精度（30s）。
        "sweep-human-timeouts": {
            "task": "app.workers.tasks.human_timeout.sweep_timed_out_human_tasks",
            "schedule": 30.0,
        },
        # 慢任务警告 + 孤儿清理（workflow 任务已去 Celery 超时/改 acks_early，
        # 这两项是替代防线：慢任务只提醒不干预；孤儿=RUNNING 且 updated_at
        # 超阈值 → FAILED）。
        "scan-running-tasks": {
            "task": "app.workers.tasks.running_task_scan.scan_running_tasks",
            "schedule": 300.0,  # 5 分钟
        },
        # checkpoints 历史堆积治理：每 thread 保最新 5 条（O(N²)→O(N)）+
        # 完结 task 保留期清理。历史堆积性质，每日一次足够。
        "prune-checkpoints": {
            "task": "app.workers.tasks.checkpoint_prune.prune_checkpoints",
            "schedule": crontab(hour=5, minute=30),  # 每日 05:30，错开其他维护任务
        },
        # 孤儿沙盒容器清扫 / 复用容器闲置回收：按 label 扫描。
        # 间隔须 ≪ SANDBOX_CONTAINER_IDLE_TIMEOUT（300s），否则闲置语义漂移
        # （实际驻留 ≈ IDLE_TIMEOUT + 本间隔）。list+exec 探测负载可忽略。
        "sweep-orphan-sandboxes": {
            "task": "app.workers.tasks.maintenance.cleanup_orphan_sandboxes",
            "schedule": 60.0,  # 1 分钟
        },
    },
)


# 构建期由 scripts/build_compiled.py 注入 app.core.license 产物（strip 后）
# 的 sha256 与强制真值；源码轨保持占位符。完整性链校验点之一（与
# license_mw/engine 各自独立实现，判定输入不经 license 模块与 import
# 系统——模块被整体替换或 build_flags 被拦截时这里必须独立发现）。
_BUILT_LICENSE_SHA256 = "__LICENSE_SO_SHA256__"
_BUILT_LICENSE_ENFORCED = "__LICENSE_ENFORCED__"


def _license_module_sha_ok() -> bool:
    """license 模块完整性自检（物理定位 + 哈希比对，fail closed）。

    强制判定用构建期内联真值——不经 import，拦截 build_flags 无法关闭
    本检查；文件定位以本模块 ``__file__`` 为锚点（find_spec 会被
    sys.modules 中的假模块污染），并核对已加载模块的 ``__spec__.origin``
    与物理文件一致。
    """
    if _BUILT_LICENSE_ENFORCED != "True":
        return True
    import hashlib
    import sys
    from pathlib import Path

    if _BUILT_LICENSE_SHA256.startswith("__"):
        return False
    core_dir: Path | None = None
    for anc in Path(__file__).resolve().parents:
        if anc.name == "app" and (anc / "core").is_dir():
            core_dir = anc / "core"
            break
    if core_dir is None:
        return False
    physical: Path | None = None
    for cand in [
        *sorted(core_dir.glob("license.*.so")),
        *sorted(core_dir.glob("license.*.pyc")),
        *sorted((core_dir / "__pycache__").glob("license.*.pyc")),
    ]:
        try:
            if hashlib.sha256(cand.read_bytes()).hexdigest() == _BUILT_LICENSE_SHA256:
                physical = cand.resolve()
                break
        except OSError:
            continue
    if physical is None:
        return False
    mod = sys.modules.get("app.core.license")
    origin = getattr(getattr(mod, "__spec__", None), "origin", None)
    if not origin:
        return False
    try:
        return Path(origin).resolve() == physical
    except OSError:
        return False


def _license_contract_ok() -> bool:
    """矛盾检测：构建期强制而 license 模块谎报不强制 → 被篡改/欺骗。

    报告路径 3（meta_path 拦截 build_flags 返回 False）下，license 模块
    的 is_enforced() 被骗成 False——此处在强制构建上必须识别该矛盾。
    """
    if _BUILT_LICENSE_ENFORCED != "True":
        return True
    from app.core import license as lic

    return lic.evaluate_license().enforced


@worker_process_init.connect
def _init_worker(**_kwargs: object) -> None:
    """每个 Celery worker 子进程启动时的初始化。

    1. **日志初始化** — Celery worker 是独立进程，不走 FastAPI 的 lifespan，
       ``app.main`` 里的 ``setup_logging()`` 不会执行。必须在此显式调用，
       否则 worker 日志走 loguru 默认 sink（stderr 彩色输出），不写文件、
       不受 ``LOG_LEVEL`` / ``LOG_JSON_FORMAT`` 控制、格式与主进程不一致。

    2. **MongoDB checkpointer** — 同上，harness 默认使用 ``InMemorySaver``，
       agent 节点的 checkpoint 只存在于内存中，进程重启后丢失，前端无法
       按 task+node 反查执行详情。

    3. **MCP 凭证兑换器** — workflow task 全部在本进程执行，外部来源任务的
       MCP 调用必须以终端用户身份兑换凭证。不注入时 harness 拦截器对
       external_required 的调用按 fail-closed 拒绝（不会静默降级内部凭证，
       但外部任务会全部失败），因此注入失败只记日志、不阻断 worker 启动。

    4. **License 校验** — 强制模式下无有效 license 的 worker 直接拒绝启动
       （SystemExit → 子进程失败，celery 放弃后整个 worker 退出）。未激活
       降级模式对 backend 是"起服务给激活向导"，对 worker 没有意义——
       没有 API 就没有任务来源。
    5. **沙盒镜像预拉取** — 后台 daemon 线程执行（不阻塞 worker 启动），
       首笔沙盒执行免付整镜像 pull 耗时。失败只记日志。
    """
    # 1. 日志初始化 — 必须在打任何日志之前完成
    from app.core.logging import setup_logging
    setup_logging()

    # 4. License gate — 无有效 license 不干活（fail closed）。
    #    矛盾检测在前：构建期强制而模块谎报不强制 = 被篡改（如拦截
    #    build_flags 翻转总开关），与"未激活"同样拒绝启动。
    from app.core import license as lic

    _lic = lic.evaluate_license(force=True)
    if _BUILT_LICENSE_ENFORCED == "True" and not _lic.enforced:
        logger.critical("license_gate_worker_exit reason=contract_violation")
        raise SystemExit(78)
    if _lic.enforced and not _lic.ok:
        logger.critical("license_gate_worker_exit code={}", _lic.code)
        raise SystemExit(78)  # EX_CONFIG：配置类错误，一眼可辨
    if not _license_module_sha_ok():
        # 完整性链：license 模块文件被替换 → worker 拒绝启动。
        logger.critical("license_integrity_worker_exit")
        raise SystemExit(78)

    # 2. Checkpointer 配置 — shared with FastAPI lifespan via app.core.checkpointer
    from app.core.checkpointer import configure_mongo_checkpointer

    configure_mongo_checkpointer(log_on_error=True)

    # 3. MCP 用户凭证兑换器 — 与 FastAPI lifespan（app/main.py）对齐
    try:
        from agent_flow_harness.mcp.loader import set_credential_resolver

        from app.engine.mcp.user_credential_resolver import UserCredentialResolver

        set_credential_resolver(UserCredentialResolver())
        logger.info("mcp_credential_resolver_injected", process="celery_worker")
    except Exception as exc:
        # fail-closed 已兜底：外部任务的 MCP 调用会被拦截器拒绝而非静默
        # 降级为内部静态凭证；内部任务不受影响。
        logger.error("mcp_resolver_init_failed", error=str(exc))

    # 4. 沙盒镜像预拉取 — daemon 线程，不阻塞 worker 启动
    if settings.SANDBOX_PREPULL_IMAGE:
        from app.engine.harness_integration.sandbox_prepull import ensure_sandbox_image

        threading.Thread(target=ensure_sandbox_image, name="sandbox-prepull", daemon=True).start()


@task_prerun.connect
def _check_license_and_inject_request_id(task_id=None, **_kwargs: object) -> None:
    """task 执行前：license 复核（分散校验点）+ ``request_id`` 注入。

    license 复核读 60s TTL 缓存——纯内存判断，单 task 开销可忽略；
    worker 启动后 license 被撤/到期，下一个 task 即拒绝执行（到期停拉）。
    """
    from app.core import license as lic

    if not _license_contract_ok():
        raise lic.LicenseError("LIC_E_INTEGRITY")
    _lic = lic.evaluate_license()
    if _lic.enforced and not _lic.ok:
        raise lic.LicenseError(_lic.code)
    if not _license_module_sha_ok():
        raise lic.LicenseError("LIC_E_INTEGRITY")

    from app.api.middleware.request_id import request_id_var

    rid = (task_id or "-")[:8]
    request_id_var.set(rid)
    logger.contextualize(request_id=rid).__enter__()


__all__ = ["celery_app"]
