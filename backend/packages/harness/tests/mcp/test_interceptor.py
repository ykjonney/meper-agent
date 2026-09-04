"""MCP interceptor 测试 — 验证凭证兑换 / 透传分流逻辑（mcp-credential-broker 新模型）。

不连真实 MCP server，直接构造 fake MCPToolCallRequest + fake handler，
验证 interceptor 在两条路径下的行为:
- 内部路径（无 token_record_id / 无 resolver）: 透传 request, 不改 headers,
  使用 connection 配置的静态凭证。
- 外部路径（有 token_record_id + resolver）: 调 resolver 兑换该用户对该 MCP
  的绑定凭证并按 auth_type 覆盖 headers; 未绑定 / 兑换失败返回 isError 的
  CallToolResult（不抛异常, 让 adapter 走 ToolException 路径）。
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agent_flow_harness.mcp.loader import (
    _user_token_interceptor,
    set_credential_resolver,
)
from agent_flow_harness.mcp.user_token_context import (
    set_token_record_id_context,
)


class _FakeCallToolResult:
    """模拟 mcp.types.CallToolResult（测试环境里 mcp 包不可用）。"""

    def __init__(self, content=None, isError: bool = False):
        self.content = content
        self.isError = isError


class _FakeTextContent:
    """模拟 mcp.types.TextContent。"""

    def __init__(self, type: str = "text", text: str = ""):
        self.type = type
        self.text = text


@dataclass
class _FakeRequest:
    """模拟 langchain-mcp-adapters 的 MCPToolCallRequest。"""

    name: str = "query_order"
    args: dict = None
    server_name: str = "partner"
    headers: dict = None

    def override(self, **updates):
        # 模拟 MCPToolCallRequest.override: 返回新的 request,
        # 替换指定字段（其它字段保持引用相同）。
        return _FakeRequest(
            name=self.name,
            args=self.args,
            server_name=self.server_name,
            headers=updates.get("headers", self.headers),
        )


class _FakeResolver:
    """按构造时的返回值模拟 CredentialResolver.resolve。"""

    def __init__(self, result=None, error: Exception | None = None):
        self._result = result
        self._error = error

    async def resolve(self, platform_user_id: str, server_name: str):
        if self._error is not None:
            raise self._error
        return self._result


@pytest.fixture(autouse=True)
def _reset_env(monkeypatch):
    # 测试目录 tests/mcp 与 python-mcp-sdk 的 mcp 包重名, pytest 收集时
    # import mcp 会解析到本目录而非 SDK。给 sys.modules 注入假 mcp.types,
    # 让 loader._make_error_result 的 `from mcp.types import ...` 可用。
    monkeypatch.setitem(
        sys.modules,
        "mcp.types",
        SimpleNamespace(
            CallToolResult=_FakeCallToolResult,
            TextContent=_FakeTextContent,
        ),
    )
    # 每个用例前后清理 token_record_id 与注入的 resolver，避免跨用例污染
    set_token_record_id_context(None)
    set_credential_resolver(None)
    yield
    set_token_record_id_context(None)
    set_credential_resolver(None)


class TestUserTokenInterceptor:
    async def test_internal_path_passes_through(self):
        """内部路径（无 token_record_id）→ 不修改 request, 透传给 handler。"""
        captured: list = []

        async def handler(req):
            captured.append(req)
            return {"ok": True}

        req = _FakeRequest(headers={"Authorization": "Bearer static-tok"})
        result = await _user_token_interceptor(req, handler)

        assert result == {"ok": True}
        assert len(captured) == 1
        # handler 收到的就是原 request（未 override）
        assert captured[0] is req
        # Authorization 没被改
        assert captured[0].headers == {"Authorization": "Bearer static-tok"}

    async def test_internal_path_no_resolver_passes_through(self):
        """有 token_record_id 但未注入 resolver → 也走内部路径透传。"""
        set_token_record_id_context("platform-user-1")
        captured: list = []

        async def handler(req):
            captured.append(req)
            return {"ok": True}

        req = _FakeRequest(headers={"Authorization": "Bearer static-tok"})
        await _user_token_interceptor(req, handler)

        assert captured[0] is req
        assert captured[0].headers == {"Authorization": "Bearer static-tok"}

    async def test_external_path_overrides_authorization(self):
        """外部路径 → 兑换凭证按 auth_type 覆盖 Authorization。"""
        set_token_record_id_context("platform-user-1")
        set_credential_resolver(
            _FakeResolver({"auth_type": "bearer_token", "token": "user-abc-123"})
        )
        captured: list = []

        async def handler(req):
            captured.append(req)
            return {"ok": True}

        req = _FakeRequest(headers={"Authorization": "Bearer static-tok"})
        await _user_token_interceptor(req, handler)

        assert len(captured) == 1
        # override 后的 request headers 被替换为兑换出的凭证
        assert captured[0].headers == {"Authorization": "Bearer user-abc-123"}

    async def test_external_path_injects_when_no_static_header(self):
        """外部路径 → 即便 request 原本没有 headers 也注入 Authorization。"""
        set_token_record_id_context("platform-user-1")
        set_credential_resolver(
            _FakeResolver({"auth_type": "bearer", "token": "user-xyz"})
        )
        captured: list = []

        async def handler(req):
            captured.append(req)
            return {"ok": True}

        req = _FakeRequest(headers=None)
        await _user_token_interceptor(req, handler)

        assert captured[0].headers == {"Authorization": "Bearer user-xyz"}

    async def test_external_path_unbound_returns_error(self):
        """外部路径未绑定（resolver 返回 None）→ 返回 isError 结果, 不调 handler。"""
        set_token_record_id_context("platform-user-1")
        set_credential_resolver(_FakeResolver(None))
        handler = AsyncMock(return_value={"ok": True})

        result = await _user_token_interceptor(_FakeRequest(), handler)

        handler.assert_not_awaited()
        assert getattr(result, "isError", False) is True

    async def test_external_path_unbound_exception_returns_marked_error(self):
        """未绑定（McpCredentialUnbound）→ isError + 机器可读 JSON 标记
        + 引导 LLM 调 request_app_authorization 的指令文案。"""
        import json

        from agent_flow_harness.mcp.errors import McpCredentialUnbound

        set_token_record_id_context("platform-user-1")
        set_credential_resolver(
            _FakeResolver(
                error=McpCredentialUnbound("app_1", "合作系统", "partner")
            )
        )
        handler = AsyncMock(return_value={"ok": True})

        result = await _user_token_interceptor(_FakeRequest(), handler)

        handler.assert_not_awaited()
        assert getattr(result, "isError", False) is True
        text = result.content[0].text
        # 首行 JSON 标记（前端兜底解析 + LLM 读 app_id/app_name）
        marker = json.loads(text.split("\n")[0])
        assert marker["mcp_credential_error"] == "UNBOUND"
        assert marker["app_id"] == "app_1"
        assert marker["app_name"] == "合作系统"
        # 文案引导走授权工具、禁止索要凭证
        assert "request_app_authorization" in text
        assert "禁止向用户索要" in text

    async def test_external_path_invalid_credentials_returns_marked_error(self):
        """凭证失效（McpCredentialInvalid，密码/用户名被修改）→ INVALID
        标记 + 更新凭证引导文案（身份映射不受影响）。"""
        import json

        from agent_flow_harness.mcp.errors import McpCredentialInvalid

        set_token_record_id_context("platform-user-1")
        set_credential_resolver(
            _FakeResolver(
                error=McpCredentialInvalid(
                    "app_1", "合作系统", "partner", detail="登录失败：密码错误"
                )
            )
        )
        handler = AsyncMock(return_value={"ok": True})

        result = await _user_token_interceptor(_FakeRequest(), handler)

        handler.assert_not_awaited()
        assert getattr(result, "isError", False) is True
        text = result.content[0].text
        marker = json.loads(text.split("\n")[0])
        assert marker["mcp_credential_error"] == "INVALID"
        assert marker["app_id"] == "app_1"
        # 文案：失效提示（含细节）+ 引导更新凭证
        assert "凭证已失效" in text
        assert "密码错误" in text
        assert "request_app_authorization" in text
        assert "禁止向用户索要" in text

    async def test_external_path_resolver_error_returns_error(self):
        """外部路径兑换异常 → 返回 isError 结果, 不调 handler。"""
        set_token_record_id_context("platform-user-1")
        set_credential_resolver(_FakeResolver(error=RuntimeError("db down")))
        handler = AsyncMock(return_value={"ok": True})

        result = await _user_token_interceptor(_FakeRequest(), handler)

        handler.assert_not_awaited()
        assert getattr(result, "isError", False) is True

    async def test_external_path_handler_called_once(self):
        """外部路径凭证就绪 → handler 恰好调一次, 且收到 override 后的 request。"""
        set_token_record_id_context("platform-user-1")
        set_credential_resolver(
            _FakeResolver({"auth_type": "bearer_token", "token": "user-1"})
        )
        handler = AsyncMock(return_value={"done": True})

        result = await _user_token_interceptor(_FakeRequest(), handler)

        handler.assert_awaited_once()
        assert result == {"done": True}

    async def test_internal_path_handler_called_once(self):
        """内部路径 → handler 也恰好调一次。"""
        handler = AsyncMock(return_value={"done": True})

        await _user_token_interceptor(_FakeRequest(), handler)

        handler.assert_awaited_once()
