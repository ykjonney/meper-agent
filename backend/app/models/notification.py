"""Notification data model for MongoDB — persistent user notifications."""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from app.models.base import generate_id, utc_now


class NotificationKind(StrEnum):
    """Types of notifications that can be created."""

    TASK_FAILED = "task_failed"
    TASK_WAITING_HUMAN = "task_waiting_human"
    TASK_COMPLETED = "task_completed"


class Notification(BaseModel):
    """MongoDB Notification document.

    Follows the same pattern as Task — raw Pydantic model,
    serialized to dict for MongoDB insertion/update.
    """

    id: str = Field(default_factory=lambda: generate_id("notif"), alias="_id")
    user_id: str = Field(..., max_length=100)
    kind: NotificationKind
    title: str = Field(..., max_length=200)
    body: str = Field(default="", max_length=1000)
    related_task_id: str | None = Field(default=None, max_length=100)
    related_workflow_id: str | None = Field(default=None, max_length=100)
    read: bool = False
    created_at: datetime = Field(default_factory=utc_now)

    model_config = {"populate_by_name": True}
