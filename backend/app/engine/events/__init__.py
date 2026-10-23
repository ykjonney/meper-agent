"""Event Bus — in-process async pub/sub for workflow and task lifecycle events.

Usage::

    from app.engine.events import event_bus

    # Subscribe
    async def on_task_completed(event: TaskEvent):
        logger.info("task done", task_id=event.task_id)

    event_bus.subscribe("task.completed", on_task_completed)

    # Publish
    await event_bus.publish(TaskEvent(
        event_type="task.completed",
        task_id="task_xxx",
        data={"status": "completed"},
    ))
"""
from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from loguru import logger

# ---------------------------------------------------------------------------
# Event types
# ---------------------------------------------------------------------------


@dataclass
class Event:
    """Base event with timestamp and type."""

    event_type: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class TaskEvent(Event):
    """Event related to a Task lifecycle change."""

    task_id: str = ""
    from_status: str | None = None
    to_status: str | None = None


@dataclass
class WorkflowEvent(Event):
    """Event related to a Workflow execution."""

    workflow_id: str = ""
    task_id: str = ""


EventHandler = Callable[[Event], Any]


# ---------------------------------------------------------------------------
# Event Bus
# ---------------------------------------------------------------------------


class EventBus:
    """In-process async event bus.

    Thread-safe for subscribe (publish is asyncio-only).
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, list[EventHandler]] = {}

    # ── Subscription ──

    def subscribe(
        self,
        event_type: str,
        handler: EventHandler,
        handler_name: str | None = None,
    ) -> None:
        """Register a handler for *event_type*.

        Supports wildcard ``*`` — subscribes to ALL events.

        Args:
            event_type: Event type string (e.g. ``"task.completed"``) or ``"*"``.
            handler: Async or sync callable accepting an ``Event``.
            handler_name: Optional name for logging (defaults to function name).
        """
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(handler)
        logger.debug(
            "event_subscriber_added",
            event_type=event_type,
            handler=handler_name or getattr(handler, "__name__", str(handler)),
        )

    # ── Publishing ──

    async def publish(self, event: Event) -> None:
        """Publish an event to all matching subscribers.

        Handlers run sequentially; one failing handler is logged and does not
        prevent the others from running nor raise to the publisher.
        """
        handlers: list[EventHandler] = []

        # Direct match
        handlers.extend(self._subscribers.get(event.event_type, []))

        # Wildcard subscribers
        handlers.extend(self._subscribers.get("*", []))

        if not handlers:
            logger.debug("event_no_subscribers", event_type=event.event_type)
            return

        logger.debug(
            "event_publishing",
            event_type=event.event_type,
            handler_count=len(handlers),
        )

        for handler in handlers:
            try:
                result = handler(event)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                logger.opt(exception=True).error(
                    "event_handler_failed",
                    event_type=event.event_type,
                    handler=getattr(handler, "__name__", str(handler)),
                )


# Module-level singleton
_bus: EventBus | None = None


def get_event_bus() -> EventBus:
    """Return the process-level EventBus singleton."""
    global _bus
    if _bus is None:
        _bus = EventBus()
    return _bus


# Shorthand
event_bus = get_event_bus()
