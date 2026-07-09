"""Tests for Webhook CRUD, delivery, and event dispatch."""
import hashlib
import hmac
from unittest.mock import AsyncMock, patch

import pytest
from app.core.security import get_current_user, require_role
from app.main import app
from app.models.user import UserStatus
from app.schemas.user import UserResponse
from app.services.webhook_service import compute_signature
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def admin_user():
    return UserResponse(
        id="user_admin",
        username="admin",
        email="admin@test.com",
        role="admin",
        status=UserStatus.ACTIVE,
        created_at="2026-01-01T00:00:00",
        updated_at="2026-01-01T00:00:00",
    )


def _override_auth(admin_user):
    app.dependency_overrides[get_current_user] = lambda: admin_user
    app.dependency_overrides[require_role] = lambda: admin_user
    return lambda: app.dependency_overrides.clear()


def _make_webhook_doc(wh_id="wh_01", name="Test Webhook", status="active"):
    return {
        "_id": wh_id,
        "name": name,
        "url": "https://hooks.example.com/callback",
        "secret": "test_secret_key_12345678901234",
        "events": ["task.completed", "task.failed"],
        "api_key_id": None,
        "status": status,
        "created_at": "2026-01-01T00:00:00",
        "updated_at": "2026-01-01T00:00:00",
    }


# ---------------------------------------------------------------------------
# AC-1 & AC-2: Webhook CRUD
# ---------------------------------------------------------------------------


class TestWebhookCRUD:
    """Test webhook CRUD endpoints."""

    def test_create_webhook(self, client, admin_user) -> None:
        cleanup = _override_auth(admin_user)
        try:
            doc = _make_webhook_doc()
            with patch(
                "app.services.webhook_service.WebhookService.create_webhook",
                new=AsyncMock(return_value=doc),
            ):
                resp = client.post(
                    "/api/v1/webhooks",
                    json={
                        "name": "Test Webhook",
                        "url": "https://hooks.example.com/callback",
                        "events": ["task.completed", "task.failed"],
                    },
                )
            assert resp.status_code == 201
            data = resp.json()
            assert data["id"] == "wh_01"
            assert data["name"] == "Test Webhook"
            assert "secret" not in data  # secret should not be exposed
        finally:
            cleanup()

    def test_list_webhooks(self, client, admin_user) -> None:
        cleanup = _override_auth(admin_user)
        try:
            hooks = [_make_webhook_doc(), _make_webhook_doc("wh_02", "Hook 2")]
            with patch(
                "app.services.webhook_service.WebhookService.list_webhooks",
                new=AsyncMock(return_value=(hooks, 2)),
            ):
                resp = client.get("/api/v1/webhooks")
            assert resp.status_code == 200
            data = resp.json()
            assert data["total"] == 2
            assert len(data["items"]) == 2
            # Verify secret not in response
            for item in data["items"]:
                assert "secret" not in item
        finally:
            cleanup()

    def test_get_webhook(self, client, admin_user) -> None:
        cleanup = _override_auth(admin_user)
        try:
            with patch(
                "app.services.webhook_service.WebhookService.get_webhook",
                new=AsyncMock(return_value=_make_webhook_doc()),
            ):
                resp = client.get("/api/v1/webhooks/wh_01")
            assert resp.status_code == 200
            data = resp.json()
            assert data["id"] == "wh_01"
            assert "secret" not in data
        finally:
            cleanup()

    def test_get_webhook_not_found(self, client, admin_user) -> None:
        cleanup = _override_auth(admin_user)
        try:
            with patch(
                "app.services.webhook_service.WebhookService.get_webhook",
                new=AsyncMock(return_value=None),
            ):
                resp = client.get("/api/v1/webhooks/nonexistent")
            assert resp.status_code == 404
        finally:
            cleanup()

    def test_update_webhook(self, client, admin_user) -> None:
        cleanup = _override_auth(admin_user)
        try:
            doc = _make_webhook_doc()
            doc["name"] = "Updated Hook"
            with patch(
                "app.services.webhook_service.WebhookService.update_webhook",
                new=AsyncMock(return_value=doc),
            ):
                resp = client.put(
                    "/api/v1/webhooks/wh_01",
                    json={"name": "Updated Hook"},
                )
            assert resp.status_code == 200
            data = resp.json()
            assert data["name"] == "Updated Hook"
        finally:
            cleanup()

    def test_delete_webhook(self, client, admin_user) -> None:
        cleanup = _override_auth(admin_user)
        try:
            with patch(
                "app.services.webhook_service.WebhookService.delete_webhook",
                new=AsyncMock(return_value=True),
            ):
                resp = client.delete("/api/v1/webhooks/wh_01")
            assert resp.status_code == 204
        finally:
            cleanup()


