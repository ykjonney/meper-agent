"""API schemas for notification endpoints."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from app.models.notification import NotificationKind


class NotificationResponse(BaseModel):
    """Single notification in API responses."""

    id: str
    user_id: str
    kind: NotificationKind
    title: str
    body: str
    related_task_id: str | None = None
    related_workflow_id: str | None = None
    read: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class NotificationListResponse(BaseModel):
    """Paginated notification list response."""

    total: int
    page: int
    page_size: int
    items: list[NotificationResponse]


class UnreadCountResponse(BaseModel):
    """Unread notification count."""

    count: int
