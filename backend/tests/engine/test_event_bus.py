"""Tests for the in-process Event Bus — pub/sub, retry, dead letter."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.engine.events import (
    Event,
    EventBus,
    TaskEvent,
    WorkflowEvent,
    get_event_bus,
)


class TestEventCreation:
    """Event dataclass creation."""

    def test_base_event(self):
        """Should create a base event with timestamp."""
        event = Event(event_type="test.event", data={"key": "value"})
        assert event.event_type == "test.event"
        assert event.data["key"] == "value"
        assert event.timestamp is not None

    def test_task_event(self):
        """Should create a task event with task_id."""
        event = TaskEvent(
            event_type="task.completed",
            task_id="task_001",
            from_status="running",
            to_status="completed",
        )
        assert event.task_id == "task_001"
        assert event.from_status == "running"
        assert event.to_status == "completed"

    def test_workflow_event(self):
        """Should create a workflow event."""
        event = WorkflowEvent(
            event_type="workflow.started",
            workflow_id="wf_001",
            task_id="task_001",
        )
        assert event.workflow_id == "wf_001"
        assert event.task_id == "task_001"


class TestEventBusSubscribe:
    """EventBus subscription management."""

    def setup_method(self):
        self.bus = EventBus()

    def test_subscribe(self):
        """Should register a handler for an event type."""
        async def handler(event): pass

        self.bus.subscribe("task.completed", handler)
        stats = self.bus.stats()
        assert stats["total_subscribers"] == 1
        assert "task.completed" in stats["subscribers"]

    def test_subscribe_wildcard(self):
        """Should support wildcard subscription."""
        async def handler(event): pass

        self.bus.subscribe("*", handler)
        stats = self.bus.stats()
        assert stats["total_subscribers"] == 1

    def test_unsubscribe_found(self):
        """Should remove a registered handler."""
        async def handler(event): pass

        self.bus.subscribe("task.completed", handler, handler_name="test_handler")
        assert self.bus.unsubscribe("task.completed", handler) is True
        assert self.bus.stats()["total_subscribers"] == 0

    def test_unsubscribe_not_found(self):
        """Should return False for unknown handler."""
        async def handler(event): pass

        assert self.bus.unsubscribe("unknown", handler) is False


class TestEventBusPublish:
    """EventBus publishing and delivery."""

    def setup_method(self):
        self.bus = EventBus()

    @pytest.mark.asyncio
    async def test_publish_delivers_to_handler(self):
        """Should deliver event to subscribed handler."""
        received = []

        async def handler(event):
            received.append(event)

        self.bus.subscribe("task.completed", handler)
        await self.bus.publish(TaskEvent(
            event_type="task.completed",
            task_id="task_001",
        ))

        assert len(received) == 1
        assert received[0].task_id == "task_001"

    @pytest.mark.asyncio
    async def test_publish_delivers_to_wildcard(self):
        """Should deliver event to wildcard subscribers."""
        received = []

        async def handler(event):
            received.append(event)

        self.bus.subscribe("*", handler)
        await self.bus.publish(TaskEvent(event_type="task.started", task_id="task_001"))

        assert len(received) == 1

    @pytest.mark.asyncio
    async def test_publish_multiple_handlers(self):
        """Should deliver to all handlers for the same event type."""
        results = []

        async def handler1(event):
            results.append("h1")

        async def handler2(event):
            results.append("h2")

        self.bus.subscribe("task.started", handler1)
        self.bus.subscribe("task.started", handler2)
        await self.bus.publish(TaskEvent(event_type="task.started", task_id="task_001"))

        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_publish_no_subscribers(self):
        """Should not error when no subscribers exist."""
        result = await self.bus.publish(TaskEvent(event_type="task.nobody", task_id="task_001"))
        assert result == []

    @pytest.mark.asyncio
    async def test_sync_handler(self):
        """Should support sync handlers."""
        received = []

        def handler(event):
            received.append(event)

        self.bus.subscribe("task.done", handler)
        await self.bus.publish(TaskEvent(event_type="task.done", task_id="task_001"))

        assert len(received) == 1


class TestEventBusRetryAndDeadLetter:
    """EventBus retry logic and dead-letter queue."""

    def setup_method(self):
        self.bus = EventBus()

    @pytest.mark.asyncio
    async def test_retry_on_failure(self):
        """Should retry failed handlers."""
        call_count = 0

        async def failing_handler(event):
            nonlocal call_count
            call_count += 1
            raise ValueError("handler failed")

        self.bus.subscribe("task.failed", failing_handler)
        dead_letters = await self.bus.publish(TaskEvent(
            event_type="task.failed",
            task_id="task_001",
        ))

        assert len(dead_letters) == 1
        # Should have been retried MAX_RETRIES (3) times
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_dead_letter_record(self):
        """Should create dead letter record for failed handler."""
        async def handler(event):
            raise RuntimeError("boom")

        self.bus.subscribe("task.error", handler)
        dead_letters = await self.bus.publish(TaskEvent(
            event_type="task.error",
            task_id="task_001",
        ))

        assert len(dead_letters) == 1
        record = dead_letters[0]
        assert record.event.task_id == "task_001"
        assert "boom" in record.error
        assert record.attempts == 3

    @pytest.mark.asyncio
    async def test_dead_letter_queue_accumulates(self):
        """Should accumulate dead letters in the queue."""
        async def handler(event):
            raise ValueError("fail")

        self.bus.subscribe("task.fail", handler)
        await self.bus.publish(TaskEvent(event_type="task.fail", task_id="task_001"))
        await self.bus.publish(TaskEvent(event_type="task.fail", task_id="task_002"))

        assert len(self.bus.dead_letter_queue) == 2

    @pytest.mark.asyncio
    async def test_clear_dead_letters(self):
        """Should clear dead letter queue."""
        async def handler(event):
            raise ValueError("fail")

        self.bus.subscribe("task.fail", handler)
        await self.bus.publish(TaskEvent(event_type="task.fail", task_id="task_001"))

        assert self.bus.dead_letter_queue
        cleared = self.bus.clear_dead_letters()
        assert cleared == 1
        assert len(self.bus.dead_letter_queue) == 0


class TestEventBusSingleton:
    """Module-level singleton."""

    def test_get_event_bus_returns_same_instance(self):
        """get_event_bus should return the same instance."""
        bus1 = get_event_bus()
        bus2 = get_event_bus()
        assert bus1 is bus2

    def test_event_bus_shorthand(self):
        """event_bus shorthand should work."""
        from app.engine.events import event_bus
        assert event_bus is not None


class TestEventBusStats:
    """EventBus statistics."""

    def setup_method(self):
        self.bus = EventBus()

    def test_stats_empty(self):
        """Should return empty stats for new bus."""
        stats = self.bus.stats()
        assert stats["total_subscribers"] == 0
        assert stats["dead_letter_count"] == 0

    def test_stats_with_subscribers(self):
        """Should reflect registered subscribers."""
        async def h1(event): pass
        async def h2(event): pass

        self.bus.subscribe("task.a", h1)
        self.bus.subscribe("task.b", h2)
        self.bus.subscribe("task.b", h1)

        stats = self.bus.stats()
        assert stats["total_subscribers"] == 3
        assert stats["subscribers"]["task.a"] == 1
        assert stats["subscribers"]["task.b"] == 2