# ---------------------------------------------------------------------------
# AC-5: HMAC-SHA256 signing
# ---------------------------------------------------------------------------


class TestHMACSigning:
    """Test webhook signature computation."""

    def test_compute_signature(self) -> None:
        secret = "my_secret"
        timestamp = 1720252800
        body = '{"event": "task.completed"}'

        sig = compute_signature(secret, timestamp, body)

        # Verify manually
        message = f"{timestamp}.{body}"
        expected = hmac.new(
            secret.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        assert sig == expected

    def test_signature_changes_with_different_secret(self) -> None:
        timestamp = 1720252800
        body = '{"event": "task.completed"}'

        sig1 = compute_signature("secret1", timestamp, body)
        sig2 = compute_signature("secret2", timestamp, body)

        assert sig1 != sig2

    def test_signature_changes_with_different_body(self) -> None:
        secret = "my_secret"
        timestamp = 1720252800

        sig1 = compute_signature(secret, timestamp, '{"event": "task.completed"}')
        sig2 = compute_signature(secret, timestamp, '{"event": "task.failed"}')

        assert sig1 != sig2


# ---------------------------------------------------------------------------
# AC-7: Delivery logging
# ---------------------------------------------------------------------------


class TestDeliveryLogging:
    """Test webhook delivery log recording."""

    def test_log_delivery(self) -> None:
        """Test that delivery logs are recorded correctly."""

        async def _run():
            with patch(
                "app.services.webhook_service.WebhookService._log_collection"
            ) as mock_col:
                mock_collection = AsyncMock()
                mock_col.return_value = mock_collection
                mock_collection.insert_one = AsyncMock()

                from app.services.webhook_service import WebhookService

                await WebhookService.log_delivery(
                    webhook_id="wh_01",
                    event="task.completed",
                    url="https://hooks.example.com",
                    status_code=200,
                    success=True,
                    attempts=1,
                )

                mock_collection.insert_one.assert_called_once()
                log_doc = mock_collection.insert_one.call_args[0][0]
                assert log_doc["webhook_id"] == "wh_01"
                assert log_doc["event"] == "task.completed"
                assert log_doc["success"] is True
                assert log_doc["attempts"] == 1

        import asyncio

        asyncio.run(_run())


# ---------------------------------------------------------------------------
# AC-8: Dispatch event
# ---------------------------------------------------------------------------


class TestDispatchEvent:
    """Test webhook event dispatch."""

    def test_dispatch_finds_matching_webhooks(self) -> None:
        """Test that dispatch finds webhooks subscribed to the event."""

        async def _run():
            webhooks = [_make_webhook_doc()]
            with (
                patch(
                    "app.services.webhook_service.WebhookService._collection"
                ) as mock_col,
                patch("app.services.webhook_service._enqueue_delivery") as mock_enqueue,
            ):
                # Motor's find() is sync, to_list() is async
                from unittest.mock import MagicMock

                mock_collection = MagicMock()
                mock_col.return_value = mock_collection
                mock_cursor = AsyncMock()
                mock_cursor.to_list = AsyncMock(return_value=webhooks)
                mock_collection.find.return_value = mock_cursor

                from app.services.webhook_service import WebhookService

                await WebhookService.dispatch_event(
                    "task.completed",
                    {"task_id": "task_01", "status": "completed"},
                )

                mock_enqueue.assert_called_once()
                call_args = mock_enqueue.call_args
                assert call_args[0][1] == "task.completed"  # event arg

        import asyncio

        asyncio.run(_run())

    def test_dispatch_ignores_unknown_events(self) -> None:
        """Test that unknown events are logged but not dispatched."""

        async def _run():
            with patch("app.services.webhook_service._enqueue_delivery") as mock_enqueue:
                from app.services.webhook_service import WebhookService

                await WebhookService.dispatch_event(
                    "unknown.event",
                    {"data": "test"},
                )

                mock_enqueue.assert_not_called()

        import asyncio

        asyncio.run(_run())


# ---------------------------------------------------------------------------
# AC-3: Event types
# ---------------------------------------------------------------------------


class TestEventTypes:
    """Test that all documented event types are supported."""

    def test_all_event_types_defined(self) -> None:
        from app.models.webhook import WEBHOOK_EVENTS

        expected = [
            "agent.completed",
            "agent.failed",
            "task.completed",
            "task.failed",
            "task.waiting_human",
        ]
        assert expected == WEBHOOK_EVENTS
