"""Notification REST API endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.core.security import get_current_user
from app.db.mongodb import get_database
from app.schemas.notification import NotificationListResponse, UnreadCountResponse
from app.schemas.user import UserResponse
from app.services.notification_repo import NotificationRepository

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=NotificationListResponse)
async def list_notifications(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    read: bool | None = Query(default=None),
    kind: str | None = Query(default=None),
    current_user: UserResponse = Depends(get_current_user),
):
    """List notifications for the current user with pagination."""
    repo = NotificationRepository(get_database())
    result = await repo.list_by_user(
        current_user.id,
        page=page,
        page_size=page_size,
        read=read,
        kind=kind,
    )
    return NotificationListResponse(**result)


@router.get("/unread-count", response_model=UnreadCountResponse)
async def unread_count(
    current_user: UserResponse = Depends(get_current_user),
):
    """Get unread notification count for the current user."""
    repo = NotificationRepository(get_database())
    count = await repo.count_unread(current_user.id)
    return UnreadCountResponse(count=count)


@router.patch("/{notification_id}/read")
async def mark_read(
    notification_id: str,
    current_user: UserResponse = Depends(get_current_user),
):
    """Mark a single notification as read."""
    repo = NotificationRepository(get_database())
    await repo.mark_read(current_user.id, notification_id)
    return {"ok": True}


@router.patch("/read-all")
async def mark_all_read(
    current_user: UserResponse = Depends(get_current_user),
):
    """Mark all notifications as read for the current user."""
    repo = NotificationRepository(get_database())
    await repo.mark_all_read(current_user.id)
    return {"ok": True}
