"""Tests for Application schema — login_config.userid_jsonpath 校验（v4.2）。"""
import pytest
from app.schemas.application import ApplicationCreate
from pydantic import ValidationError


def _base(login_config: dict) -> ApplicationCreate:
    return ApplicationCreate(
        name="测试应用",
        login_config=login_config,
    )


class TestUseridJsonpathValidation:
    def test_valid_default(self) -> None:
        """不配置 → 合法（运行时默认 userId）。"""
        app = _base({"login_url": "https://x.example.com/login"})
        assert app.login_config.get("userid_jsonpath") is None

    def test_valid_top_level(self) -> None:
        app = _base({
            "login_url": "https://x.example.com/login",
            "userid_jsonpath": "userId",
        })
        assert app.login_config["userid_jsonpath"] == "userId"

    def test_valid_nested_path(self) -> None:
        app = _base({
            "login_url": "https://x.example.com/login",
            "userid_jsonpath": "data.userId",
        })
        assert app.login_config["userid_jsonpath"] == "data.userId"

    def test_empty_string_disables(self) -> None:
        """空串 = 显式禁用提取（身份锚退回登录名）。"""
        app = _base({
            "login_url": "https://x.example.com/login",
            "userid_jsonpath": "",
        })
        assert app.login_config["userid_jsonpath"] == ""

    def test_invalid_path_rejected(self) -> None:
        """非法点分路径 → 校验失败。"""
        with pytest.raises(ValidationError, match="userid_jsonpath"):
            _base({
                "login_url": "https://x.example.com/login",
                "userid_jsonpath": "data..userId",
            })

    def test_non_string_rejected(self) -> None:
        with pytest.raises(ValidationError, match="userid_jsonpath"):
            _base({
                "login_url": "https://x.example.com/login",
                "userid_jsonpath": 123,
            })
