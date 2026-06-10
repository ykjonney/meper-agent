"""FastAPI exception handlers for AppError conversion.

Registered in main.py via middleware. This module also provides
a helper to register exception handlers on the app instance if needed.
"""
from datetime import UTC

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.errors import AppError


def register_exception_handlers(app: FastAPI) -> None:
    """Register AppError exception handlers on the FastAPI app.

    This provides an alternative to the middleware-based exception handling.
    The middleware approach (ExceptionMiddleware) is preferred for full-chain
    coverage, but these handlers ensure Pydantic/FastAPI validation errors
    are also caught.
    """

    @app.exception_handler(AppError)  # type: ignore[misc]
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        """Convert AppError into the unified error response envelope."""
        from datetime import datetime

        from loguru import logger

        request_id = getattr(request.state, "request_id", "-")
        logger.bind(request_id=request_id).warning(
            "app_error_via_handler",
            code=exc.code,
            message=exc.message,
            status_code=exc.status_code,
        )

        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                    "request_id": request_id,
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            },
        )
