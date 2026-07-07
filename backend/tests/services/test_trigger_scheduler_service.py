"""Tests for TriggerSchedulerService."""
import pytest
from unittest.mock import AsyncMock, patch

from app.services.trigger_scheduler_service import TriggerSchedulerService


@pytest.fixture
def service() -> TriggerSchedulerService:
    return TriggerSchedulerService()


class TestTriggerSchedulerService:
    """Tests for TriggerSchedulerService."""

    async def test_service_initialization(self, service: TriggerSchedulerService) -> None:
        """测试服务初始化"""
        assert service._workflows == {}
        assert service._started is False

    async def test_service_start_stop(self, service: TriggerSchedulerService) -> None:
        """测试服务启停"""
        await service.start()
        assert service._started is True

        await service.stop()
        assert service._started is False
