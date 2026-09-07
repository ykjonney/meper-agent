"""Tests for UserCredentialResolver — 账密型换 session（带 Redis 缓存）。

v4 模型（mcp-credential-broker）：纯账密型绑定。resolve() 流程：
server_name → conn → 反查 app（find_by_mcp_connection）→
get_binding(platform_user_id, app_id) → _get_or_exchange_session
（Redis 缓存 / POST login_url 换 session）→ 按 conn.auth_type + auth_config 注入。
token 型绑定已废弃。

v5 增补（公共 MCP 放行）：auth_type=none 的连接直接放行（不反查应用）；
不挂任何应用的连接用平台静态凭证放行（无授权单元）。
"""
from unittest.mock import AsyncMock, patch

import pytest
from app.engine.mcp.user_credential_resolver import UserCredentialResolver

# 复用的 conn / app / binding 夹具
_CONN = {
    "_id": "mcp_conn_01",
    "auth_type": "bearer_token",
    "auth_config": {},
}
_APP = {
    "_id": "app_01",
    "login_config": {
        "login_url": "https://oa.example.com/login",
        "method": "POST",
        "username_field": "username",
        "password_field": "password",
        "token_jsonpath": "data.token",
        "session_ttl": 1800,
    },
}
_BINDING = {"username": "admin", "password": "pass"}


