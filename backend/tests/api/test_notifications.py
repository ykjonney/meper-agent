"""Tests for notification REST API endpoints."""
import pytest
from unittest.mock import patch, AsyncMock

from app.main import app


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    return TestClient(app)


@pytest.fixture
def override_auth():
    """Override get_current_user to return a test user."""
    from app.core.security import get_current_user
    from app.models.user import UserStatus
    from app.schemas.user import UserResponse

    user = UserResponse(
        id="user_test",
        username="testuser",
        email="test@test.com",
        role="admin",
        status=UserStatus.ACTIVE,
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
        permissions=[],
    )
    app.dependency_overrides[get_current_user] = lambda: user
    yield user
    app.dependency_overrides.clear()


class TestNotificationAPI:
    async def test_list_notifications(self, client, override_auth):
        with patch("app.api.v1.notifications.NotificationRepository") as MockRepo:
            repo_instance = AsyncMock()
            MockRepo.return_value = repo_instance
            repo_instance.list_by_user.return_value = {
                "total": 0, "page": 1, "page_size": 20, "items": []
            }
            resp = client.get("/api/v1/notifications")
            assert resp.status_code == 200
            data = resp.json()
            assert data["total"] == 0
            assert data["items"] == []

    async def test_unread_count(self, client, override_auth):
        with patch("app.api.v1.notifications.NotificationRepository") as MockRepo:
            repo_instance = AsyncMock()
            MockRepo.return_value = repo_instance
            repo_instance.count_unread.return_value = 5
            resp = client.get("/api/v1/notifications/unread-count")
            assert resp.status_code == 200
            assert resp.json()["count"] == 5

    async def test_mark_read(self, client, override_auth):
        with patch("app.api.v1.notifications.NotificationRepository") as MockRepo:
            repo_instance = AsyncMock()
            MockRepo.return_value = repo_instance
            repo_instance.mark_read.return_value = None
            resp = client.patch("/api/v1/notifications/notif_xxx/read")
            assert resp.status_code == 200

    async def test_mark_all_read(self, client, override_auth):
        with patch("app.api.v1.notifications.NotificationRepository") as MockRepo:
            repo_instance = AsyncMock()
            MockRepo.return_value = repo_instance
            repo_instance.mark_all_read.return_value = None
            resp = client.patch("/api/v1/notifications/read-all")
            assert resp.status_code == 200
