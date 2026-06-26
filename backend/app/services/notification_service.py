# backend/app/services/notification_service.py
"""NotificationService — bridges EventBus task events to WebSocket pushes and persistent notifications."""
from __future__ import annotations

from loguru import logger

from app.engine.events import Event, TaskEvent, get_event_bus
from app.models.notification import Notification, NotificationKind
from app.services.notification_repo import NotificationRepository
from app.services.task_service import TaskService
from app.services.ws_manager import WebSocketConnectionManager

# Task events that trigger persistent notifications
NOTIFY_EVENTS: dict[str, NotificationKind] = {
    "task.failed": NotificationKind.TASK_FAILED,
    "task.waiting_human": NotificationKind.TASK_WAITING_HUMAN,
    "task.completed": NotificationKind.TASK_COMPLETED,
}

# Notification titles per kind
_NOTIFICATION_TITLES: dict[NotificationKind, str] = {
    NotificationKind.TASK_FAILED: "任务执行失败",
    NotificationKind.TASK_WAITING_HUMAN: "任务等待审批",
    NotificationKind.TASK_COMPLETED: "任务执行完成",
}


class NotificationService:
    """Subscribes to EventBus, pushes task_status to WS, persists notifications."""

    def __init__(
        self,
        event_bus=None,
        ws_manager: WebSocketConnectionManager | None = None,
        notification_repo: NotificationRepository | None = None,
    ) -> None:
        self._event_bus = event_bus or get_event_bus()
        self._ws_manager = ws_manager
        self._notification_repo = notification_repo

    def _get_ws_manager(self) -> WebSocketConnectionManager:
        if self._ws_manager is None:
            from app.services.ws_manager import get_ws_manager
            self._ws_manager = get_ws_manager()
        return self._ws_manager

    def _get_repo(self) -> NotificationRepository:
        if self._notification_repo is None:
            from app.db.mongodb import get_database
            self._notification_repo = NotificationRepository(get_database())
        return self._notification_repo

    async def _get_task(self, task_id: str) -> dict | None:
        """Load task document. Delegates to TaskService.get_task."""
        return await TaskService.get_task(task_id)

    def register(self) -> None:
        """Subscribe to all EventBus events and filter for task-related ones."""
        self._event_bus.subscribe("*", self._on_event, handler_name="notification_service")
        logger.info("notification_service_registered")

    async def _on_event(self, event: Event) -> None:
        """Handle an EventBus event — route to task status push / notification creation."""
        if not isinstance(event, TaskEvent):
            return
        if not event.task_id:
            return

        task = await self._get_task(event.task_id)
        if task is None:
            return

        user_id = task.get("created_by", "")
        if not user_id:
            return

        ws_manager = self._get_ws_manager()

        # 1. Push task_status to user's WebSocket (transient)
        await ws_manager.send_to_user(user_id, {
            "type": "task_status",
            "data": {
                "task_id": event.task_id,
                "status": event.to_status,
                "from_status": event.from_status,
                "workflow_id": task.get("workflow_id", ""),
                "updated_at": event.timestamp.isoformat(),
            },
        })

        # 2. If this event warrants a persistent notification
        kind = NOTIFY_EVENTS.get(event.event_type)
        if kind is not None:
            notification = Notification(
                user_id=user_id,
                kind=kind,
                title=_NOTIFICATION_TITLES[kind],
                body=self._build_body(event, task),
                related_task_id=event.task_id,
                related_workflow_id=task.get("workflow_id", ""),
            )
            await self._get_repo().insert(notification)

            await ws_manager.send_to_user(user_id, {
                "type": "notification",
                "data": notification.model_dump(mode="json"),
            })

    def _build_body(self, event: TaskEvent, task: dict) -> str:
        """Build human-readable notification body from event context."""
        kind = NOTIFY_EVENTS.get(event.event_type)
        if kind == NotificationKind.TASK_FAILED:
            error = task.get("error")
            error_msg = ""
            if error and isinstance(error, dict):
                error_msg = error.get("error_message", "")
            return f"任务 {event.task_id} 执行失败" + (f": {error_msg}" if error_msg else "")
        elif kind == NotificationKind.TASK_WAITING_HUMAN:
            return f"任务 {event.task_id} 等待人工审批"
        elif kind == NotificationKind.TASK_COMPLETED:
            return f"任务 {event.task_id} 已完成"
        return f"任务 {event.task_id} 状态更新"