class TestResolve:
    """resolve 主流程：conn → app → binding → session。"""

    async def test_empty_args_returns_none(self) -> None:
        """platform_user_id 或 server_name 为空 → None。"""
        resolver = UserCredentialResolver()
        assert await resolver.resolve("", "oa_system") is None
        assert await resolver.resolve("user_platform_01", "") is None

    async def test_unknown_server_returns_none(self) -> None:
        """server_name 找不到对应 connection → None。"""
        resolver = UserCredentialResolver()
        with patch.object(
            UserCredentialResolver,
            "_get_connection_by_name",
            AsyncMock(return_value=None),
        ):
            result = await resolver.resolve("user_platform_01", "unknown")
        assert result is None

    async def test_auth_type_none_passes_through_without_app_lookup(self) -> None:
        """公共 MCP（auth_type=none）：直接放行，不反查应用、不查绑定。"""
        resolver = UserCredentialResolver()
        conn = {"_id": "mcp_public", "auth_type": "none", "auth_config": {}}
        with patch.object(
            UserCredentialResolver,
            "_get_connection_by_name",
            AsyncMock(return_value=conn),
        ), patch(
            "app.services.application_service.ApplicationService.find_by_mcp_connection",
            AsyncMock(side_effect=AssertionError("不应反查应用")),
        ) as mock_find:
            result = await resolver.resolve("user_platform_01", "weather")
        assert result == {"auth_type": "none"}
        mock_find.assert_not_awaited()

    async def test_auth_type_none_bound_app_also_passes_through(self) -> None:
        """auth_type=none 即使挂在应用下也放行——无需用户授权（换出的
        session 本来也不会注入 header，授权流程形同虚设）。"""
        resolver = UserCredentialResolver()
        conn = {"_id": "mcp_public", "auth_type": "none", "auth_config": {}}
        with patch.object(
            UserCredentialResolver,
            "_get_connection_by_name",
            AsyncMock(return_value=conn),
        ):
            result = await resolver.resolve("user_platform_01", "weather")
        assert result == {"auth_type": "none"}

    async def test_no_application_uses_static_credentials(self) -> None:
        """不挂任何应用 = 公共 MCP：返回平台静态凭证（auth_config）放行；
        auth_config 为空则裸透传（loader 空 headers 分支）。"""
        resolver = UserCredentialResolver()
        conn = {
            "_id": "mcp_public_key",
            "auth_type": "bearer_token",
            "auth_config": {"token": "platform_static_token"},
        }
        with patch.object(
            UserCredentialResolver,
            "_get_connection_by_name",
            AsyncMock(return_value=conn),
        ), patch(
            "app.services.application_service.ApplicationService.find_by_mcp_connection",
            AsyncMock(return_value=None),
        ):
            result = await resolver.resolve("user_platform_01", "public_api")

        assert result is not None
        assert result["auth_type"] == "bearer_token"
        assert result["token"] == "platform_static_token"

    async def test_no_application_without_static_credentials(self) -> None:
        """不挂应用且 auth_config 为空：仍放行（返回不含凭证的描述，
        loader 空 headers 裸透传）。"""
        resolver = UserCredentialResolver()
        with patch.object(
            UserCredentialResolver,
            "_get_connection_by_name",
            AsyncMock(return_value=_CONN),  # bearer_token + 空 auth_config
        ), patch(
            "app.services.application_service.ApplicationService.find_by_mcp_connection",
            AsyncMock(return_value=None),
        ):
            result = await resolver.resolve("user_platform_01", "oa_system")
        assert result == {"auth_type": "bearer_token"}

    async def test_unbound_raises_structured_error(self) -> None:
        """用户未绑定该应用 → 抛 McpCredentialUnbound（携带 app_id/app_name，
        拦截器据此生成带标记的错误结果并引导 LLM 走 request_app_authorization）。"""
        from agent_flow_harness.mcp.errors import McpCredentialUnbound

        resolver = UserCredentialResolver()
        with patch.object(
            UserCredentialResolver,
            "_get_connection_by_name",
            AsyncMock(return_value=_CONN),
        ), patch(
            "app.services.application_service.ApplicationService.find_by_mcp_connection",
            AsyncMock(return_value=_APP),
        ), patch(
            "app.services.user_mcp_credential_service.UserMcpCredentialService.get_binding",
            AsyncMock(return_value=None),
        ), pytest.raises(McpCredentialUnbound) as exc_info:
            await resolver.resolve("user_platform_01", "oa_system")
        assert exc_info.value.app_id == "app_01"
        assert exc_info.value.server_name == "oa_system"

    async def test_cached_session_returned_directly(self) -> None:
        """Redis 缓存命中 → 直接返回缓存的 session，不调 login。"""
        resolver = UserCredentialResolver()
        with patch.object(
            UserCredentialResolver,
            "_get_connection_by_name",
            AsyncMock(return_value=_CONN),
        ), patch(
            "app.services.application_service.ApplicationService.find_by_mcp_connection",
            AsyncMock(return_value=_APP),
        ), patch(
            "app.services.user_mcp_credential_service.UserMcpCredentialService.get_binding",
            AsyncMock(return_value=_BINDING),
        ), patch(
            "app.services.user_mcp_credential_service.get_cached_session",
            AsyncMock(return_value="cached_session_token"),
        ), patch.object(
            UserCredentialResolver,
            "_do_login",
            AsyncMock(return_value="should_not_be_called"),
        ):
            result = await resolver.resolve("user_platform_01", "oa_system")

        assert result is not None
        assert result["token"] == "cached_session_token"
        assert result["auth_type"] == "bearer_token"
        assert result["header_name"] == "X-API-Key"

    async def test_cache_miss_calls_login_and_caches(self) -> None:
        """缓存 miss → 取 login_config → POST login → 写缓存 → 返回。"""
        resolver = UserCredentialResolver()
        with patch.object(
            UserCredentialResolver,
            "_get_connection_by_name",
            AsyncMock(return_value=_CONN),
        ), patch(
            "app.services.application_service.ApplicationService.find_by_mcp_connection",
            AsyncMock(return_value=_APP),
        ), patch(
            "app.services.user_mcp_credential_service.UserMcpCredentialService.get_binding",
            AsyncMock(return_value=_BINDING),
        ), patch(
            "app.services.user_mcp_credential_service.get_cached_session",
            AsyncMock(return_value=None),  # cache miss
        ), patch(
            "app.services.user_mcp_credential_service.set_cached_session",
            AsyncMock(),
        ) as mock_set_cache, patch.object(
            UserCredentialResolver,
            "_do_login",
            AsyncMock(return_value="fresh_session_token"),
        ) as mock_login:
            result = await resolver.resolve("user_platform_01", "oa_system")

        assert result is not None
        assert result["token"] == "fresh_session_token"
        mock_login.assert_awaited_once()
        mock_set_cache.assert_awaited_once()
        args = mock_set_cache.call_args.args
        assert args[0] == "user_platform_01"
        assert args[1] == "app_01"
        assert args[2] == "fresh_session_token"
        assert args[3] == 1800

    async def test_no_login_config_returns_none(self) -> None:
        """应用没配 login_config（无 login_url）→ None（无法换 session）。"""
        resolver = UserCredentialResolver()
        app = {"_id": "app_01", "login_config": {}}
        with patch.object(
            UserCredentialResolver,
            "_get_connection_by_name",
            AsyncMock(return_value=_CONN),
        ), patch(
            "app.services.application_service.ApplicationService.find_by_mcp_connection",
            AsyncMock(return_value=app),
        ), patch(
            "app.services.user_mcp_credential_service.UserMcpCredentialService.get_binding",
            AsyncMock(return_value=_BINDING),
        ), patch(
            "app.services.user_mcp_credential_service.get_cached_session",
            AsyncMock(return_value=None),
        ):
            result = await resolver.resolve("user_platform_01", "oa_system")
        assert result is None

    async def test_exchange_failure_raises_structured_invalid(self) -> None:
        """兑换 session 失败（账密被用户在外部系统改掉等）→ 结构化
        McpCredentialInvalid（拦截器据此弹卡引导更新凭证，而非不透明报错）。"""
        from agent_flow_harness.mcp.errors import McpCredentialInvalid

        app = {**_APP, "name": "OA 系统"}
        resolver = UserCredentialResolver()
        with patch.object(
            UserCredentialResolver,
            "_get_connection_by_name",
            AsyncMock(return_value=_CONN),
        ), patch(
            "app.services.application_service.ApplicationService.find_by_mcp_connection",
            AsyncMock(return_value=app),
        ), patch(
            "app.services.user_mcp_credential_service.UserMcpCredentialService.get_binding",
            AsyncMock(return_value=_BINDING),
        ), patch(
            "app.services.user_mcp_credential_service.get_cached_session",
            AsyncMock(return_value=None),  # cache miss → 走 login
        ), patch.object(
            UserCredentialResolver,
            "_do_login",
            AsyncMock(side_effect=PermissionError("登录失败：密码错误")),
        ), pytest.raises(McpCredentialInvalid) as exc_info:
            await resolver.resolve("user_platform_01", "oa_system")

        assert exc_info.value.reason == "INVALID"
        assert exc_info.value.app_id == "app_01"
        assert exc_info.value.app_name == "OA 系统"
        assert "密码错误" in exc_info.value.detail

    async def test_injects_header_name_from_auth_config(self) -> None:
        """auth_config.header_name 决定注入头。"""
        resolver = UserCredentialResolver()
        conn = {
            **_CONN,
            "auth_config": {"header_name": "X-Auth-Token"},
        }
        with patch.object(
            UserCredentialResolver,
            "_get_connection_by_name",
            AsyncMock(return_value=conn),
        ), patch(
            "app.services.application_service.ApplicationService.find_by_mcp_connection",
            AsyncMock(return_value=_APP),
        ), patch(
            "app.services.user_mcp_credential_service.UserMcpCredentialService.get_binding",
            AsyncMock(return_value=_BINDING),
        ), patch(
            "app.services.user_mcp_credential_service.get_cached_session",
            AsyncMock(return_value="sess"),
        ):
            result = await resolver.resolve("user_platform_01", "oa_system")

        assert result is not None
        assert result["header_name"] == "X-Auth-Token"


