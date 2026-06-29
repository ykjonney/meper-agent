# backend/tests/services/test_notification_service.py
"""Tests for NotificationService — EventBus bridge."""
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.engine.events import Event, TaskEvent
from app.models.notification import NotificationKind
from app.services.notification_service import NotificationService


@pytest.fixture
def mock_deps():
    event_bus = MagicMock()
    ws_manager = AsyncMock()
    notification_repo = AsyncMock()

    service = NotificationService(
        event_bus=event_bus,
        ws_manager=ws_manager,
        notification_repo=notification_repo,
    )
    return service, event_bus, ws_manager, notification_repo


class TestNotificationService:
    def test_register_subscribes_to_event_bus(self, mock_deps):
        service, event_bus, *_ = mock_deps
        service.register()
        event_bus.subscribe.assert_called_once_with("*", service._on_event, handler_name="notification_service")

    async def test_task_event_pushes_status_update(self, mock_deps):
        service, _, ws_manager, _ = mock_deps

        # Mock task lookup — TaskService.get_task returns dict, not model
        mock_task = {
            "created_by": "user_abc",
            "workflow_id": "wf_xxx",
            "id": "task_123",
            "error": None,
        }
        service._get_task = AsyncMock(return_value=mock_task)

        event = TaskEvent(
            event_type="task.running",
            task_id="task_123",
            from_status="pending",
            to_status="running",
        )
        await service._on_event(event)

        ws_manager.send_to_user.assert_awaited_once()
        call_args = ws_manager.send_to_user.call_args
        assert call_args[0][0] == "user_abc"
        assert call_args[0][1]["type"] == "task_status"
        assert call_args[0][1]["data"]["task_id"] == "task_123"
        assert call_args[0][1]["data"]["status"] == "running"

    async def test_non_task_event_is_ignored(self, mock_deps):
        service, _, ws_manager, _ = mock_deps

        # Use a non-TaskEvent
        event = Event(event_type="workflow.started")
        await service._on_event(event)

        ws_manager.send_to_user.assert_not_awaited()

    async def test_task_event_without_task_id_is_ignored(self, mock_deps):
        service, _, ws_manager, _ = mock_deps

        event = TaskEvent(event_type="task.running", task_id="")
        await service._on_event(event)

        ws_manager.send_to_user.assert_not_awaited()

    async def test_task_failed_creates_notification(self, mock_deps):
        service, _, ws_manager, notification_repo = mock_deps

        mock_task = {
            "created_by": "user_abc",
            "workflow_id": "wf_xxx",
            "id": "task_123",
            "error": {"error_message": "LLM timeout"},
        }
        service._get_task = AsyncMock(return_value=mock_task)

        event = TaskEvent(
            event_type="task.failed",
            task_id="task_123",
            from_status="running",
            to_status="failed",
        )
        await service._on_event(event)

        # Should push task_status AND notification
        assert ws_manager.send_to_user.await_count == 2
        notification_repo.insert.assert_awaited_once()

        notif = notification_repo.insert.call_args[0][0]
        assert notif.kind == NotificationKind.TASK_FAILED

    async def test_task_completed_creates_notification(self, mock_deps):
        service, _, ws_manager, notification_repo = mock_deps

        mock_task = {
            "created_by": "user_abc",
            "workflow_id": "wf_xxx",
            "id": "task_123",
            "error": None,
        }
        service._get_task = AsyncMock(return_value=mock_task)

        event = TaskEvent(
            event_type="task.completed",
            task_id="task_123",
            from_status="running",
            to_status="completed",
        )
        await service._on_event(event)

        notif = notification_repo.insert.call_args[0][0]
        assert notif.kind == NotificationKind.TASK_COMPLETED

    async def test_task_waiting_human_creates_notification(self, mock_deps):
        service, _, ws_manager, notification_repo = mock_deps

        mock_task = {
            "created_by": "user_abc",
            "workflow_id": "wf_xxx",
            "id": "task_123",
            "error": None,
        }
        service._get_task = AsyncMock(return_value=mock_task)

        event = TaskEvent(
            event_type="task.waiting_human",
            task_id="task_123",
            from_status="running",
            to_status="waiting_human",
        )
        await service._on_event(event)

        notif = notification_repo.insert.call_args[0][0]
        assert notif.kind == NotificationKind.TASK_WAITING_HUMAN

    async def test_task_running_does_not_create_notification(self, mock_deps):
        service, _, _, notification_repo = mock_deps

        mock_task = {
            "created_by": "user_abc",
            "workflow_id": "wf_xxx",
            "id": "task_123",
            "error": None,
        }
        service._get_task = AsyncMock(return_value=mock_task)

        event = TaskEvent(
            event_type="task.running",
            task_id="task_123",
            from_status="pending",
            to_status="running",
        )
        await service._on_event(event)

        notification_repo.insert.assert_not_awaited()

    async def test_empty_created_by_skips_push(self, mock_deps):
        service, _, ws_manager, notification_repo = mock_deps

        mock_task = {
            "created_by": "",
            "workflow_id": "wf_xxx",
            "id": "task_123",
            "error": None,
        }
        service._get_task = AsyncMock(return_value=mock_task)

        event = TaskEvent(
            event_type="task.running",
            task_id="task_123",
            from_status="pending",
            to_status="running",
        )
        await service._on_event(event)

        ws_manager.send_to_user.assert_not_awaited()
        notification_repo.insert.assert_not_awaited()

    async def test_task_not_found_skips_push(self, mock_deps):
        service, _, ws_manager, notification_repo = mock_deps

        service._get_task = AsyncMock(return_value=None)

        event = TaskEvent(
            event_type="task.running",
            task_id="task_nonexistent",
            from_status="pending",
            to_status="running",
        )
        await service._on_event(event)

        ws_manager.send_to_user.assert_not_awaited()
        notification_repo.insert.assert_not_awaited()
