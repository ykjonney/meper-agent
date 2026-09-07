"""Tests for external API — 终端用户自助授权（client 首绑/按需授权）。

覆盖：
- relaxed 鉴权语义（依赖注入层面模拟未绑定 principal，鉴权链本身由
  test_auth_apikey.py 覆盖）
- key 应用 username 锁定（防冒名）/ 跨应用绑定规则
- 自动开通（应用同账户密码建号，前端明确告知）与认领（claim）双路径
- 列表/解绑（完整鉴权端点）
"""
from unittest.mock import AsyncMock, patch

import pytest
from app.api.v1.ext import auth_and_rate_limit, auth_and_rate_limit_allow_unbound
from app.core.auth_apikey import ApiKeyPrincipal
from app.main import app
from fastapi.testclient import TestClient

APP_ID = "app_main"
APP = {
    "_id": APP_ID,
    "name": "主应用",
    "description": "",
    "mcp_connection_ids": ["conn_1"],
    "login_config": {
        "login_url": "https://ext.example.com/login",
        "method": "POST",
        "username_field": "username",
        "password_field": "password",
        "token_jsonpath": "data.token",
        "session_ttl": 3600,
    },
}
OTHER_APP = {
    "_id": "app_other",
    "name": "其他应用",
    "description": "",
    "mcp_connection_ids": ["conn_2"],
    "login_config": {"login_url": "https://other.example.com/login"},
}


@pytest.fixture
def client():
    return TestClient(app)


def _principal(*, bound: bool = False) -> ApiKeyPrincipal:
    """构造 ext principal：bound=True 模拟已绑定（有 platform_user_id）。

    ext_user_id 模拟 introspection 的稳定用户 ID（sub），身份锚点 v4.2。
    """
    return ApiKeyPrincipal(
        key_id="apikey_test",
        owner_user_id="user_owner",
        scopes=["agents:read", "agents:invoke"],
        bindings={},
        rate_limit=60,
        user_id="user_plat_1" if bound else None,
        token_record_id="user_plat_1" if bound else None,
        user_token="token_raw",
        app_id=APP_ID,
        introspect_url="https://ext.example.com/introspect",
        ext_username="alice",
        ext_user_id="extuid_888",
    )


def _override(principal, *, relaxed: bool = False):
    dep = auth_and_rate_limit_allow_unbound if relaxed else auth_and_rate_limit
    app.dependency_overrides[dep] = lambda: principal
    return lambda: app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# GET /ext/my-app-authorizations/bootstrap（relaxed）
# ---------------------------------------------------------------------------


class TestBootstrap:
    def test_bootstrap_unbound_user_allowed(self, client) -> None:
        cleanup = _override(_principal(bound=False), relaxed=True)
        try:
            with (
                patch(
                    "app.api.v1.ext.my_app_authorizations.ApplicationService.get_application",
                    new=AsyncMock(return_value=APP),
                ),
            ):
                resp = client.get("/api/v1/ext/my-app-authorizations/bootstrap")
            assert resp.status_code == 200
            data = resp.json()
            assert data["app"]["id"] == APP_ID
            assert data["app"]["name"] == "主应用"
            assert data["app"]["has_login_config"] is True
            assert data["ext_username"] == "alice"
            assert data["bound"] is False
        finally:
            cleanup()

    def test_bootstrap_bound_user(self, client) -> None:
        cleanup = _override(_principal(bound=True), relaxed=True)
        try:
            with (
                patch(
                    "app.api.v1.ext.my_app_authorizations.ApplicationService.get_application",
                    new=AsyncMock(return_value=APP),
                ),
                patch(
                    "app.api.v1.ext.my_app_authorizations.UserMcpCredentialService.get_binding",
                    new=AsyncMock(return_value={"username": "alice", "password": "x"}),
                ),
            ):
                resp = client.get("/api/v1/ext/my-app-authorizations/bootstrap")
            assert resp.status_code == 200
            assert resp.json()["bound"] is True
        finally:
            cleanup()


