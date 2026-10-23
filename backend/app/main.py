"""FastAPI application entry point."""
import asyncio
import pathlib
from contextlib import asynccontextmanager

# Cython 兼容补丁必须最先安装（在任何 pydantic 模型类创建之前）——
# 编译产物运行时它把 cyfunction 追加进 pydantic 忽略类型表。
# （from-import 形式：避免 ``app`` 名字被包遮蔽，下方 ``app = FastAPI()``）
from app import _cycompat as _cycompat_module

_cycompat_module.install()

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.middleware.exception_mw import ExceptionMiddleware
from app.api.middleware.license_mw import LicenseMiddleware
from app.api.middleware.logging_mw import LoggingMiddleware
from app.api.middleware.request_id import RequestIDMiddleware
from app.api.middleware.scoped_cors import ScopedCorsMiddleware, parse_cors_origins
from app.api.v1.ext import ExtApiStatsMiddleware
from app.api.v1.router import api_v1_router
from app.core.bootstrap import background_boot, init_critical_path, shutdown
from app.core.config import settings
from app.core.logging import setup_logging

# Initialize structured logging before app creation
setup_logging()


async def _license_revalidation_loop() -> None:
    """运行期本地复验（默认 30 分钟）：运行中途到期/文件被篡改时刷新缓存，
    LicenseMiddleware 与各分散校验点随后即拒绝业务请求。"""
    from loguru import logger

    from app.core import license as lic
    while True:
        await asyncio.sleep(settings.LICENSE_RECHECK_INTERVAL_SECONDS)
        try:
            status = lic.evaluate_license(force=True)
            if not status.ok:
                logger.warning("license_recheck_failed code={}", status.code)
        except Exception as exc:  # noqa: BLE001 - 复验循环不许死
            logger.error("license_recheck_error error={}", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage startup/shutdown lifecycle for external connections.

    Startup is split into:
    1. **Critical path** (awaited): checkpointer, notification, event bridge.
    2. **Background boot** (create_task): indexes, schedulers, recovery,
       channel connections — deferred so the first request isn't blocked.

    License：启动即校验但**不阻止启动**（未激活降级模式——后端要能起来
    提供激活向导，业务 API 由 LicenseMiddleware 拦截）；另起 30min 复验
    循环处理运行中途到期。
    """
    from loguru import logger

    # License startup check（降级模式：失败只告警，不 raise）。
    from app.core import license as lic

    _lic_status = lic.evaluate_license(force=True)
    if _lic_status.enforced and not _lic_status.ok:
        logger.warning("license_gate_active code={}", _lic_status.code)

    # Critical path — must complete before serving requests.
    await init_critical_path()

    # Inject MCP credential resolver into harness（统一凭证兑换）。
    # harness 保持无 DB 依赖，app 层在此注入实现。外部路径（/ext/*）的 MCP
    # 调用会经兑换器按用户绑定凭证；内部路径（JWT 测试）不受影响。
    from agent_flow_harness.mcp.loader import set_credential_resolver

    from app.engine.mcp.user_credential_resolver import UserCredentialResolver

    set_credential_resolver(UserCredentialResolver())

    # 沙盒镜像预拉取 — daemon 线程执行（阻塞 I/O 不占事件循环），首笔沙盒
    # 执行免付整镜像 pull 耗时。内部自捕获异常，失败不阻断启动。
    if settings.SANDBOX_PREPULL_IMAGE:
        import threading

        from app.engine.harness_integration.sandbox_prepull import ensure_sandbox_image

        threading.Thread(target=ensure_sandbox_image, name="sandbox-prepull", daemon=True).start()

    # Background boot — indexes/schedulers/recovery/channels.
    # Store the task reference on app.state to prevent GC, and to allow
    # graceful shutdown ordering (cancel before closing DB clients).
    boot_task = asyncio.create_task(background_boot())
    app.state._boot_task = boot_task

    # Capture schedulers when background boot completes (best-effort;
    # if it hasn't finished by shutdown, we cancel it).
    app.state._scheduler = None
    app.state._trigger_scheduler = None

    async def _capture_schedulers():
        try:
            scheduler, trigger_scheduler = await boot_task
            app.state._scheduler = scheduler
            app.state._trigger_scheduler = trigger_scheduler
        except Exception as exc:
            from loguru import logger
            logger.error("background_boot_failed error={}", exc)

    asyncio.create_task(_capture_schedulers())

    # License 周期复验（引用挂 app.state 防 GC，随 shutdown 取消）。
    app.state._license_recheck_task = asyncio.create_task(_license_revalidation_loop())

    yield

    # Shutdown — cancel background boot if still running, then graceful stop.
    if not boot_task.done():
        boot_task.cancel()
    app.state._license_recheck_task.cancel()
    await shutdown(app.state._scheduler, app.state._trigger_scheduler)


app = FastAPI(
    title=settings.APP_NAME,
    description="MEPER Agent - AI Agent orchestration platform",
    version="0.1.0",
    docs_url="/api/v1/docs",
    redoc_url="/api/v1/redoc",
    openapi_url="/api/v1/openapi.json",
    lifespan=lifespan,
)

# Middleware 顺序（Starlette 语义：**最后** add 的在最外层、请求时最先执行）。
# 按 add 顺序 = 内→外书写，实际请求链为：
#   ScopedCors → RequestID → Exception → ExtApiStats → Logging → 路由
# 设计理由：
# - CORS 最外：preflight 短路；错误信封也能带上 CORS 头（浏览器才读得到）。
# - RequestID 次外：请求进入即分配 id；错误信封响应会带上 X-Request-ID。
# - Exception 居中兜底：捕获所有内层中间件与路由的异常，统一错误信封。
# - Logging 最内：完整覆盖内层耗时；能观察到原始异常（error_raised 分支）。
app.add_middleware(LoggingMiddleware)
app.add_middleware(ExtApiStatsMiddleware)
app.add_middleware(ExceptionMiddleware)
app.add_middleware(RequestIDMiddleware)
app.add_middleware(
    ScopedCorsMiddleware,
    allow_origins=parse_cors_origins(settings.CORS_ORIGINS),
)
# License 闸门放最内层（最先 add）：业务路由前最后一步，白名单放行的
# 激活向导端点仍能享受外层日志/错误信封能力。
app.add_middleware(LicenseMiddleware)

# API routes
app.include_router(api_v1_router, prefix="/api/v1")

# Agent 头像静态目录（无鉴权读取，<img src> 直接用；上传端点仍鉴权）。
_avatars_dir = pathlib.Path(settings.AVATARS_CONTAINER_DIR)
_avatars_dir.mkdir(parents=True, exist_ok=True)
app.mount("/api/v1/agent-avatars", StaticFiles(directory=str(_avatars_dir)), name="agent-avatars")

# Skill (Tool) 头像静态目录（同上，独立目录避免与 Agent 混淆）。
_skill_avatars_dir = pathlib.Path(settings.SKILL_AVATARS_CONTAINER_DIR)
_skill_avatars_dir.mkdir(parents=True, exist_ok=True)
app.mount("/api/v1/skill-avatars", StaticFiles(directory=str(_skill_avatars_dir)), name="skill-avatars")


# ── 全原生部署：FastAPI 直接托管前端产物（零 Docker/Caddy）──────────────
# 静态页面与激活向导必须未激活也能打开（业务保护在 /api/* 的 license
# middleware，不在页面层）。挂载在全部 API 路由之后，不影响 /api、/ws。
if settings.AGENT_FLOW_SERVE_STATIC and settings.AGENT_FLOW_WEB_DIR:
    _web_dir = pathlib.Path(settings.AGENT_FLOW_WEB_DIR)
    if (_web_dir / "index.html").exists():
        _client_dir = _web_dir / "client"
        if _client_dir.exists():
            app.mount(
                "/client",
                StaticFiles(directory=str(_client_dir), html=True),
                name="client-spa",
            )

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa_fallback(full_path: str):
            """SPA fallback：非 API/静态资产路径回退 studio 的 index.html。

            仅在前面所有路由（API/mounts）都未命中时到达——FastAPI 按注册
            顺序匹配，/api、/ws、/assets、/client 均已在前。
            """
            from fastapi.responses import FileResponse

            candidate = _web_dir / full_path
            if full_path and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(_web_dir / "index.html")


@app.get("/", tags=["root"])
async def root() -> dict[str, str]:
    """Root endpoint - redirects users to docs."""
    return {
        "message": f"Welcome to {settings.APP_NAME}",
        "docs": "/api/v1/docs",
        "redoc": "/api/v1/redoc",
    }


@app.get("/health", tags=["health"])
async def health_check() -> dict[str, str]:
    """Liveness probe (also exposed at /api/v1/health for consistency)."""
    return {"status": "ok"}
