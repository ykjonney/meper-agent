"""External API route group — API Key authenticated + rate-limited endpoints."""
from fastapi import APIRouter, Depends, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.status import HTTP_429_TOO_MANY_REQUESTS

from app.core.auth_apikey import ApiKeyPrincipal, get_api_key_principal
from app.core.rate_limiter import check_rate_limit
from app.services.api_key_stats_service import record_request

router = APIRouter(
    prefix="/ext",
    tags=["external-api"],
)


async def auth_and_rate_limit(
    request: Request,
    principal: ApiKeyPrincipal = Depends(get_api_key_principal),
) -> ApiKeyPrincipal:
    """Combined dependency: authenticate API Key then enforce rate limit.

    Runs after the request hits /api/v1/ext/* routes.
    1. Validates API Key (via get_api_key_principal — FastAPI-injected)
    2. Checks rate limit against Redis sliding window
    3. Stores metadata on request.state for downstream middleware
    """
    # Rate limit check
    allowed, remaining, reset_ts = await check_rate_limit(
        api_key_id=principal.key_id,
        limit=principal.rate_limit,
    )

    # Store on request.state for the response middleware
    request.state.api_key_id = principal.key_id
    request.state.rate_limit = principal.rate_limit
    request.state.rate_remaining = remaining
    request.state.rate_reset = reset_ts

    if not allowed:
        from app.core.errors import AppError

        raise AppError(
            code="RATE_LIMIT_EXCEEDED",
            message="请求频率超限，请稍后重试",
            status_code=HTTP_429_TOO_MANY_REQUESTS,
        )

    return principal


# Register sub-routers with combined auth + rate limit
from app.api.v1.ext import agents, tasks, workflows  # noqa: E402, F401

router.include_router(agents.router, prefix="")  # type: ignore[has-type]
router.include_router(workflows.router, prefix="")  # type: ignore[has-type]
router.include_router(tasks.router, prefix="")  # type: ignore[has-type]


class ExtApiStatsMiddleware(BaseHTTPMiddleware):
    """Post-response middleware: record API Key stats + inject rate limit headers."""

    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)

        # Only process /ext/ routes that went through auth
        api_key_id = getattr(request.state, "api_key_id", None)
        if api_key_id and str(request.url.path).startswith("/api/v1/ext/"):
            endpoint = _extract_endpoint(request)
            await record_request(
                api_key_id=api_key_id,
                endpoint=endpoint,
                status_code=response.status_code,
            )

        # Add rate limit headers when available
        if hasattr(request.state, "rate_limit"):
            response.headers["X-RateLimit-Limit"] = str(request.state.rate_limit)
            response.headers["X-RateLimit-Remaining"] = str(
                getattr(request.state, "rate_remaining", 0)
            )
            response.headers["X-RateLimit-Reset"] = str(
                getattr(request.state, "rate_reset", 0)
            )

        return response


def _extract_endpoint(request: Request) -> str:
    """Extract a logical endpoint name from the request path.

    Maps paths like /api/v1/ext/agents/xxx/invoke -> "agents:invoke"
    """
    path = str(request.url.path)

    if "/agents/" in path and path.endswith("/invoke/stream"):
        return "agents:invoke:stream"
    if "/agents/" in path and path.endswith("/invoke/resume"):
        return "agents:invoke:resume"
    if "/agents/" in path and path.endswith("/invoke"):
        return "agents:invoke"
    if "/agents/" in path and path.endswith("/sessions"):
        return "agents:sessions"
    if "/agents" in path:
        return "agents:read"
    if "/workflows/" in path and path.endswith("/invoke"):
        return "workflows:invoke"
    if "/workflows" in path:
        return "workflows:read"
    if "/tasks/" in path:
        return "tasks:read"
    return f"{request.method.lower()}:unknown"
