"""Role data model for MongoDB — dynamic RBAC roles."""
from enum import StrEnum

from pydantic import BaseModel, Field

from app.models.base import generate_id, utc_now


class RoleType(StrEnum):
    """Role type — system roles cannot be deleted, custom roles are user-created."""

    SYSTEM = "system"
    CUSTOM = "custom"


class Role(BaseModel):
    """MongoDB role document model."""

    id: str = Field(default_factory=lambda: generate_id("role"), alias="_id")
    name: str = Field(..., min_length=1, max_length=50, description="Unique role identifier")
    display_name: str = Field(..., min_length=1, max_length=100, description="Display name")
    description: str = Field(default="", max_length=500)
    role_type: RoleType = Field(default=RoleType.CUSTOM)
    permissions: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: utc_now().isoformat())
    updated_at: str = Field(default_factory=lambda: utc_now().isoformat())

    model_config = {"populate_by_name": True}
