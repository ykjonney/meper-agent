"""API tests for trigger config CRUD endpoints.

Uses ``unittest.mock`` to mock DB and scheduler so tests run without
real MongoDB or Celery connections.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.core.security import get_current_user
from app.main import app
from app.schemas.user import UserResponse, UserStatus
from fastapi.testclient import TestClient

WORKFLOW_ID = "wf_01HTEST"
BASE_URL = f"/api/v1/workflows/{WORKFLOW_ID}/trigger"


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


def _fake_workflow_doc(trigger_config: dict | None = None) -> dict:
    """Build a minimal fake workflow document."""
    doc = {
        "_id": WORKFLOW_ID,
        "name": "Test Workflow",
        "description": "",
        "status": "draft",
        "version": 1,
        "nodes": [],
        "edges": [],
        "tags": [],
        "created_by": "user_01HTEST",
        "created_at": "2026-01-01T00:00:00",
        "updated_at": "2026-01-01T00:00:00",
    }
    if trigger_config is not None:
        doc["trigger_config"] = trigger_config
    return doc


def _mock_db_collection(doc: dict | None):
    """Create a mock MongoDB collection with common operations."""
    collection = AsyncMock()
    collection.find_one = AsyncMock(return_value=doc)
    collection.find_one_and_update = AsyncMock(return_value=doc)
    return collection


class TestCreateTrigger:
    """POST /api/workflows/{workflow_id}/trigger"""

    @patch("app.api.v1.workflows.get_trigger_scheduler")
    @patch("app.api.v1.workflows.get_database")
    def test_create_trigger_200(self, mock_get_db, mock_get_scheduler, client, auth_user) -> None:
        """Successfully create a trigger config."""
        trigger_data = {
            "type": "cron",
            "enabled": True,
            "cron_expression": "0 9 * * *",
        }
        fake_doc = _fake_workflow_doc(trigger_config=trigger_data)
        collection = _mock_db_collection(fake_doc)
        mock_get_db.return_value = {"workflows": collection}

        mock_scheduler = MagicMock()
        mock_scheduler.update_trigger = AsyncMock()
        mock_get_scheduler.return_value = mock_scheduler

        response = client.post(BASE_URL, json=trigger_data)

        assert response.status_code == 200
        data = response.json()
        assert data["type"] == "cron"
        assert data["enabled"] is True
        assert data["cron_expression"] == "0 9 * * *"
        mock_scheduler.update_trigger.assert_awaited_once_with(WORKFLOW_ID)

    @patch("app.api.v1.workflows.get_database")
    def test_create_trigger_404(self, mock_get_db, client, auth_user) -> None:
        """Return 404 when workflow does not exist."""
        collection = _mock_db_collection(None)
        mock_get_db.return_value = {"workflows": collection}

        response = client.post(BASE_URL, json={"type": "cron", "enabled": False})

        assert response.status_code == 404


class TestGetTrigger:
    """GET /api/workflows/{workflow_id}/trigger"""

    @patch("app.api.v1.workflows.get_database")
    def test_get_trigger_200(self, mock_get_db, client, auth_user) -> None:
        """Successfully get trigger config."""
        trigger_data = {
            "type": "cron",
            "enabled": True,
            "cron_expression": "0 9 * * *",
        }
        fake_doc = _fake_workflow_doc(trigger_config=trigger_data)
        collection = _mock_db_collection(fake_doc)
        mock_get_db.return_value = {"workflows": collection}

        response = client.get(BASE_URL)

        assert response.status_code == 200
        data = response.json()
        assert data["type"] == "cron"
        assert data["enabled"] is True

    @patch("app.api.v1.workflows.get_database")
    def test_get_trigger_404_workflow_not_found(self, mock_get_db, client, auth_user) -> None:
        """Return 404 when workflow does not exist."""
        collection = _mock_db_collection(None)
        mock_get_db.return_value = {"workflows": collection}

        response = client.get(BASE_URL)

        assert response.status_code == 404

    @patch("app.api.v1.workflows.get_database")
    def test_get_trigger_404_no_trigger_config(self, mock_get_db, client, auth_user) -> None:
        """Return 404 when workflow exists but has no trigger config."""
        fake_doc = _fake_workflow_doc(trigger_config=None)
        collection = _mock_db_collection(fake_doc)
        mock_get_db.return_value = {"workflows": collection}

        response = client.get(BASE_URL)

        assert response.status_code == 404


class TestDeleteTrigger:
    """DELETE /api/workflows/{workflow_id}/trigger"""

    @patch("app.api.v1.workflows.get_trigger_scheduler")
    @patch("app.api.v1.workflows.get_database")
    def test_delete_trigger_204(self, mock_get_db, mock_get_scheduler, client, auth_user) -> None:
        """Successfully delete trigger config."""
        fake_doc = _fake_workflow_doc(trigger_config=None)
        collection = _mock_db_collection(fake_doc)
        collection.find_one_and_update = AsyncMock(return_value=fake_doc)
        mock_get_db.return_value = {"workflows": collection}

        mock_scheduler = MagicMock()
        mock_scheduler.unregister_trigger = AsyncMock()
        mock_get_scheduler.return_value = mock_scheduler

        response = client.delete(BASE_URL)

        assert response.status_code == 204
        mock_scheduler.unregister_trigger.assert_awaited_once_with(WORKFLOW_ID)

    @patch("app.api.v1.workflows.get_database")
    def test_delete_trigger_404(self, mock_get_db, client, auth_user) -> None:
        """Return 404 when workflow does not exist."""
        collection = _mock_db_collection(None)
        mock_get_db.return_value = {"workflows": collection}

        response = client.delete(BASE_URL)

        assert response.status_code == 404


class TestToggleTrigger:
    """PATCH /api/workflows/{workflow_id}/trigger/toggle"""

    @patch("app.api.v1.workflows.get_trigger_scheduler")
    @patch("app.api.v1.workflows.get_database")
    def test_toggle_trigger_200(self, mock_get_db, mock_get_scheduler, client, auth_user) -> None:
        """Successfully toggle trigger enabled state."""
        trigger_data = {
            "type": "cron",
            "enabled": False,
            "cron_expression": "0 9 * * *",
        }
        # After toggle: enabled = True
        toggled_doc = _fake_workflow_doc(trigger_config={
            **trigger_data,
            "enabled": True,
        })
        collection = _mock_db_collection(_fake_workflow_doc(trigger_config=trigger_data))
        collection.find_one_and_update = AsyncMock(return_value=toggled_doc)
        mock_get_db.return_value = {"workflows": collection}

        mock_scheduler = MagicMock()
        mock_scheduler.update_trigger = AsyncMock()
        mock_get_scheduler.return_value = mock_scheduler

        response = client.patch(f"{BASE_URL}/toggle", json={"enabled": True})

        assert response.status_code == 200
        data = response.json()
        assert data["enabled"] is True
        mock_scheduler.update_trigger.assert_awaited_once_with(WORKFLOW_ID)

    @patch("app.api.v1.workflows.get_database")
    def test_toggle_trigger_404(self, mock_get_db, client, auth_user) -> None:
        """Return 404 when workflow does not exist."""
        collection = _mock_db_collection(None)
        mock_get_db.return_value = {"workflows": collection}

        response = client.patch(f"{BASE_URL}/toggle", json={"enabled": True})

        assert response.status_code == 404
