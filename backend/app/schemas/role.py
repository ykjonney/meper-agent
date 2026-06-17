"""Role-related Pydantic schemas for API request/response."""
from __future__ import annotations

from pydantic import BaseModel, Field

from app.models.role import RoleType


class RoleCreate(BaseModel):
    """Schema for creating a new custom role."""

    name: str = Field(..., min_length=1, max_length=50, pattern=r"^[a-z][a-z0-9_]*$", description="Unique role identifier (lowercase, alphanumeric)")
    display_name: str = Field(..., min_length=1, max_length=100, description="Display name")
    description: str = Field(default="", max_length=500)
    permissions: list[str] = Field(default_factory=list, description="List of permission keys")


class RoleUpdate(BaseModel):
    """Schema for updating an existing role (partial update — PATCH)."""

    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    permissions: list[str] | None = Field(default=None, description="Replace entire permissions list")


class RoleResponse(BaseModel):
    """Role data returned in API responses."""

    id: str
    name: str
    display_name: str
    description: str
    role_type: RoleType
    permissions: list[str]
    created_at: str
    updated_at: str


class AllPermissionsResponse(BaseModel):
    """Response for the all-permissions endpoint — grouped permission keys."""

    permissions: list[str]
