"""Request ID middleware - injects a short UUID4 into each request and response header."""
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Generate or propagate X-Request-ID for full-chain traceability.

    - Inbound: respect client-provided X-Request-ID (for distributed tracing)
    - Outbound: always emit X-Request-ID in response header
    - Available downstream via `request.state.request_id`
    """

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", uuid.uuid4().hex[:8])
        request.state.request_id = request_id
        response: Response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
