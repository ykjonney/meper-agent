"""Tests for TriggerConfig model."""
from datetime import UTC, datetime

from app.models.workflow import TriggerConfig


class TestTriggerConfig:
    """Tests for TriggerConfig model."""

    def test_trigger_config_cron(self) -> None:
        """测试 Cron 类型触发配置"""
        config = TriggerConfig(
            type="cron",
            enabled=True,
            cron_expression="0 9 * * *",
            default_input={"date": "{{ now() }}"},
        )
        assert config.type == "cron"
        assert config.enabled is True
        assert config.cron_expression == "0 9 * * *"
        assert config.execute_at is None

    def test_trigger_config_once(self) -> None:
        """测试一次性触发配置"""
        execute_time = datetime(2026, 7, 10, 14, 0, tzinfo=UTC)
        config = TriggerConfig(
            type="once",
            enabled=True,
            execute_at=execute_time,
            default_input={},
        )
        assert config.type == "once"
        assert config.execute_at == execute_time
        assert config.cron_expression is None

    def test_trigger_config_defaults(self) -> None:
        """测试默认值"""
        config = TriggerConfig(type="cron")
        assert config.enabled is False
        assert config.default_input == {}
        assert config.last_triggered_at is None
