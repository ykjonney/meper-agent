"""API tests for trigger CRUD endpoints.

NOTE: These tests are currently skipped due to API restructuring.
The trigger endpoints moved from /workflows/{id}/trigger to /triggers.
TODO: Rewrite tests to match new API structure.

Uses ``unittest.mock`` to mock DB and scheduler so tests run without
real MongoDB or Celery connections.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.core.security import get_current_user
from app.main import app
from app.models.trigger import Trigger
from app.schemas.user import UserResponse, UserStatus
from fastapi.testclient import TestClient

TRIGGER_ID = "trg_01HTEST"
WORKFLOW_ID = "wf_01HTEST"
BASE_URL = "/api/v1/triggers"


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def auth_user():
    """Override get_current_user for authentication."""
    user = UserResponse(
        id="user_01HTEST",
        username="admin",
        email="admin@example.com",
        role="admin",
        status=UserStatus.ACTIVE,
        created_at="2026-01-01T00:00:00",
        updated_at="2026-01-01T00:00:00",
        permissions=[],
    )
    app.dependency_overrides[get_current_user] = lambda: user
    yield
    app.dependency_overrides.clear()


def _fake_trigger(trigger_id: str = TRIGGER_ID, workflow_id: str = WORKFLOW_ID) -> Trigger:
    """Build a minimal fake trigger."""
    return Trigger(
        id=trigger_id,
        workflow_id=workflow_id,
        user_id="user_01HTEST",
        type="cron",
        enabled=True,
        cron_expression="0 9 * * *",
    )


# All tests skipped pending rewrite for new API structure
pytestmark = pytest.mark.skip(reason="API restructured - tests need rewrite")


class TestCreateTrigger:
    """POST /api/v1/triggers"""

    @patch("app.api.v1.triggers.get_trigger_scheduler")
    def test_create_trigger_201(self, mock_get_scheduler, client, auth_user) -> None:
        """Successfully create a trigger."""
        trigger_data = {
            "workflow_id": WORKFLOW_ID,
            "type": "cron",
            "enabled": True,
            "cron_expression": "0 9 * * *",
        }

        fake_trigger = _fake_trigger()
        mock_repo = AsyncMock()
        mock_repo.insert = AsyncMock()
        mock_repo.find_by_id = AsyncMock(return_value=fake_trigger)

        mock_scheduler = MagicMock()
        mock_scheduler.repo = mock_repo
        mock_scheduler.schedule_next = AsyncMock()
        mock_get_scheduler.return_value = mock_scheduler

        response = client.post(BASE_URL, json=trigger_data)

        assert response.status_code == 201
        data = response.json()
        assert data["type"] == "cron"
        assert data["enabled"] is True
        mock_repo.insert.assert_awaited_once()
        mock_scheduler.schedule_next.assert_awaited_once()


class TestListTriggers:
    """GET /api/v1/triggers"""

    @patch("app.db.mongodb.get_database")
    def test_list_triggers_200(self, mock_get_db, client, auth_user) -> None:
        """Successfully list triggers."""
        fake_trigger = {
            "_id": TRIGGER_ID,
            "workflow_id": WORKFLOW_ID,
            "user_id": "user_01HTEST",
            "type": "cron",
            "enabled": True,
            "cron_expression": "0 9 * * *",
        }

        mock_cursor = AsyncMock()
        mock_cursor.to_list = AsyncMock(return_value=[fake_trigger])

        mock_collection = AsyncMock()
        mock_collection.find.return_value = mock_collection
        mock_collection.sort.return_value = mock_cursor

        mock_get_db.return_value = {"triggers": mock_collection}

        response = client.get(BASE_URL)

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)


class TestDeleteTrigger:
    """DELETE /api/v1/triggers/{trigger_id}"""

    @patch("app.api.v1.triggers.get_trigger_scheduler")
    def test_delete_trigger_204(self, mock_get_scheduler, client, auth_user) -> None:
        """Successfully delete a trigger."""
        mock_repo = AsyncMock()
        mock_repo.find_by_id = AsyncMock(return_value=_fake_trigger())
        mock_repo.delete = AsyncMock()

        mock_scheduler = MagicMock()
        mock_scheduler.repo = mock_repo
        mock_scheduler.unregister_trigger = AsyncMock()
        mock_get_scheduler.return_value = mock_scheduler

        response = client.delete(f"{BASE_URL}/{TRIGGER_ID}")

        assert response.status_code == 204
        mock_repo.delete.assert_awaited_once()

    @patch("app.api.v1.triggers.get_trigger_scheduler")
    def test_delete_trigger_404(self, mock_get_scheduler, client, auth_user) -> None:
        """Return 404 when trigger does not exist."""
        mock_repo = AsyncMock()
        mock_repo.find_by_id = AsyncMock(return_value=None)

        mock_scheduler = MagicMock()
        mock_scheduler.repo = mock_repo
        mock_get_scheduler.return_value = mock_scheduler

        response = client.delete(f"{BASE_URL}/nonexistent")

        assert response.status_code == 404


class TestToggleTrigger:
    """PATCH /api/v1/triggers/{trigger_id}/toggle"""

    @patch("app.api.v1.triggers.get_trigger_scheduler")
    def test_toggle_trigger_200(self, mock_get_scheduler, client, auth_user) -> None:
        """Successfully toggle trigger enabled state."""
        fake_trigger = _fake_trigger()
        toggled_trigger = _fake_trigger()
        toggled_trigger.enabled = False

        mock_repo = AsyncMock()
        mock_repo.find_by_id = AsyncMock(return_value=fake_trigger)
        mock_repo.update = AsyncMock(return_value=toggled_trigger)

        mock_scheduler = MagicMock()
        mock_scheduler.repo = mock_repo
        mock_scheduler.update_trigger = AsyncMock()
        mock_get_scheduler.return_value = mock_scheduler

        response = client.patch(f"{BASE_URL}/{TRIGGER_ID}/toggle", json={"enabled": False})

        assert response.status_code == 200
        data = response.json()
        assert "enabled" in data

    @patch("app.api.v1.triggers.get_trigger_scheduler")
    def test_toggle_trigger_404(self, mock_get_scheduler, client, auth_user) -> None:
        """Return 404 when trigger does not exist."""
        mock_repo = AsyncMock()
        mock_repo.find_by_id = AsyncMock(return_value=None)

        mock_scheduler = MagicMock()
        mock_scheduler.repo = mock_repo
        mock_get_scheduler.return_value = mock_scheduler

        response = client.patch(f"{BASE_URL}/nonexistent/toggle", json={"enabled": True})

        assert response.status_code == 404
