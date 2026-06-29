"""Tests for NotificationRepository."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.models.notification import Notification, NotificationKind
from app.services.notification_repo import NotificationRepository


@pytest.fixture
def mock_db():
    """Create a mock database with collection."""
    db = MagicMock()
    collection = AsyncMock()
    db.__getitem__ = MagicMock(return_value=collection)
    return db, collection


class TestNotificationRepository:
    async def test_insert(self, mock_db):
        db, collection = mock_db
        repo = NotificationRepository(db)
        notif = Notification(
            user_id="user_abc",
            kind=NotificationKind.TASK_FAILED,
            title="失败",
            body="测试",
        )
        collection.find_one = AsyncMock(return_value=None)
        collection.insert_one.return_value = MagicMock(inserted_id=notif.id)
        result = await repo.insert(notif)
        assert result is True
        collection.insert_one.assert_awaited_once()

    async def test_insert_duplicate_skipped(self, mock_db):
        db, collection = mock_db
        repo = NotificationRepository(db)
        notif = Notification(
            user_id="user_abc",
            kind=NotificationKind.TASK_FAILED,
            title="失败",
            body="测试",
            related_task_id="task_001",
        )
        collection.find_one = AsyncMock(return_value={"_id": "existing"})
        result = await repo.insert(notif)
        assert result is False
        collection.insert_one.assert_not_awaited()

    async def test_list_by_user(self, mock_db):
        db, collection = mock_db
        repo = NotificationRepository(db)

        notif = Notification(
            user_id="user_abc",
            kind=NotificationKind.TASK_COMPLETED,
            title="完成",
            body="测试",
        )
        # Motor's find() is sync — returns a cursor. Override the AsyncMock default.
        collection.find = MagicMock()
        collection.find.return_value.sort.return_value.skip.return_value.limit.return_value.to_list = AsyncMock(
            return_value=[notif.model_dump(by_alias=True)]
        )
        collection.count_documents.return_value = 1

        result = await repo.list_by_user("user_abc", page=1, page_size=20)
        assert result["total"] == 1
        assert len(result["items"]) == 1

    async def test_count_unread(self, mock_db):
        db, collection = mock_db
        repo = NotificationRepository(db)
        collection.count_documents.return_value = 5
        count = await repo.count_unread("user_abc")
        assert count == 5
        collection.count_documents.assert_awaited_once_with({"user_id": "user_abc", "read": False})

    async def test_mark_read(self, mock_db):
        db, collection = mock_db
        repo = NotificationRepository(db)
        collection.update_one.return_value = MagicMock(modified_count=1)
        await repo.mark_read("user_abc", "notif_xxx")
        collection.update_one.assert_awaited_once()

    async def test_mark_all_read(self, mock_db):
        db, collection = mock_db
        repo = NotificationRepository(db)
        collection.update_many.return_value = MagicMock(modified_count=3)
        await repo.mark_all_read("user_abc")
        collection.update_many.assert_awaited_once()
