"""Credential data model — encrypted secrets for tool authentication.

Credentials are stored separately from tools and referenced by ``credential_id``.
This allows one credential (e.g. a GitHub token) to be shared across multiple
tools, and rotated without modifying tool configurations.

Sensitive data is encrypted with AES-256-GCM (``app.core.crypto``).
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel as PydanticBaseModel
from pydantic import ConfigDict, Field

from app.models.base import generate_id, utc_now

CredentialType = Literal["api_key", "bearer", "basic", "oauth2"]


class Credential(PydanticBaseModel):
    """MongoDB credential document model.

    The ``credential_data_encrypted`` field stores the AES-256-GCM encrypted
    JSON string of the actual secret payload (e.g. ``{"token": "ghp_xxx"}``).
    It is never returned to the client in plaintext — API responses use
    ``masked_data`` instead.
    """

    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(default_factory=lambda: generate_id("cred"), alias="_id")
    user_id: str = Field(..., description="Owner user ID")
    name: str = Field(..., min_length=1, max_length=100, description="Human-readable name")
    type: CredentialType = Field(default="api_key", description="Credential type")
    credential_data_encrypted: str = Field(
        default="",
        description="AES-256-GCM encrypted JSON of the secret payload",
    )
    created_at: str = Field(default_factory=lambda: utc_now().isoformat())
