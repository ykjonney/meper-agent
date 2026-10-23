"""Common Pydantic schemas: pagination, error response."""
from typing import Any

from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    """Unified error response body (matches `ExceptionMiddleware` output)."""

    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    request_id: str = ""
    timestamp: str = ""


class PaginatedResponse[T](BaseModel):
    """Standard paginated response envelope."""

    total: int = 0
    page: int = 1
    page_size: int = 20
    items: list[T] = Field(default_factory=list)
