"""Request/response logging middleware."""
import time

from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class LoggingMiddleware(BaseHTTPMiddleware):
    """Log every HTTP request with method, path, status code, and elapsed time."""

    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        response: Response = await call_next(request)
        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)

        logger.bind(request_id=getattr(request.state, "request_id", "-")).info(
            "request_completed",
            method=request.method,
            path=str(request.url.path),
            status_code=response.status_code,
            elapsed_ms=elapsed_ms,
        )
        return response
