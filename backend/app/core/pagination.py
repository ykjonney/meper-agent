"""Pagination helpers."""
from pydantic import BaseModel, Field


class PaginationParams(BaseModel):
    """Standard pagination query parameters."""

    page: int = Field(default=1, ge=1, description="Page number, 1-indexed")
    page_size: int = Field(default=20, ge=1, le=100, description="Items per page (1-100)")


class PaginatedResult[T](BaseModel):
    """Standard paginated response envelope."""

    total: int = 0
    page: int = 1
    page_size: int = 20
    items: list[T] = Field(default_factory=list)


def calc_skip(page: int, page_size: int) -> int:
    """Calculate the MongoDB skip offset for a given page."""
    return (page - 1) * page_size