# ---------------------------------------------------------------------------
# PUT /ext/my-app-authorizations/{app_id}（relaxed）
# ---------------------------------------------------------------------------


def _list_bindings_result():
    return {
        "platform_user_id": "user_plat_1",
        "app_bindings": {APP_ID: {"username": "alice", "password": "***"}},
        "updated_at": "2026-01-01T00:00:00",
    }


class TestAuthorizeApp:
    def test_key_app_username_override_allowed(self, client) -> None:
        """key 应用 username 可改（默认带出 introspection 用户名但不强制）——
        登录名与 introspection 返回值不同的场景；凭证仍经 login_url 校验。"""
        cleanup = _override(_principal(bound=True), relaxed=True)
        try:
            bind_mock = AsyncMock(return_value=_list_bindings_result())
            with (
                patch(
                    "app.api.v1.ext.my_app_authorizations.ApplicationService.get_application",
                    new=AsyncMock(return_value=APP),
                ),
                patch(
                    "app.api.v1.ext.my_app_authorizations.ApplicationService.list_applications",
                    new=AsyncMock(return_value=[APP]),
                ),
                patch(
                    "app.api.v1.ext.my_app_authorizations.UserMcpCredentialService.bind_credential",
                    new=bind_mock,
                ),
                patch(
                    "app.api.v1.ext.my_app_authorizations.UserMcpCredentialService.list_bindings",
                    new=AsyncMock(return_value=_list_bindings_result()),
                ),
            ):
                resp = client.put(
                    f"/api/v1/ext/my-app-authorizations/{APP_ID}",
                    json={"username": "bob", "password": "pw"},
                )
            assert resp.status_code == 200
            # 按提交的用户名绑定（非 ext_username）
            assert bind_mock.await_args.kwargs["username"] == "bob"
        finally:
            cleanup()

    def test_first_bind_auto_creates_platform_user_with_app_credentials(
        self, client
    ) -> None:
        """未绑定 + 无认领 + 用户名不存在 → 以应用账号密码自动创建平台
        账号（前端已明确告知并经用户确认）。先验证应用凭证再建号。"""
        cleanup = _override(_principal(bound=False), relaxed=True)
        try:
            create_mock = AsyncMock(return_value="user_auto_1")
            bind_mock = AsyncMock(return_value=_list_bindings_result())
            with (
                patch(
                    "app.api.v1.ext.my_app_authorizations.ApplicationService.get_application",
                    new=AsyncMock(return_value=APP),
                ),
                patch(
                    "app.api.v1.ext.my_app_authorizations.UserMcpCredentialService.verify_credentials",
                    new=AsyncMock(return_value=None),
                ),
                patch(
                    "app.api.v1.ext.my_app_authorizations.UserService.get_user_by_username",
                    new=AsyncMock(return_value=None),
                ),
                patch(
                    "app.api.v1.ext.my_app_authorizations.UserService.create_ext_user_with_password",
                    new=create_mock,
                ),
                patch(
                    "app.api.v1.ext.my_app_authorizations.UserMcpCredentialService.bind_credential",
                    new=bind_mock,
                ),
                patch(
                    "app.api.v1.ext.my_app_authorizations.UserMcpCredentialService.list_bindings",
                    new=AsyncMock(return_value=_list_bindings_result()),
                ),
            ):
                resp = client.put(
                    f"/api/v1/ext/my-app-authorizations/{APP_ID}",
                    json={"username": "alice", "password": "app_pw"},
                )
            assert resp.status_code == 200
            # 建号用应用账号密码（同账户密码）
            create_mock.assert_awaited_once_with("alice", "app_pw")
            assert bind_mock.call_args.kwargs["platform_user_id"] == "user_auto_1"
            # 身份锚点用稳定 ID（ext_user_id），不是登录名
            assert bind_mock.call_args.kwargs["identity_key"] == "extuid_888"
        finally:
            cleanup()

    def test_first_bind_attaches_existing_user_with_matching_password(
        self, client
    ) -> None:
        """用户名已有平台账号且密码一致（admin 预建/此前自动创建的同一
        自然人）→ 直接关联该账号，不再建新号。"""
        cleanup = _override(_principal(bound=False), relaxed=True)
        try:
            create_mock = AsyncMock(return_value="user_new_1")
            bind_mock = AsyncMock(return_value=_list_bindings_result())
            with (
                patch(
                    "app.api.v1.ext.my_app_authorizations.ApplicationService.get_application",
                    new=AsyncMock(return_value=APP),
                ),
                patch(
                    "app.api.v1.ext.my_app_authorizations.UserMcpCredentialService.verify_credentials",
                    new=AsyncMock(return_value=None),
                ),
                patch(
                    "app.api.v1.ext.my_app_authorizations.UserService.get_user_by_username",
                    new=AsyncMock(return_value={"_id": "user_exist_1"}),
                ),
                patch(
                    "app.api.v1.ext.my_app_authorizations.AuthService.verify_platform_credentials",
                    new=AsyncMock(return_value="user_exist_1"),
                ),
                patch(
                    "app.api.v1.ext.my_app_authorizations.UserService.create_ext_user_with_password",
                    new=create_mock,
                ),
                patch(
                    "app.api.v1.ext.my_app_authorizations.UserMcpCredentialService.bind_credential",
                    new=bind_mock,
                ),
                patch(
                    "app.api.v1.ext.my_app_authorizations.UserMcpCredentialService.list_bindings",
                    new=AsyncMock(return_value=_list_bindings_result()),
                ),
            ):
                resp = client.put(
                    f"/api/v1/ext/my-app-authorizations/{APP_ID}",
                    json={"username": "alice", "password": "app_pw"},
                )
            assert resp.status_code == 200
            create_mock.assert_not_awaited()
            assert bind_mock.call_args.kwargs["platform_user_id"] == "user_exist_1"
        finally:
            cleanup()

    def test_first_bind_username_taken_password_mismatch(self, client) -> None:
        """用户名已有平台账号但密码不一致 → 422 PLATFORM_USERNAME_TAKEN，
        引导用户改走「关联已有账号」认领。"""
        from app.core.errors import UnauthorizedError

        cleanup = _override(_principal(bound=False), relaxed=True)
        try:
            create_mock = AsyncMock(return_value="user_new_1")
            bind_mock = AsyncMock(return_value=_list_bindings_result())
            with (
                patch(
                    "app.api.v1.ext.my_app_authorizations.ApplicationService.get_application",
                    new=AsyncMock(return_value=APP),
                ),
                patch(
                    "app.api.v1.ext.my_app_authorizations.UserMcpCredentialService.verify_credentials",
                    new=AsyncMock(return_value=None),
                ),
                patch(
                    "app.api.v1.ext.my_app_authorizations.UserService.get_user_by_username",
                    new=AsyncMock(return_value={"_id": "user_exist_1"}),
                ),
                patch(
                    "app.api.v1.ext.my_app_authorizations.AuthService.verify_platform_credentials",
                    new=AsyncMock(
                        side_effect=UnauthorizedError(
                            code="INVALID_CREDENTIALS",
                            message="用户名或密码错误",
                        )
                    ),
                ),
                patch(
                    "app.api.v1.ext.my_app_authorizations.UserService.create_ext_user_with_password",
                    new=create_mock,
                ),
                patch(
                    "app.api.v1.ext.my_app_authorizations.UserMcpCredentialService.bind_credential",
                    new=bind_mock,
                ),
            ):
                resp = client.put(
                    f"/api/v1/ext/my-app-authorizations/{APP_ID}",
                    json={"username": "alice", "password": "wrong_pw"},
                )
            assert resp.status_code == 422
            assert resp.json()["error"]["code"] == "PLATFORM_USERNAME_TAKEN"
            # 不建号、不落凭证
            create_mock.assert_not_awaited()
            bind_mock.assert_not_awaited()
        finally:
            cleanup()

    def test_first_bind_invalid_app_credentials_no_user_created(
        self, client
    ) -> None:
        """应用凭证验证失败（密码填错）→ 422 MCP_CREDENTIAL_INVALID，
        不创建平台账号（先验证再建号）。"""
        cleanup = _override(_principal(bound=False), relaxed=True)
        try:
            create_mock = AsyncMock(return_value="user_new_1")
            with (
                patch(
                    "app.api.v1.ext.my_app_authorizations.ApplicationService.get_application",
                    new=AsyncMock(return_value=APP),
                ),
                patch(
                    "app.api.v1.ext.my_app_authorizations.UserMcpCredentialService.verify_credentials",
                    new=AsyncMock(side_effect=PermissionError("应用登录失败：密码错误")),
                ),
                patch(
                    "app.api.v1.ext.my_app_authorizations.UserService.create_ext_user_with_password",
                    new=create_mock,
                ),
                patch(
                    "app.api.v1.ext.my_app_authorizations.UserService.get_user_by_username",
                    new=AsyncMock(return_value=None),
                ),
            ):
                resp = client.put(
                    f"/api/v1/ext/my-app-authorizations/{APP_ID}",
                    json={"username": "alice", "password": "bad_pw"},
                )
            assert resp.status_code == 422
            assert resp.json()["error"]["code"] == "MCP_CREDENTIAL_INVALID"
            create_mock.assert_not_awaited()
        finally:
            cleanup()

    def test_first_bind_with_claim_attaches_to_existing_account(self, client) -> None:
        """认领路径（首绑唯一路径）：平台账密验证通过 → 挂到已有账号。"""
        cleanup = _override(_principal(bound=False), relaxed=True)
        try:
            verify_mock = AsyncMock(return_value="user_claimed_1")
            bind_mock = AsyncMock(return_value=_list_bindings_result())
            with (
                patch(
                    "app.api.v1.ext.my_app_authorizations.ApplicationService.get_application",
                    new=AsyncMock(return_value=APP),
                ),
                patch(
                    "app.api.v1.ext.my_app_authorizations.ApplicationService.list_applications",
                    new=AsyncMock(return_value=[APP]),
                ),
                patch(
                    "app.api.v1.ext.my_app_authorizations.AuthService.verify_platform_credentials",
                    new=verify_mock,
                ),
                patch(
                    "app.api.v1.ext.my_app_authorizations.UserMcpCredentialService.bind_credential",
                    new=bind_mock,
                ),
                patch(
                    "app.api.v1.ext.my_app_authorizations.UserMcpCredentialService.list_bindings",
                    new=AsyncMock(return_value=_list_bindings_result()),
                ),
            ):
                resp = client.put(
                    f"/api/v1/ext/my-app-authorizations/{APP_ID}",
                    json={
                        "username": "alice",
                        "password": "pw",
                        "claim_platform_username": "platform_alice",
                        "claim_platform_password": "platform_pw",
                    },
                )
            assert resp.status_code == 200
            verify_mock.assert_awaited_once_with("platform_alice", "platform_pw")
            assert bind_mock.call_args.kwargs["platform_user_id"] == "user_claimed_1"
            # 身份锚点用稳定 ID（ext_user_id），不是登录名
            assert bind_mock.call_args.kwargs["identity_key"] == "extuid_888"
        finally:
            cleanup()

    def test_claim_failure_mapped_to_422(self, client) -> None:
        """认领失败（平台账密错误/锁定）→ 422 业务错误而非 401——
        401 会被 client 的 apikey 处理器误判为身份失效弹回错误页。"""
        from app.core.errors import UnauthorizedError

        cleanup = _override(_principal(bound=False), relaxed=True)
        try:
            with (
                patch(
                    "app.api.v1.ext.my_app_authorizations.ApplicationService.get_application",
                    new=AsyncMock(return_value=APP),
                ),
                patch(
                    "app.api.v1.ext.my_app_authorizations.AuthService.verify_platform_credentials",
                    new=AsyncMock(
                        side_effect=UnauthorizedError(
                            code="INVALID_CREDENTIALS",
                            message="平台账号或密码错误",
                        )
                    ),
                ),
            ):
                resp = client.put(
                    f"/api/v1/ext/my-app-authorizations/{APP_ID}",
                    json={
                        "username": "alice",
                        "password": "pw",
                        "claim_platform_username": "platform_alice",
                        "claim_platform_password": "wrong",
                    },
                )
            assert resp.status_code == 422
            assert resp.json()["error"]["code"] == "PLATFORM_CREDENTIAL_INVALID"
            assert "平台账号或密码错误" in resp.json()["error"]["message"]
        finally:
            cleanup()

    def test_claim_rejected_when_already_bound(self, client) -> None:
        """已有平台身份后不允许认领（防把凭证挂到别的账号、运行时查不到）。"""
        cleanup = _override(_principal(bound=True), relaxed=True)
        try:
            with patch(
                "app.api.v1.ext.my_app_authorizations.ApplicationService.get_application",
                new=AsyncMock(return_value=APP),
            ):
                resp = client.put(
                    f"/api/v1/ext/my-app-authorizations/{APP_ID}",
                    json={
                        "username": "alice",
                        "password": "pw",
                        "claim_platform_username": "platform_alice",
                        "claim_platform_password": "platform_pw",
                    },
                )
            assert resp.status_code == 403
            assert resp.json()["error"]["code"] == "EXT_CLAIM_NOT_ALLOWED"
        finally:
            cleanup()

    def test_cross_app_requires_identity(self, client) -> None:
        """未绑定用户不能直接绑其他应用（先完成 key 应用首绑）。"""
        cleanup = _override(_principal(bound=False), relaxed=True)
        try:
            with patch(
                "app.api.v1.ext.my_app_authorizations.ApplicationService.get_application",
                new=AsyncMock(return_value=OTHER_APP),
            ):
                resp = client.put(
                    "/api/v1/ext/my-app-authorizations/app_other",
                    json={"username": "carol", "password": "pw"},
                )
            assert resp.status_code == 403
            assert resp.json()["error"]["code"] == "EXT_IDENTITY_REQUIRED"
        finally:
            cleanup()

    def test_cross_app_with_identity_binds_to_current_user(self, client) -> None:
        """已绑定用户可绑其他应用（按需授权场景），挂当前身份、username 自由。"""
        cleanup = _override(_principal(bound=True), relaxed=True)
        try:
            bind_mock = AsyncMock(return_value=_list_bindings_result())
            with (
                patch(
                    "app.api.v1.ext.my_app_authorizations.ApplicationService.get_application",
                    new=AsyncMock(return_value=OTHER_APP),
                ),
                patch(
                    "app.api.v1.ext.my_app_authorizations.ApplicationService.list_applications",
                    new=AsyncMock(return_value=[OTHER_APP]),
                ),
                patch(
                    "app.api.v1.ext.my_app_authorizations.UserMcpCredentialService.bind_credential",
                    new=bind_mock,
                ),
                patch(
                    "app.api.v1.ext.my_app_authorizations.UserMcpCredentialService.list_bindings",
                    new=AsyncMock(return_value=_list_bindings_result()),
                ),
            ):
                resp = client.put(
                    "/api/v1/ext/my-app-authorizations/app_other",
                    json={"username": "carol", "password": "pw"},
                )
            assert resp.status_code == 200
            assert bind_mock.call_args.kwargs["platform_user_id"] == "user_plat_1"
            assert bind_mock.call_args.kwargs["username"] == "carol"
            # 跨应用不传锚（空串）——由 bind_credential 从登录响应提取
            # 稳定用户 ID（userid_jsonpath），提取不到退回登录名
            assert bind_mock.call_args.kwargs["identity_key"] == ""
        finally:
            cleanup()

    def test_application_not_found(self, client) -> None:
        cleanup = _override(_principal(bound=True), relaxed=True)
        try:
            with patch(
                "app.api.v1.ext.my_app_authorizations.ApplicationService.get_application",
                new=AsyncMock(return_value=None),
            ):
                resp = client.put(
                    "/api/v1/ext/my-app-authorizations/app_missing",
                    json={"username": "alice", "password": "pw"},
                )
            assert resp.status_code == 404
            assert resp.json()["error"]["code"] == "APPLICATION_NOT_FOUND"
        finally:
            cleanup()

    def test_invalid_credentials_mapped(self, client) -> None:
        """bind_credential 的 PermissionError → MCP_CREDENTIAL_INVALID。"""
        cleanup = _override(_principal(bound=True), relaxed=True)
        try:
            with (
                patch(
                    "app.api.v1.ext.my_app_authorizations.ApplicationService.get_application",
                    new=AsyncMock(return_value=APP),
                ),
                patch(
                    "app.api.v1.ext.my_app_authorizations.UserMcpCredentialService.bind_credential",
                    new=AsyncMock(side_effect=PermissionError("登录失败：密码错误")),
                ),
            ):
                resp = client.put(
                    f"/api/v1/ext/my-app-authorizations/{APP_ID}",
                    json={"username": "alice", "password": "bad"},
                )
            assert resp.status_code == 422
            assert resp.json()["error"]["code"] == "MCP_CREDENTIAL_INVALID"
            assert "密码错误" in resp.json()["error"]["message"]
        finally:
            cleanup()


