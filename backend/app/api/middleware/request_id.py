"""Request ID middleware - injects a short UUID4 into each request and response header.

Uses a contextvar + ``logger.contextualize()`` so that ``request_id`` propagates
to **all** downstream code (services, engine, workers) without per-call
``logger.bind()``.  Any ``logger.xxx()`` called within the request scope
automatically carries the request_id.
"""
import contextvars
import uuid

from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

#: Global contextvar holding the current request_id.
#: Defaults to ``"-"`` outside a request scope (e.g. Celery tasks that
#: don't set one, startup code).
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default="-",
)


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Generate or propagate X-Request-ID for full-chain traceability.

    - Inbound: respect client-provided X-Request-ID (for distributed tracing)
    - Outbound: always emit X-Request-ID in response header
    - Available downstream via ``request.state.request_id`` **and** the
      ``request_id_var`` contextvar (for non-Request code paths)
    - ``logger.contextualize()`` ensures all logs within the request scope
      carry request_id automatically.
    """

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", uuid.uuid4().hex[:8])
        request.state.request_id = request_id
        token = request_id_var.set(request_id)
        try:
            with logger.contextualize(request_id=request_id):
                response: Response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            request_id_var.reset(token)
