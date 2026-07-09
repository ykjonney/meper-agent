"""Webhook configuration and delivery log data models."""
from __future__ import annotations

from pydantic import BaseModel, Field

from app.models.base import generate_id, utc_now

WEBHOOK_EVENTS = [
    "agent.completed",
    "agent.failed",
    "task.completed",
    "task.failed",
    "task.waiting_human",
]


class WebhookStatus:
    ACTIVE = "active"
    DISABLED = "disabled"


class Webhook(BaseModel):
    """Webhook configuration document stored in MongoDB."""

    id: str = Field(default_factory=lambda: generate_id("wh"), alias="_id")
    name: str = Field(..., min_length=1, max_length=200)
    url: str = Field(..., min_length=1, max_length=2000)
    secret: str = Field(..., min_length=16)
    events: list[str] = Field(default_factory=list)
    api_key_id: str | None = None
    status: str = Field(default=WebhookStatus.ACTIVE)
    created_at: str = Field(default_factory=lambda: utc_now().isoformat())
    updated_at: str = Field(default_factory=lambda: utc_now().isoformat())

    model_config = {"populate_by_name": True}


class WebhookDeliveryLog(BaseModel):
    """Record of a single webhook delivery attempt (with retries)."""

    id: str = Field(default_factory=lambda: generate_id("whl"), alias="_id")
    webhook_id: str
    event: str
    url: str
    status_code: int | None = None
    success: bool = False
    attempts: int = 0
    error: str | None = None
    timestamp: str = Field(default_factory=lambda: utc_now().isoformat())

    model_config = {"populate_by_name": True}
