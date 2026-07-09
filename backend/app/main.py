"""FastAPI application entry point."""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.middleware.exception_mw import ExceptionMiddleware
from app.api.middleware.logging_mw import LoggingMiddleware
from app.api.middleware.request_id import RequestIDMiddleware
from app.api.v1.ext import ExtApiStatsMiddleware
from app.api.v1.router import api_v1_router
from app.core.config import settings
from app.core.logging import setup_logging
from app.db.mongodb import close_mongodb_client
from app.db.redis import close_redis_client
from app.services.task_scheduler_service import get_scheduler
from app.services.trigger_scheduler_service import get_trigger_scheduler

# Initialize structured logging before app creation
setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage startup/shutdown lifecycle for external connections."""
    # Startup: connections are lazy-initialized on first use
    # Configure harness checkpointer with MongoDB (overrides the default
    # MemorySaver) so thread state persists across restarts.
    try:
        from agent_flow_harness import build_mongo_saver, configure_checkpointer

        from app.db.mongodb import get_mongodb_client

        saver = build_mongo_saver(
            client=get_mongodb_client().delegate,
            db_name=settings.MONGODB_DB_NAME,
        )
        configure_checkpointer(saver, overwrite=True)
    except Exception:
        pass  # Fall back to harness default MemorySaver

    # Start the Task scheduler for timed/scheduled workflow execution
    scheduler = get_scheduler()
    await scheduler.start()

    # Initialize Trigger repository and indexes
    from app.db.mongodb import get_database
    from app.services.trigger_repo import TriggerRepository

    trigger_repo = TriggerRepository(get_database())
    await trigger_repo.ensure_indexes()

    # Start the Trigger scheduler for cron/once workflow triggers
    trigger_scheduler = get_trigger_scheduler()
    trigger_scheduler.set_repo(trigger_repo)
    await trigger_scheduler.start()

    # Initialize system roles (idempotent — only inserts missing roles)
    from app.services.role_service import RoleService
    await RoleService.ensure_indexes()
    await RoleService.init_system_roles()

    # Initialize API Key indexes
    from app.services.api_key_service import ApiKeyService
    await ApiKeyService.ensure_indexes()

    # Recover waiting_human tasks from previous server instance
    from app.services.task_recovery import (
        recover_orphan_running_tasks,
        recover_waiting_human_tasks,
    )
    await recover_waiting_human_tasks()
    # Clean up running tasks orphaned by the previous process crash/restart.
    # run_and_persist executes workflows as in-process asyncio tasks, so a
    # process death orphans every running task — sweep them on startup.
    await recover_orphan_running_tasks()

    # Initialize notification service (bridges EventBus → WebSocket + MongoDB)
    from app.services.notification_service import NotificationService
    notification_service = NotificationService()
    notification_service.register()

    # Start Redis pub/sub bridge (bridges Celery worker events → FastAPI EventBus)
    from app.services.event_bridge import start_event_bridge_listener
    await start_event_bridge_listener()

    yield

    # Shutdown: gracefully close connections
    from app.services.event_bridge import stop_event_bridge_listener
    await stop_event_bridge_listener()
    await trigger_scheduler.stop()
    await scheduler.stop()
    await close_mongodb_client()
    await close_redis_client()


app = FastAPI(
    title=settings.APP_NAME,
    description="Agent Flow - AI Agent orchestration platform",
    version="0.1.0",
    docs_url="/api/v1/docs",
    redoc_url="/api/v1/redoc",
    openapi_url="/api/v1/openapi.json",
    lifespan=lifespan,
)

# Middleware order matters: outermost first (executed first on request, last on response)
app.add_middleware(ExceptionMiddleware)
app.add_middleware(LoggingMiddleware)
app.add_middleware(RequestIDMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.CORS_ORIGINS.split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID", "X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset"],
)
app.add_middleware(ExtApiStatsMiddleware)

# API routes
app.include_router(api_v1_router, prefix="/api/v1")


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