class TestDoLogin:
    """_do_login 的 HTTP 调用 + jsonpath 解析。"""

    async def test_successful_login_extracts_token(self) -> None:
        """正常登录：POST 成功 → 按 token_jsonpath 取 token。"""
        resolver = UserCredentialResolver()
        login_config = {
            "login_url": "https://oa.example.com/login",
            "method": "POST",
            "token_jsonpath": "data.access_token",
        }

        class _FakeResp:
            def raise_for_status(self):
                pass

            def json(self):
                return {"data": {"access_token": "sess_abc"}, "status": "ok"}

        class _FakeClient:
            def __init__(self, *a, **kw):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                pass

            async def request(self, method, url, **kw):
                return _FakeResp()

        with patch(
            "app.engine.mcp.user_credential_resolver.httpx.AsyncClient", _FakeClient
        ):
            token = await resolver._do_login(login_config, "admin", "pass123")

        assert token == "sess_abc"

    async def test_missing_token_path_raises(self) -> None:
        """响应成功但找不到 token_jsonpath → 抛 PermissionError。"""
        resolver = UserCredentialResolver()
        login_config = {
            "login_url": "https://oa.example.com/login",
            "token_jsonpath": "data.token",
        }

        class _FakeResp:
            def raise_for_status(self):
                pass

            def json(self):
                # 成功响应但没有 data.token（路径不存在）
                return {"success": True, "data": {"other": "value"}}

        class _FakeClient:
            def __init__(self, *a, **kw):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                pass

            async def request(self, method, url, **kw):
                return _FakeResp()

        with patch(
            "app.engine.mcp.user_credential_resolver.httpx.AsyncClient", _FakeClient
        ), pytest.raises(PermissionError, match="未找到 token 路径"):
            await resolver._do_login(login_config, "admin", "pass123")

    async def test_login_failure_success_false_raises(self) -> None:
        """登录失败（success:false）→ 抛 PermissionError 带原始错误信息。"""
        resolver = UserCredentialResolver()
        login_config = {
            "login_url": "https://oa.example.com/api/admin/login",
            "token_jsonpath": "data.accessToken",
        }

        class _FakeResp:
            def raise_for_status(self):
                pass

            def json(self):
                return {"success": False, "code": 500, "message": "User Name or Password is Invalid!", "data": {}}

        class _FakeClient:
            def __init__(self, *a, **kw):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                pass

            async def request(self, method, url, **kw):
                return _FakeResp()

        with patch(
            "app.engine.mcp.user_credential_resolver.httpx.AsyncClient", _FakeClient
        ), pytest.raises(PermissionError, match="登录失败.*Invalid"):
            await resolver._do_login(login_config, "admin", "pass123")
