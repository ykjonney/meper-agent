"""Event Bus — in-process async pub/sub for workflow and task lifecycle events.

Provides at-least-once delivery semantics with automatic retry and
dead-letter queue for failed handlers.

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

import asyncio
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


# ---------------------------------------------------------------------------
# Handler wrapper with retry and dead-letter
# ---------------------------------------------------------------------------


class DeadLetterRecord:
    """Record of a failed event delivery."""

    def __init__(
        self,
        event: Event,
        handler_name: str,
        error: str,
        attempts: int,
    ) -> None:
        self.event = event
        self.handler_name = handler_name
        self.error = error
        self.attempts = attempts
        self.timestamp = datetime.now(UTC)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_type": self.event.event_type,
            "handler": self.handler_name,
            "error": self.error,
            "attempts": self.attempts,
            "timestamp": self.timestamp.isoformat(),
        }


EventHandler = Callable[[Event], Any]


class _HandlerWrapper:
    """Wraps a handler with retry logic and dead-letter tracking."""

    MAX_RETRIES = 3
    RETRY_DELAY_S = 1.0

    def __init__(self, handler: EventHandler, handler_name: str | None = None):
        self.handler = handler
        self.name = handler_name or getattr(handler, "__name__", str(handler))

    async def invoke(self, event: Event) -> Exception | None:
        """Invoke the handler with retry.

        Returns:
            The last exception if all retries failed, ``None`` on success.
        """
        last_error: Exception | None = None

        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                result = self.handler(event)
                if result is not None and hasattr(result, "__await__"):
                    await result
                return None  # success
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "event_handler_retry",
                    handler=self.name,
                    event_type=event.event_type,
                    attempt=attempt,
                    max_retries=self.MAX_RETRIES,
                    error=str(exc),
                )
                if attempt < self.MAX_RETRIES:
                    await asyncio.sleep(self.RETRY_DELAY_S * attempt)

        return last_error


# ---------------------------------------------------------------------------
# Event Bus
# ---------------------------------------------------------------------------


class EventBus:
    """In-process async event bus with at-least-once delivery.

    Thread-safe for subscribe (publish is asyncio-only).
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, list[_HandlerWrapper]] = {}
        self._dead_letter_queue: list[DeadLetterRecord] = []
        self._max_dead_letter = 1000
        # handler_name → {event_key: first_seen_timestamp}
        self._processed: dict[str, dict[str, float]] = {}
        self._max_processed = 10_000
        self._dedup_ttl = 60.0  # seconds — only suppress burst duplicates

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
        self._subscribers[event_type].append(
            _HandlerWrapper(handler, handler_name=handler_name)
        )
        logger.debug(
            "event_subscriber_added",
            event_type=event_type,
            handler=self._subscribers[event_type][-1].name,
        )

    def unsubscribe(self, event_type: str, handler: EventHandler) -> bool:
        """Remove a handler from *event_type*.

        Returns:
            True if removed, False if not found.
        """
        wrappers = self._subscribers.get(event_type, [])
        for i, w in enumerate(wrappers):
            if w.handler is handler:
                wrappers.pop(i)
                logger.debug("event_subscriber_removed", event_type=event_type, handler=w.name)
                return True
        return False

    # ── Publishing ──

    async def publish(self, event: Event) -> list[DeadLetterRecord]:
        """Publish an event to all matching subscribers.

        Delivery semantics:
        - All matching handlers are invoked concurrently (via ``asyncio.gather``).
        - Each handler is retried up to MAX_RETRIES times.
        - Handlers that exhaust retries go to the dead-letter queue.
        - Duplicate events (same identity per handler) are silently skipped.

        Args:
            event: The event to publish.

        Returns:
            List of dead-letter records for failed deliveries.
        """
        handlers: list[_HandlerWrapper] = []

        # Direct match
        handlers.extend(self._subscribers.get(event.event_type, []))

        # Wildcard subscribers
        handlers.extend(self._subscribers.get("*", []))

        if not handlers:
            logger.debug("event_no_subscribers", event_type=event.event_type)
            return []

        event_key = self._event_key(event)
        now = event.timestamp.timestamp()

        # Filter out recently-processed (handler, event) pairs within TTL window
        to_invoke: list[_HandlerWrapper] = []
        for h in handlers:
            seen_at = self._processed.get(h.name, {}).get(event_key)
            if seen_at is not None and (now - seen_at) < self._dedup_ttl:
                logger.debug(
                    "event_handler_skipped",
                    handler=h.name,
                    event_key=event_key,
                    age_s=round(now - seen_at, 1),
                )
                continue
            self._mark_processed(h.name, event_key, now)
            to_invoke.append(h)

        if not to_invoke:
            logger.debug("event_all_handlers_dedup", event_type=event.event_type)
            return []

        logger.debug(
            "event_publishing",
            event_type=event.event_type,
            handler_count=len(to_invoke),
        )

        # Invoke all handlers concurrently
        results = await asyncio.gather(
            *[h.invoke(event) for h in to_invoke],
            return_exceptions=True,
        )

        # Collect dead letters
        dead_letters: list[DeadLetterRecord] = []
        for handler_wrapper, exc in zip(to_invoke, results, strict=True):
            if isinstance(exc, Exception):
                record = DeadLetterRecord(
                    event=event,
                    handler_name=handler_wrapper.name,
                    error=str(exc),
                    attempts=_HandlerWrapper.MAX_RETRIES,
                )
                dead_letters.append(record)

        if dead_letters:
            self._dead_letter_queue.extend(dead_letters)
            # Trim dead letter queue
            if len(self._dead_letter_queue) > self._max_dead_letter:
                self._dead_letter_queue = self._dead_letter_queue[
                    -self._max_dead_letter:
                ]

            logger.error(
                "event_delivery_failed",
                event_type=event.event_type,
                failed_count=len(dead_letters),
            )

        return dead_letters

    # ── Deduplication helpers ──

    def _event_key(self, event: Event) -> str:
        """Stable identity for an event.

        TaskEvent uses ``event_type:task_id:to_status`` so the same logical
        transition is recognised even if the object is re-created.  All other
        events fall back to ``event_type:data`` which is safe for the small,
        structured payloads we emit today.
        """
        if isinstance(event, TaskEvent):
            return f"{event.event_type}:{event.task_id}:{event.to_status}"
        return f"{event.event_type}:{event.data}"

    def _mark_processed(self, handler_name: str, event_key: str, now: float) -> None:
        """Record *event_key* as handled by *handler_name* at time *now*.

        Entries older than ``_dedup_ttl`` are evicted opportunistically when
        the per-handler dict exceeds ``_max_processed`` to bound memory.
        """
        if handler_name not in self._processed:
            self._processed[handler_name] = {}
        bucket = self._processed[handler_name]
        bucket[event_key] = now
        if len(bucket) > self._max_processed:
            cutoff = now - self._dedup_ttl
            self._processed[handler_name] = {
                k: v for k, v in bucket.items() if v >= cutoff
            }

    # ── Dead letter inspection ──

    @property
    def dead_letter_queue(self) -> list[DeadLetterRecord]:
        """Immutable view of the dead-letter queue."""
        return list(self._dead_letter_queue)

    def clear_dead_letters(self) -> int:
        """Clear the dead-letter queue.

        Returns:
            Number of records cleared.
        """
        count = len(self._dead_letter_queue)
        self._dead_letter_queue.clear()
        return count

    # ── Stats ──

    def stats(self) -> dict[str, Any]:
        """Return event bus statistics."""
        return {
            "subscribers": {
                event_type: len(handlers)
                for event_type, handlers in self._subscribers.items()
            },
            "total_subscribers": sum(len(h) for h in self._subscribers.values()),
            "dead_letter_count": len(self._dead_letter_queue),
        }


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
