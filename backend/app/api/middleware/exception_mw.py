"""Global exception middleware - converts exceptions to the unified error response format."""
import traceback
from datetime import UTC, datetime

from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.errors import AppError


def _error_response(
    code: str,
    message: str,
    status_code: int,
    request_id: str,
    details: dict | None = None,
) -> JSONResponse:
    """Build the unified error response envelope."""
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": details or {},
                "request_id": request_id,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        },
    )


class ExceptionMiddleware(BaseHTTPMiddleware):
    """Catch AppError and unhandled exceptions, emit the unified error envelope."""

    async def dispatch(self, request: Request, call_next):
        try:
            response: Response = await call_next(request)
            return response
        except AppError as exc:
            request_id = getattr(request.state, "request_id", "-")
            logger.bind(request_id=request_id).warning(
                "app_error",
                method=request.method,
                path=str(request.url.path),
                code=exc.code,
                message=exc.message,
                status_code=exc.status_code,
                details=exc.details,
            )
            return _error_response(
                code=exc.code,
                message=exc.message,
                status_code=exc.status_code,
                request_id=request_id,
                details=exc.details,
            )
        except Exception as exc:  # noqa: BLE001 - last-resort handler
            request_id = getattr(request.state, "request_id", "-")
            logger.bind(request_id=request_id).error(
                "unhandled_exception",
                method=request.method,
                path=str(request.url.path),
                error=str(exc),
                error_type=type(exc).__name__,
                traceback=traceback.format_exc(),
            )
            return _error_response(
                code="INTERNAL_ERROR",
                message="An unexpected error occurred",
                status_code=500,
                request_id=request_id,
            )
