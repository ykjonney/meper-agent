"""Credential request/response schemas."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.models.credential import CredentialType


class CredentialCreate(BaseModel):
    """Request body for creating a credential."""

    name: str = Field(..., min_length=1, max_length=100, description="Human-readable name")
    type: CredentialType = Field(default="api_key")
    data: dict[str, Any] = Field(
        ...,
        description=(
            "Secret payload, e.g. {\"token\": \"ghp_xxx\"} or "
            "{\"username\": \"x\", \"password\": \"y\"}. "
            "Will be encrypted before storage."
        ),
    )


class CredentialResponse(BaseModel):
    """Response — never contains the plaintext secret, only masked."""

    id: str = Field(..., alias="_id")
    user_id: str
    name: str
    type: CredentialType
    masked_data: dict[str, str] = Field(
        default_factory=dict,
        description="Masked representation of the secret payload",
    )
    created_at: str


class CredentialListResponse(BaseModel):
    items: list[CredentialResponse]
    total: int