# ---------------------------------------------------------------------------
# GET /available-apps + GET / + DELETE（完整鉴权）
# ---------------------------------------------------------------------------


class TestFullAuthEndpoints:
    def test_available_apps_marks_key_app(self, client) -> None:
        cleanup = _override(_principal(bound=True))
        try:
            with patch(
                "app.api.v1.ext.my_app_authorizations.ApplicationService.list_applications",
                new=AsyncMock(return_value=[APP, OTHER_APP, {"_id": "app_nologin"}]),
            ):
                resp = client.get("/api/v1/ext/my-app-authorizations/available-apps")
            assert resp.status_code == 200
            data = resp.json()
            assert data["key_app_id"] == APP_ID
            assert len(data["items"]) == 2  # 无 login_config 的应用不出现
            by_id = {item["id"]: item for item in data["items"]}
            assert by_id[APP_ID]["is_key_app"] is True
            assert by_id["app_other"]["is_key_app"] is False
        finally:
            cleanup()

    def test_list_bindings(self, client) -> None:
        cleanup = _override(_principal(bound=True))
        try:
            with (
                patch(
                    "app.api.v1.ext.my_app_authorizations.UserMcpCredentialService.list_bindings",
                    new=AsyncMock(return_value=_list_bindings_result()),
                ),
                patch(
                    "app.api.v1.ext.my_app_authorizations.ApplicationService.list_applications",
                    new=AsyncMock(return_value=[APP]),
                ),
            ):
                resp = client.get("/api/v1/ext/my-app-authorizations")
            assert resp.status_code == 200
            data = resp.json()
            assert data["platform_user_id"] == "user_plat_1"
            assert data["bindings"][0]["password_masked"] == "***"
        finally:
            cleanup()

    def test_revoke_calls_unbind(self, client) -> None:
        cleanup = _override(_principal(bound=True))
        try:
            unbind_mock = AsyncMock(return_value=None)
            with (
                patch(
                    "app.api.v1.ext.my_app_authorizations.UserMcpCredentialService.unbind_credential",
                    new=unbind_mock,
                ),
                patch(
                    "app.api.v1.ext.my_app_authorizations.UserMcpCredentialService.list_bindings",
                    new=AsyncMock(return_value=None),
                ),
                patch(
                    "app.api.v1.ext.my_app_authorizations.ApplicationService.list_applications",
                    new=AsyncMock(return_value=[]),
                ),
            ):
                resp = client.delete(f"/api/v1/ext/my-app-authorizations/{APP_ID}")
            assert resp.status_code == 200
            unbind_mock.assert_awaited_once_with(
                platform_user_id="user_plat_1", app_id=APP_ID
            )
        finally:
            cleanup()
