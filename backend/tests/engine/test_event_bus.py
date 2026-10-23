"""Tests for the in-process Event Bus — pub/sub delivery."""
from __future__ import annotations

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
        assert result is None

    @pytest.mark.asyncio
    async def test_sync_handler(self):
        """Should support sync handlers."""
        received = []

        def handler(event):
            received.append(event)

        self.bus.subscribe("task.done", handler)
        await self.bus.publish(TaskEvent(event_type="task.done", task_id="task_001"))

        assert len(received) == 1

    @pytest.mark.asyncio
    async def test_failing_handler_does_not_break_others(self):
        """A failing handler is logged; remaining handlers still run."""
        received = []

        async def failing_handler(event):
            raise ValueError("handler failed")

        async def ok_handler(event):
            received.append(event)

        self.bus.subscribe("task.failed", failing_handler)
        self.bus.subscribe("task.failed", ok_handler)
        await self.bus.publish(TaskEvent(
            event_type="task.failed",
            task_id="task_001",
        ))

        assert len(received) == 1


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
