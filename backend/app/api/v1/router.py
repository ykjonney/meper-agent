"""V1 API router aggregator."""
from fastapi import APIRouter

from app.api.v1.admin import router as admin_router
from app.api.v1.agents import router as agents_router
from app.api.v1.auth import router as auth_router
from app.api.v1.health import router as health_router
from app.api.v1.mcp import router as mcp_router
from app.api.v1.models import router as models_router
from app.api.v1.sessions import router as sessions_router
from app.api.v1.tools import router as tools_router

api_v1_router = APIRouter()
api_v1_router.include_router(health_router)
api_v1_router.include_router(auth_router)
api_v1_router.include_router(admin_router)
api_v1_router.include_router(agents_router)
api_v1_router.include_router(models_router)
api_v1_router.include_router(sessions_router)
api_v1_router.include_router(tools_router)
api_v1_router.include_router(mcp_router)
