"""Tests for UserMcpCredentialService — 验证提取稳定用户 ID + 身份锚点优先级链。

聚焦 v4.2 身份锚点：
- ``_verify_credentials`` 按 ``userid_jsonpath``（默认 userId，空串禁用）
  从登录响应提取稳定用户 ID，提取不到返回 None（不报错）
- ``bind_credential`` 的 identity_key 优先级：
  显式传入（key 应用 introspection sub）> 登录响应 userId > 登录名
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from app.core.errors import ConflictError
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


def _login_response(payload: dict, status_code: int = 200):
    """构造 _verify_credentials 的 httpx 假响应（默认 200）。"""
    resp = MagicMock()
    resp.status_code = status_code
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

    async def test_4xx_raises_permission_error(self) -> None:
        """4xx（密码错误返回 401/403 的接入方）→ PermissionError（INVALID
        语义，出授权卡引导重输）；不能落入 raise_for_status 的「不可用」。"""
        client = _login_response({}, status_code=401)
        with patch(
            "app.services.user_mcp_credential_service.httpx.AsyncClient",
            return_value=client,
        ), pytest.raises(PermissionError, match="HTTP 401"):
            await _verify_credentials(LOGIN_CONFIG, "zhangsan", "bad")

    async def test_5xx_raises_app_unavailable(self) -> None:
        """5xx → McpAppUnavailable（授权提交路径转 422 MCP_APP_UNAVAILABLE，
        提示稍后重试，不误导用户重输密码）。"""
        from agent_flow_harness.mcp.errors import McpAppUnavailable

        resp = MagicMock()
        resp.status_code = 500
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Server error '500'",
            request=httpx.Request("POST", "https://oa.example.com/login"),
            response=httpx.Response(500),
        )
        client = MagicMock()
        client.request = AsyncMock(return_value=resp)
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)
        with patch(
            "app.services.user_mcp_credential_service.httpx.AsyncClient",
            return_value=client,
        ), pytest.raises(McpAppUnavailable):
            await _verify_credentials(LOGIN_CONFIG, "zhangsan", "pw")

    async def test_network_error_raises_app_unavailable(self) -> None:
        """网络异常（超时/连接失败）→ 同样归 McpAppUnavailable。"""
        from agent_flow_harness.mcp.errors import McpAppUnavailable

        client = MagicMock()
        client.request = AsyncMock(side_effect=httpx.ConnectTimeout("timed out"))
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)
        with patch(
            "app.services.user_mcp_credential_service.httpx.AsyncClient",
            return_value=client,
        ), pytest.raises(McpAppUnavailable):
            await _verify_credentials(LOGIN_CONFIG, "zhangsan", "pw")


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
                "app.services.user_mcp_credential_service"
                ".ExternalIdentityService.find_by_sub",
                new=AsyncMock(return_value=None),
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


class TestBindCredentialOrphanTakeover:
    """bind_credential 的孤儿映射接管（存量自愈）。

    孤儿映射（sub 指向已删除平台用户）会让 strict 鉴权 401 且引导用户
    去首绑门页重新授权；重新授权生成新 platform_user_id，若不接管，
    upsert 的抢注保护会以 EXTERNAL_IDENTITY_ALREADY_BOUND 拒绝——
    用户自救死锁。接管仅限「旧用户已删除」；禁用/活用户维持冲突。
    """

    @staticmethod
    async def _bind_with_existing(
        existing_mapping: dict | None,
        prev_user: dict | None,
        *,
        upsert_error: Exception | None = None,
    ) -> SimpleNamespace:
        """跑一次 bind_credential（sub 已有映射场景），返回各 mock。

        Args:
            existing_mapping: find_by_sub 返回的既有映射（None = 无映射）。
            prev_user: 旧 platform_user_id 的回查结果（None = 已删除）。
            upsert_error: upsert 抛出的异常（模拟真实抢注冲突语义）。
        """
        client = _login_response({"data": {"token": "tok"}})
        captured: dict = {}
        delete_mock = AsyncMock(return_value=1)
        raised: BaseException | None = None
        with (
            patch(
                "app.services.user_mcp_credential_service.httpx.AsyncClient",
                return_value=client,
            ),
            patch(
                "app.services.user_mcp_credential_service"
                ".ExternalIdentityService.find_by_sub",
                new=AsyncMock(return_value=existing_mapping),
            ),
            patch(
                "app.services.user_mcp_credential_service"
                ".ExternalIdentityService.delete_by_sub",
                new=delete_mock,
            ),
            patch(
                "app.services.user_mcp_credential_service.ExternalIdentityService.upsert",
                new=AsyncMock(
                    side_effect=upsert_error
                    or (lambda sub, uid: captured.update(
                        sub=sub, platform_user_id=uid
                    ))
                ),
            ),
            patch(
                "app.services.user_service.UserService.get_user_by_id",
                new=AsyncMock(return_value=prev_user),
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
            try:
                await UserMcpCredentialService.bind_credential(
                    platform_user_id="user_p1",
                    app_id="app_1",
                    username="zhangsan",
                    password="pw",
                    login_config=LOGIN_CONFIG,
                    identity_key="sub_anchor",
                )
            except Exception as exc:  # noqa: BLE001 —— 测试记录后由用例断言
                raised = exc
        return SimpleNamespace(
            captured=captured, delete_mock=delete_mock, raised=raised
        )

    async def test_orphan_mapping_of_deleted_user_taken_over(self) -> None:
        """旧映射指向已删用户 → 清孤儿后 upsert 新绑定（接管成功）。"""
        out = await self._bind_with_existing(
            existing_mapping={"sub": "app_1:sub_anchor", "platform_user_id": "user_dead"},
            prev_user=None,
        )
        assert out.raised is None
        out.delete_mock.assert_awaited_once_with("app_1:sub_anchor")
        assert out.captured["sub"] == "app_1:sub_anchor"
        assert out.captured["platform_user_id"] == "user_p1"

    async def test_same_user_rebind_skips_takeover(self) -> None:
        """既有映射即本人（重新提交凭证）→ 不查不删，直接 upsert。"""
        out = await self._bind_with_existing(
            existing_mapping={"sub": "app_1:sub_anchor", "platform_user_id": "user_p1"},
            prev_user=None,
        )
        assert out.raised is None
        out.delete_mock.assert_not_awaited()
        assert out.captured["platform_user_id"] == "user_p1"

    async def test_live_owner_conflict_preserved(self) -> None:
        """旧映射指向活着的其他用户 → 不删映射，抢注冲突照抛。"""
        out = await self._bind_with_existing(
            existing_mapping={"sub": "app_1:sub_anchor", "platform_user_id": "user_other"},
            prev_user={"_id": "user_other", "status": "active"},
            upsert_error=ConflictError(
                code="EXTERNAL_IDENTITY_ALREADY_BOUND",
                message="该外部身份已绑定到其他平台账号",
            ),
        )
        assert isinstance(out.raised, ConflictError)
        assert out.raised.code == "EXTERNAL_IDENTITY_ALREADY_BOUND"
        out.delete_mock.assert_not_awaited()

    async def test_disabled_owner_conflict_preserved(self) -> None:
        """旧映射指向禁用用户 → 同样不接管（管理员停用不被绕过）。"""
        out = await self._bind_with_existing(
            existing_mapping={"sub": "app_1:sub_anchor", "platform_user_id": "user_other"},
            prev_user={"_id": "user_other", "status": "disabled"},
            upsert_error=ConflictError(
                code="EXTERNAL_IDENTITY_ALREADY_BOUND",
                message="该外部身份已绑定到其他平台账号",
            ),
        )
        assert isinstance(out.raised, ConflictError)
        assert out.raised.code == "EXTERNAL_IDENTITY_ALREADY_BOUND"
        out.delete_mock.assert_not_awaited()


class TestUnbindCredential:
    """unbind_credential——按 (app, user) 全维度清身份映射。

    只删 binding 记录的单个 sub 不够：多版本锚（v4.1 登录名 / v4.2
    introspection 稳定 ID / jwt 端点登录响应 userId）可能并存，任一
    残留都会被鉴权放行（legacy 维度还会被在线升级复活），表现为
    「取消授权了 client 仍能直接进入」。
    """

    @staticmethod
    async def _unbind(doc: dict | None) -> object:
        """跑一次 unbind_credential，返回 delete_by_app_and_user 的 mock。"""
        delete_mock = AsyncMock(return_value=1)
        with (
            patch(
                "app.services.user_mcp_credential_service.UserMcpCredentialService._collection",
                return_value=MagicMock(
                    find_one=AsyncMock(return_value=doc),
                    update_one=AsyncMock(),
                ),
            ),
            patch(
                "app.services.user_mcp_credential_service"
                ".ExternalIdentityService.delete_by_app_and_user",
                new=delete_mock,
            ),
            patch(
                "app.services.user_mcp_credential_service.clear_app_session_cache",
                new=AsyncMock(),
            ),
            patch(
                "app.services.user_mcp_credential_service"
                ".UserMcpCredentialService.list_bindings",
                new=AsyncMock(return_value={"bindings": []}),
            ),
        ):
            result = await UserMcpCredentialService.unbind_credential(
                platform_user_id="user_p1", app_id="app_1"
            )
        return SimpleNamespace(delete_mock=delete_mock, result=result)

    async def test_unbind_deletes_all_identity_dimensions(self) -> None:
        """正常解绑：按 (app, user) 全维度清映射 + 删凭证 + 清缓存。"""
        out = await self._unbind(
            {"platform_user_id": "user_p1", "app_bindings": {"app_1": {}}}
        )
        out.delete_mock.assert_awaited_once_with("app_1", "user_p1")
        assert out.result is not None

    async def test_unbind_without_binding_still_cleans_orphan_identities(self) -> None:
        """凭证已无该应用（此前取消过但残留了别的维度映射）→ 仍清孤儿
        映射（自愈存量状态），不改凭证记录。"""
        out = await self._unbind(
            {"platform_user_id": "user_p1", "app_bindings": {"app_other": {}}}
        )
        out.delete_mock.assert_awaited_once_with("app_1", "user_p1")
        assert out.result is not None

    async def test_unbind_without_record_still_cleans_identities(self) -> None:
        """凭证记录不存在 → 返回 None，但仍清孤儿映射。"""
        out = await self._unbind(None)
        out.delete_mock.assert_awaited_once_with("app_1", "user_p1")
        assert out.result is None
