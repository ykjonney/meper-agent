"""Webhook Pydantic schemas for API request/response."""
from __future__ import annotations

from pydantic import BaseModel, Field

from app.models.webhook import WEBHOOK_EVENTS


class WebhookCreate(BaseModel):
    """Create a new Webhook configuration."""

    name: str = Field(..., min_length=1, max_length=200, description="显示名称")
    url: str = Field(..., min_length=1, max_length=2000, description="回调 URL")
    events: list[str] = Field(
        ...,
        min_length=1,
        description=f"订阅事件列表，可选: {', '.join(WEBHOOK_EVENTS)}",
    )
    api_key_id: str | None = Field(default=None, description="绑定 API Key（可选）")


class WebhookUpdate(BaseModel):
    """Update a Webhook configuration."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    url: str | None = Field(default=None, min_length=1, max_length=2000)
    events: list[str] | None = None
    api_key_id: str | None = None
    status: str | None = None


class WebhookResponse(BaseModel):
    """Webhook configuration returned in list/detail responses."""

    id: str
    name: str
    url: str
    events: list[str]
    api_key_id: str | None
    status: str
    created_at: str
    updated_at: str


class WebhookListResponse(BaseModel):
    """Paginated Webhook list."""

    items: list[WebhookResponse]
    total: int
    page: int
    page_size: int


class WebhookTestResult(BaseModel):
    """Result of a test webhook delivery."""

    success: bool
    status_code: int | None = None
    error: str | None = None
    attempts: int = 1


class WebhookDeliveryLogResponse(BaseModel):
    """Delivery log entry."""

    id: str
    webhook_id: str
    event: str
    url: str
    status_code: int | None
    success: bool
    attempts: int
    error: str | None
    timestamp: str
