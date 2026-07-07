"""Tests for template renderer utility."""
from datetime import datetime, timezone

from app.utils.template_renderer import render_default_input


class TestRenderDefaultInput:
    """Tests for render_default_input function."""

    def test_render_static_values(self) -> None:
        """测试静态值不做处理"""
        default_input = {"department": "engineering", "count": 5}
        result = render_default_input(default_input)
        assert result == {"department": "engineering", "count": 5}

    def test_render_now_template(self) -> None:
        """测试 {{ now() }} 模板"""
        default_input = {"timestamp": "{{ now() }}"}
        result = render_default_input(default_input)
        assert "timestamp" in result
        # 验证是 ISO 格式时间字符串
        datetime.fromisoformat(result["timestamp"])

    def test_render_today_template(self) -> None:
        """测试 {{ today() }} 模板"""
        default_input = {"date": "{{ today() }}"}
        result = render_default_input(default_input)
        # 验证是 YYYY-MM-DD 格式
        assert len(result["date"]) == 10
        assert result["date"].count("-") == 2

    def test_render_mixed(self) -> None:
        """测试混合模板和静态值"""
        default_input = {
            "date": "{{ today() }}",
            "department": "engineering",
            "timestamp": "{{ now() }}",
        }
        result = render_default_input(default_input)
        assert result["department"] == "engineering"
        assert "{{" not in result["date"]
        assert "{{" not in result["timestamp"]

    def test_render_invalid_template(self) -> None:
        """测试无效模板降级处理"""
        default_input = {"invalid": "{{ undefined_func() }}"}
        result = render_default_input(default_input)
        # 无效模板返回原始字符串
        assert result["invalid"] == "{{ undefined_func() }}"
