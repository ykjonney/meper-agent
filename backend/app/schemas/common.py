"""Common Pydantic schemas: pagination, error response."""
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

# TypeVar 传统写法而非 PEP 695 泛型类语法（class Foo[T]）——Cython（含 3.3）
# 不解析后者，交付构建（build_compiled.py）会整体失败。
T = TypeVar("T")


class ErrorResponse(BaseModel):
    """Unified error response body (matches `ExceptionMiddleware` output)."""

    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    request_id: str = ""
    timestamp: str = ""


class PaginatedResponse(BaseModel, Generic[T]):  # noqa: UP046 — Cython 不解析 PEP 695 泛型类，见上注释
    """Standard paginated response envelope."""

    total: int = 0
    page: int = 1
    page_size: int = 20
    items: list[T] = Field(default_factory=list)
