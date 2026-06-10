"""User data model for MongoDB."""
from enum import StrEnum

from pydantic import BaseModel, Field

from app.models.base import generate_id, utc_now


class UserRole(StrEnum):
    """User role enum — maps to the 4-role RBAC matrix (PRD FR-27)."""

    ADMIN = "admin"
    DEVELOPER = "developer"
    OPERATOR = "operator"
    VIEWER = "viewer"


class UserStatus(StrEnum):
    """User account status."""

    ACTIVE = "active"
    DISABLED = "disabled"


class User(BaseModel):
    """MongoDB user document model.

    IMPORTANT: `password_hash` must never be serialized to API responses.
    Use UserResponse for API output and UserInDB for internal handling.
    """

    id: str = Field(default_factory=lambda: generate_id("user"), alias="_id")
    username: str = Field(..., min_length=1, max_length=50)
    email: str = Field(..., max_length=255, pattern=r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
    password_hash: str = Field(..., exclude=True)  # Never serialize
    role: UserRole = Field(default=UserRole.VIEWER)
    status: UserStatus = Field(default=UserStatus.ACTIVE)
    created_at: str = Field(default_factory=lambda: utc_now().isoformat())
    updated_at: str = Field(default_factory=lambda: utc_now().isoformat())
    last_login_at: str | None = Field(default=None)

    model_config = {"populate_by_name": True}
