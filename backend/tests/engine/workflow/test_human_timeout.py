"""HumanTimeoutMonitor unit tests — timeout actions, cancellation, edge cases."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from app.engine.workflow.nodes.human import HumanTimeoutMonitor
from app.models.task import TaskStatus


class TestHumanTimeoutMonitor:
    """Tests for HumanTimeoutMonitor timeout behavior."""

    async def test_timeout_auto_approve(self) -> None:
        """Timeout triggers auto_approve → RUNNING."""
        monitor = HumanTimeoutMonitor()
        with patch("app.engine.workflow.nodes.human.TaskService") as mock_ts:
            mock_ts.get_task = AsyncMock(return_value={"status": TaskStatus.WAITING_HUMAN.value})
            mock_ts.transition_task = AsyncMock()

            await monitor.start_monitor("t1", "n1", timeout_ms=100, timeout_action="auto_approve")
            # Wait for timeout to fire
            await asyncio.sleep(0.2)

            mock_ts.transition_task.assert_called_once()
            call_kwargs = mock_ts.transition_task.call_args
            assert call_kwargs.kwargs["to_status"] == TaskStatus.RUNNING

        await monitor.cancel_monitor("t1", "n1")

    async def test_timeout_auto_reject(self) -> None:
        """Timeout triggers auto_reject → FAILED."""
        monitor = HumanTimeoutMonitor()
        with patch("app.engine.workflow.nodes.human.TaskService") as mock_ts:
            mock_ts.get_task = AsyncMock(return_value={"status": TaskStatus.WAITING_HUMAN.value})
            mock_ts.transition_task = AsyncMock()

            await monitor.start_monitor("t2", "n2", timeout_ms=100, timeout_action="auto_reject")
            await asyncio.sleep(0.2)

            mock_ts.transition_task.assert_called_once()
            call_kwargs = mock_ts.transition_task.call_args
            assert call_kwargs.kwargs["to_status"] == TaskStatus.FAILED

        await monitor.cancel_monitor("t2", "n2")

    async def test_timeout_auto_skip(self) -> None:
        """Timeout triggers auto_skip → RUNNING."""
        monitor = HumanTimeoutMonitor()
        with patch("app.engine.workflow.nodes.human.TaskService") as mock_ts:
            mock_ts.get_task = AsyncMock(return_value={"status": TaskStatus.WAITING_HUMAN.value})
            mock_ts.transition_task = AsyncMock()

            await monitor.start_monitor("t3", "n3", timeout_ms=100, timeout_action="auto_skip")
            await asyncio.sleep(0.2)

            mock_ts.transition_task.assert_called_once()
            call_kwargs = mock_ts.transition_task.call_args
            assert call_kwargs.kwargs["to_status"] == TaskStatus.RUNNING

        await monitor.cancel_monitor("t3", "n3")

    async def test_timeout_fail(self) -> None:
        """Timeout triggers fail → FAILED."""
        monitor = HumanTimeoutMonitor()
        with patch("app.engine.workflow.nodes.human.TaskService") as mock_ts:
            mock_ts.get_task = AsyncMock(return_value={"status": TaskStatus.WAITING_HUMAN.value})
            mock_ts.transition_task = AsyncMock()

            await monitor.start_monitor("t4", "n4", timeout_ms=100, timeout_action="fail")
            await asyncio.sleep(0.2)

            mock_ts.transition_task.assert_called_once()
            call_kwargs = mock_ts.transition_task.call_args
            assert call_kwargs.kwargs["to_status"] == TaskStatus.FAILED

        await monitor.cancel_monitor("t4", "n4")

    async def test_already_handled_no_action(self) -> None:
        """Task already processed — no action taken."""
        monitor = HumanTimeoutMonitor()
        with patch("app.engine.workflow.nodes.human.TaskService") as mock_ts:
            # Task already completed
            mock_ts.get_task = AsyncMock(return_value={"status": TaskStatus.COMPLETED.value})
            mock_ts.transition_task = AsyncMock()

            await monitor.start_monitor("t5", "n5", timeout_ms=100, timeout_action="auto_approve")
            await asyncio.sleep(0.2)

            mock_ts.transition_task.assert_not_called()

        await monitor.cancel_monitor("t5", "n5")

    async def test_cancel_monitor(self) -> None:
        """Cancelling monitor prevents timeout action."""
        monitor = HumanTimeoutMonitor()
        with patch("app.engine.workflow.nodes.human.TaskService") as mock_ts:
            mock_ts.get_task = AsyncMock()
            mock_ts.transition_task = AsyncMock()

            await monitor.start_monitor("t6", "n6", timeout_ms=200, timeout_action="fail")
            # Cancel immediately
            await monitor.cancel_monitor("t6", "n6")
            # Wait past the original timeout
            await asyncio.sleep(0.3)

            mock_ts.transition_task.assert_not_called()

    async def test_zero_timeout_no_monitor(self) -> None:
        """timeout_ms=0 does not start monitoring."""
        monitor = HumanTimeoutMonitor()
        with patch("app.engine.workflow.nodes.human.TaskService"):
            await monitor.start_monitor("t7", "n7", timeout_ms=0, timeout_action="fail")
            assert not monitor._tasks


# Make all async tests work with pytest-asyncio
for attr_name in dir(TestHumanTimeoutMonitor):
    if attr_name.startswith("test_"):
        method = getattr(TestHumanTimeoutMonitor, attr_name)
        if asyncio.iscoroutinefunction(method):
            setattr(TestHumanTimeoutMonitor, attr_name, pytest.mark.asyncio(method))
