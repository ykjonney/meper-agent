"""Health check endpoint - no auth required."""
from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health", summary="Liveness/readiness probe")
async def health_check() -> dict[str, str]:
    """Return 200 OK if the process is running."""
    return {"status": "ok"}
