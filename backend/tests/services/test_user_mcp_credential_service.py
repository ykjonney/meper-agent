"""Tests for UserMcpCredentialService — 验证提取稳定用户 ID + 身份锚点优先级链。

聚焦 v4.2 身份锚点：
- ``_verify_credentials`` 按 ``userid_jsonpath``（默认 userId，空串禁用）
  从登录响应提取稳定用户 ID，提取不到返回 None（不报错）
- ``bind_credential`` 的 identity_key 优先级：
  显式传入（key 应用 introspection sub）> 登录响应 userId > 登录名
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.services.user_mcp_credential_service import (
    UserMcpCredentialService,
    _verify_credentials,
)

LOGIN_CONFIG = {
    "login_url": "https://oa.example.com/login",
    "method": "POST",
    "username_field": "username",
    "password_field": "password",
    "token_jsonpath": "data.token",
}


def _login_response(payload: dict):
    """构造 _verify_credentials 的 httpx 假响应。"""
    resp = MagicMock()
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    client = MagicMock()
    client.request = AsyncMock(return_value=resp)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    return client


class TestVerifyCredentialsExtractsUserId:
    async def test_default_jsonpath_extracts_userid(self) -> None:
        """默认 userid_jsonpath=userId：顶层字段提取。"""
        client = _login_response({
            "success": True,
            "userId": "u_10086",
            "data": {"token": "tok"},
        })
        with patch(
            "app.services.user_mcp_credential_service.httpx.AsyncClient",
            return_value=client,
        ):
            result = await _verify_credentials(LOGIN_CONFIG, "zhangsan", "pw")
        assert result == "u_10086"

    async def test_custom_jsonpath(self) -> None:
        """配置 data.userId：嵌套路径提取。"""
        client = _login_response({
            "data": {"token": "tok", "userId": 10086},
        })
        config = {**LOGIN_CONFIG, "userid_jsonpath": "data.userId"}
        with patch(
            "app.services.user_mcp_credential_service.httpx.AsyncClient",
            return_value=client,
        ):
            result = await _verify_credentials(config, "zhangsan", "pw")
        assert result == "10086"  # 数值型 ID 转字符串

    async def test_empty_jsonpath_disables_extraction(self) -> None:
        """userid_jsonpath 配空串 → 显式禁用，返回 None。"""
        client = _login_response({
            "userId": "u_10086",
            "data": {"token": "tok"},
        })
        config = {**LOGIN_CONFIG, "userid_jsonpath": ""}
        with patch(
            "app.services.user_mcp_credential_service.httpx.AsyncClient",
            return_value=client,
        ):
            result = await _verify_credentials(config, "zhangsan", "pw")
        assert result is None

    async def test_missing_path_returns_none(self) -> None:
        """登录响应没有该路径 → None（退回登录名锚，不视为失败）。"""
        client = _login_response({"data": {"token": "tok"}})
        with patch(
            "app.services.user_mcp_credential_service.httpx.AsyncClient",
            return_value=client,
        ):
            result = await _verify_credentials(LOGIN_CONFIG, "zhangsan", "pw")
        assert result is None

    async def test_login_failure_still_raises(self) -> None:
        """登录失败 → PermissionError（提取逻辑不影响验证语义）。"""
        client = _login_response({"success": False, "message": "密码错误"})
        with patch(
            "app.services.user_mcp_credential_service.httpx.AsyncClient",
            return_value=client,
        ), pytest.raises(PermissionError):
            await _verify_credentials(LOGIN_CONFIG, "zhangsan", "bad")


class TestBindCredentialIdentityKey:
    """bind_credential 的 identity_key 三级优先链（mock DB/Redis/身份服务）。"""

    @staticmethod
    async def _bind(login_payload: dict, identity_key: str = "") -> dict:
        """跑一次 bind_credential，返回 upsert 收到的 sub 参数。"""
        client = _login_response(login_payload)
        captured: dict = {}
        with (
            patch(
                "app.services.user_mcp_credential_service.httpx.AsyncClient",
                return_value=client,
            ),
            patch(
                "app.services.user_mcp_credential_service.ExternalIdentityService.upsert",
                new=AsyncMock(side_effect=lambda sub, uid: captured.update(
                    sub=sub, platform_user_id=uid
                )),
            ),
            patch(
                "app.services.user_mcp_credential_service.UserMcpCredentialService._collection",
                return_value=MagicMock(
                    update_one=AsyncMock(),
                    find_one=AsyncMock(return_value=None),
                ),
            ),
            patch(
                "app.services.user_mcp_credential_service.clear_app_session_cache",
                new=AsyncMock(),
            ),
        ):
            await UserMcpCredentialService.bind_credential(
                platform_user_id="user_p1",
                app_id="app_1",
                username="zhangsan",
                password="pw",
                login_config=LOGIN_CONFIG,
                identity_key=identity_key,
            )
        return captured

    async def test_explicit_identity_key_wins(self) -> None:
        """① 显式传入（key 应用 introspection sub）优先于登录响应。"""
        captured = await self._bind(
            {"userId": "u_10086", "data": {"token": "tok"}},
            identity_key="sub_from_introspection",
        )
        assert captured["sub"] == "app_1:sub_from_introspection"

    async def test_login_userid_beats_username(self) -> None:
        """② 无显式传入 → 登录响应的稳定 userId 优先于登录名。"""
        captured = await self._bind(
            {"userId": "u_10086", "data": {"token": "tok"}},
        )
        assert captured["sub"] == "app_1:u_10086"

    async def test_fallback_to_username(self) -> None:
        """③ 登录响应无 userId → 退回登录名（v4.1 行为）。"""
        captured = await self._bind({"data": {"token": "tok"}})
        assert captured["sub"] == "app_1:zhangsan"
