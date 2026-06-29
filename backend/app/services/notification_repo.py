"""Notification CRUD repository — MongoDB persistence layer."""
from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.pagination import calc_skip
from app.models.notification import Notification

COLLECTION = "notifications"


class NotificationRepository:
    """MongoDB repository for Notification documents."""

    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._db = db

    def _collection(self):
        return self._db[COLLECTION]

    async def insert(self, notification: Notification) -> bool:
        """Insert a new notification.

        Returns:
            True if a new document was inserted, False if a duplicate was
            skipped (same ``user_id`` + ``related_task_id`` + ``kind``).
        """
        if notification.related_task_id:
            existing = await self._collection().find_one({
                "user_id": notification.user_id,
                "related_task_id": notification.related_task_id,
                "kind": notification.kind.value,
            })
            if existing:
                return False
        doc = notification.model_dump(by_alias=True)
        await self._collection().insert_one(doc)
        return True

    async def list_by_user(
        self,
        user_id: str,
        *,
        page: int = 1,
        page_size: int = 20,
        read: bool | None = None,
        kind: str | None = None,
    ) -> dict:
        """List notifications for a user with pagination and optional filters."""
        query: dict = {"user_id": user_id}
        if read is not None:
            query["read"] = read
        if kind is not None:
            query["kind"] = kind

        total = await self._collection().count_documents(query)
        cursor = (
            self._collection()
            .find(query)
            .sort("created_at", -1)
            .skip(calc_skip(page, page_size))
            .limit(page_size)
        )
        items = await cursor.to_list(length=page_size)
        for item in items:
            if "_id" in item:
                item["id"] = item.pop("_id")
        return {"total": total, "page": page, "page_size": page_size, "items": items}

    async def count_unread(self, user_id: str) -> int:
        """Count unread notifications for a user."""
        return await self._collection().count_documents({"user_id": user_id, "read": False})

    async def mark_read(self, user_id: str, notification_id: str) -> None:
        """Mark a single notification as read."""
        await self._collection().update_one(
            {"_id": notification_id, "user_id": user_id},
            {"$set": {"read": True}},
        )

    async def mark_all_read(self, user_id: str) -> None:
        """Mark all notifications as read for a user."""
        await self._collection().update_many(
            {"user_id": user_id, "read": False},
            {"$set": {"read": True}},
        )
