"""Tests for UserCredentialResolver — 账密型换 session（带 Redis 缓存）。

v4 模型（mcp-credential-broker）：纯账密型绑定。resolve() 流程：
server_name → conn → 反查 app（find_by_mcp_connection）→
get_binding(platform_user_id, app_id) → _get_or_exchange_session
（Redis 缓存 / POST login_url 换 session）→ 按 conn.auth_type + auth_config 注入。
token 型绑定已废弃。

v5 增补（公共 MCP 放行）：auth_type=none 的连接直接放行（不反查应用）。

v5.1 收紧：不挂任何应用且需认证的连接 → McpCredentialForbidden——
外部用户的调用不得回退平台静态凭证（跨权限访问风险），公共语义
仅剩免认证连接；认证型连接必须挂应用走用户授权。
"""
from unittest.mock import AsyncMock, patch

import httpx
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

    async def test_no_application_with_static_credentials_forbidden(self) -> None:
        """不挂任何应用且需认证 → FORBIDDEN：即使平台配了静态凭证也不放行
        （外部用户的调用不得以平台共享身份代用，防跨权限访问）。"""
        from agent_flow_harness.mcp.errors import McpCredentialForbidden

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
        ), pytest.raises(McpCredentialForbidden) as exc_info:
            await resolver.resolve("user_platform_01", "public_api")

        assert exc_info.value.reason == "FORBIDDEN"
        assert exc_info.value.server_name == "public_api"

    async def test_no_application_without_static_credentials_forbidden(
        self,
    ) -> None:
        """不挂应用且 auth_config 为空：同样 FORBIDDEN（不裸透传）。"""
        from agent_flow_harness.mcp.errors import McpCredentialForbidden

        resolver = UserCredentialResolver()
        with patch.object(
            UserCredentialResolver,
            "_get_connection_by_name",
            AsyncMock(return_value=_CONN),  # bearer_token + 空 auth_config
        ), patch(
            "app.services.application_service.ApplicationService.find_by_mcp_connection",
            AsyncMock(return_value=None),
        ), pytest.raises(McpCredentialForbidden) as exc_info:
            await resolver.resolve("user_platform_01", "oa_system")
        assert exc_info.value.reason == "FORBIDDEN"

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

    async def test_endpoint_5xx_raises_structured_unavailable(self) -> None:
        """登录端点 5xx → 结构化 McpAppUnavailable（UNAVAILABLE）——
        凭证未必有问题，不引导授权更新，提示稍后重试。"""
        from agent_flow_harness.mcp.errors import McpAppUnavailable

        app = {**_APP, "name": "OA 系统"}
        request = httpx.Request("POST", "https://oa.example.com/login")
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
            AsyncMock(
                side_effect=httpx.HTTPStatusError(
                    "Server error '500'",
                    request=request,
                    response=httpx.Response(500, request=request),
                )
            ),
        ), pytest.raises(McpAppUnavailable) as exc_info:
            await resolver.resolve("user_platform_01", "oa_system")

        assert exc_info.value.reason == "UNAVAILABLE"
        assert exc_info.value.app_id == "app_01"
        assert exc_info.value.app_name == "OA 系统"
        # detail 只放异常类名，不透内部 URL
        assert exc_info.value.detail == "HTTPStatusError"

    async def test_endpoint_timeout_raises_structured_unavailable(self) -> None:
        """登录端点超时（httpx.RequestError）→ 同样归 UNAVAILABLE。"""
        from agent_flow_harness.mcp.errors import McpAppUnavailable

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
            AsyncMock(return_value=None),
        ), patch.object(
            UserCredentialResolver,
            "_do_login",
            AsyncMock(side_effect=httpx.ConnectTimeout("timed out")),
        ), pytest.raises(McpAppUnavailable) as exc_info:
            await resolver.resolve("user_platform_01", "oa_system")

        assert exc_info.value.reason == "UNAVAILABLE"

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

    @staticmethod
    def _fake_client(resp: "_FakeResp") -> type:
        """按给定响应构造 httpx.AsyncClient 替身。"""

        class _FakeClient:
            def __init__(self, *a, **kw):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                pass

            async def request(self, method, url, **kw):
                return resp

        return _FakeClient

    async def test_successful_login_extracts_token(self) -> None:
        """正常登录：POST 成功 → 按 token_jsonpath 取 token。"""
        resolver = UserCredentialResolver()
        login_config = {
            "login_url": "https://oa.example.com/login",
            "method": "POST",
            "token_jsonpath": "data.access_token",
        }

        resp = _FakeResp(
            200, lambda: {"data": {"access_token": "sess_abc"}, "status": "ok"}
        )

        with patch(
            "app.engine.mcp.user_credential_resolver.httpx.AsyncClient",
            self._fake_client(resp),
        ):
            token = await resolver._do_login(login_config, "admin", "pass123")

        assert token == "sess_abc"

    async def test_4xx_login_rejected_as_permission_error(self) -> None:
        """4xx（密码错误返回 401/403 的接入方）→ PermissionError（INVALID
        语义，出授权卡）。若落入 raise_for_status 的 HTTPStatusError 会被
        归为「端点不可用」，这类应用永远出不了授权卡。"""
        resolver = UserCredentialResolver()
        login_config = {
            "login_url": "https://oa.example.com/login",
            "token_jsonpath": "data.token",
        }

        resp = _FakeResp(401, lambda: {})

        with patch(
            "app.engine.mcp.user_credential_resolver.httpx.AsyncClient",
            self._fake_client(resp),
        ), pytest.raises(PermissionError, match="HTTP 401"):
            await resolver._do_login(login_config, "admin", "wrong_pass")

    async def test_5xx_login_raises_http_status_error(self) -> None:
        """5xx → raise_for_status 抛 HTTPStatusError（resolve 层归 UNAVAILABLE）。"""
        resolver = UserCredentialResolver()
        login_config = {
            "login_url": "https://oa.example.com/login",
            "token_jsonpath": "data.token",
        }

        resp = _FakeResp(500, lambda: {})
        resp.raise_for_status_error = True

        with patch(
            "app.engine.mcp.user_credential_resolver.httpx.AsyncClient",
            self._fake_client(resp),
        ), pytest.raises(httpx.HTTPStatusError):
            await resolver._do_login(login_config, "admin", "pass123")

    async def test_missing_token_path_raises(self) -> None:
        """响应成功但找不到 token_jsonpath → 抛 PermissionError。"""
        resolver = UserCredentialResolver()
        login_config = {
            "login_url": "https://oa.example.com/login",
            "token_jsonpath": "data.token",
        }

        resp = _FakeResp(
            200, lambda: {"success": True, "data": {"other": "value"}}
        )

        with patch(
            "app.engine.mcp.user_credential_resolver.httpx.AsyncClient",
            self._fake_client(resp),
        ), pytest.raises(PermissionError, match="未找到 token 路径"):
            await resolver._do_login(login_config, "admin", "pass123")

    async def test_login_failure_success_false_raises(self) -> None:
        """登录失败（success:false）→ 抛 PermissionError 带原始错误信息。"""
        resolver = UserCredentialResolver()
        login_config = {
            "login_url": "https://oa.example.com/api/admin/login",
            "token_jsonpath": "data.accessToken",
        }

        resp = _FakeResp(
            200,
            lambda: {
                "success": False,
                "code": 500,
                "message": "User Name or Password is Invalid!",
                "data": {},
            },
        )

        with patch(
            "app.engine.mcp.user_credential_resolver.httpx.AsyncClient",
            self._fake_client(resp),
        ), pytest.raises(PermissionError, match="登录失败.*Invalid"):
            await resolver._do_login(login_config, "admin", "pass123")


class _FakeResp:
    """httpx 响应替身：status_code 参与错误分类；json/raise_for_status 可配。"""

    def __init__(self, status_code: int, json_body) -> None:
        self.status_code = status_code
        self._json_body = json_body
        self.raise_for_status_error = status_code >= 500

    def raise_for_status(self) -> None:
        if self.raise_for_status_error:
            request = httpx.Request("POST", "https://oa.example.com/login")
            raise httpx.HTTPStatusError(
                f"Server error '{self.status_code}'",
                request=request,
                response=httpx.Response(self.status_code, request=request),
            )

    def json(self):
        return self._json_body()
