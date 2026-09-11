"""Tests for ToolNodeExecutor — 按来源三分的执行契约。

覆盖：
1. markdown/skill 透传（不执行，instructions 作为上下文输出）
2. openapi/code 直调（build_tool 构建后 ainvoke，输出 {result, tool_id}）
3. build_tool 返回 None → 节点失败
4. 超时重试耗尽 → 节点失败
5. 工具不存在 / tool_id 未配置 → 失败
6. user_args enc: 加密字段解密后传给 build_tool

DB 访问与 build_tool 全部 mock（conftest 规则：不连真实 Mongo）。
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from app.core.crypto import encrypt_secret
from app.engine.workflow.node_executor import ToolNodeExecutor


def _make(config: dict) -> ToolNodeExecutor:
    return ToolNodeExecutor(node_id="tool_1", node_config=config)


def _patch_db(monkeypatch, tool_doc: dict | None):
    """Mock app.db.mongodb.get_database → tools.find_one 返回 tool_doc。"""
    find_one = AsyncMock(return_value=tool_doc)
    db = {"tools": type("Coll", (), {"find_one": staticmethod(find_one)})()}
    monkeypatch.setattr("app.db.mongodb.get_database", lambda: db)
    return find_one


class _FakeTool:
    """Minimal BaseTool stand-in with a controllable ainvoke."""

    def __init__(self, result="ok", delay: float = 0.0, exc: Exception | None = None):
        self.result = result
        self.delay = delay
        self.exc = exc
        self.calls = 0

    async def ainvoke(self, params):
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.exc:
            raise self.exc
        return self.result


# ── markdown / skill：透传 ────────────────────────────────────────────


async def test_markdown_tool_passes_instructions(monkeypatch):
    doc = {
        "_id": "tool_1",
        "name": "pdf-skill",
        "description": "PDF 处理技能",
        "source": "markdown",
        "instructions": "# Steps\n...",
    }
    _patch_db(monkeypatch, doc)

    result = await _make({"tool_id": "tool_1", "params": {"q": "x"}}).execute({})

    assert result.success
    out = result.output
    assert out["tool_name"] == "pdf-skill"
    assert out["instructions"] == "# Steps\n..."
    assert "Agent" in out["note"]  # 明确提示需由 Agent 节点执行


# ── openapi / code：直调 ──────────────────────────────────────────────


async def test_openapi_tool_direct_invoke(monkeypatch):
    doc = {"_id": "tool_2", "name": "send-http", "source": "openapi", "endpoint": {"url": "https://x"}}
    _patch_db(monkeypatch, doc)
    fake = _FakeTool(result={"status": 200})
    monkeypatch.setattr("app.engine.tool.tool_builder.build_tool", AsyncMock(return_value=fake))

    result = await _make({"tool_id": "tool_2", "params": {"path": "/a"}}).execute({})

    assert result.success
    assert result.output == {"result": {"status": 200}, "tool_id": "tool_2"}


async def test_code_tool_direct_invoke(monkeypatch):
    doc = {"_id": "tool_3", "name": "calc", "source": "code", "code": "def run(x): return x"}
    _patch_db(monkeypatch, doc)
    fake = _FakeTool(result="42")
    monkeypatch.setattr("app.engine.tool.tool_builder.build_tool", AsyncMock(return_value=fake))

    result = await _make({"tool_id": "tool_3", "params": {"x": 1}}).execute({})

    assert result.success
    assert result.output == {"result": "42", "tool_id": "tool_3"}


async def test_user_args_encrypted_field_decrypted(monkeypatch):
    """user_args sensitive 字段（enc: 前缀）解密后传给 build_tool。"""
    doc = {
        "_id": "tool_4",
        "name": "api-tool",
        "source": "openapi",
        "user_args_schema": {"properties": {"token": {"type": "string", "sensitive": True}}},
    }
    _patch_db(monkeypatch, doc)
    captured: dict = {}

    async def fake_build(tool_doc, *, user_args=None):
        captured.update(user_args or {})
        return _FakeTool(result="ok")

    monkeypatch.setattr("app.engine.tool.tool_builder.build_tool", fake_build)

    secret = "raw-token-value"
    config = {"tool_id": "tool_4", "user_args": {"token": f"enc:{encrypt_secret(secret)}", "env": "prod"}}
    result = await _make(config).execute({})

    assert result.success
    assert captured == {"token": secret, "env": "prod"}  # enc: 已解密，明文字段原样


async def test_build_tool_none_fails(monkeypatch):
    doc = {"_id": "tool_5", "name": "broken", "source": "openapi"}
    _patch_db(monkeypatch, doc)
    monkeypatch.setattr("app.engine.tool.tool_builder.build_tool", AsyncMock(return_value=None))

    result = await _make({"tool_id": "tool_5"}).execute({})

    assert not result.success
    assert "构建失败" in result.error_message


async def test_timeout_retries_exhausted(monkeypatch):
    doc = {"_id": "tool_6", "name": "slow", "source": "openapi"}
    _patch_db(monkeypatch, doc)
    fake = _FakeTool(delay=0.2)  # 超过 timeout_ms=50
    monkeypatch.setattr("app.engine.tool.tool_builder.build_tool", AsyncMock(return_value=fake))

    result = await _make(
        {"tool_id": "tool_6", "timeout_ms": 50, "retry_policy": {"max_retries": 1, "backoff_ms": 10}}
    ).execute({})

    assert not result.success
    assert "超时" in result.error_message
    assert fake.calls == 2  # 初次 + 1 次重试


async def test_retry_succeeds_on_second_attempt(monkeypatch):
    doc = {"_id": "tool_7", "name": "flaky", "source": "code"}
    _patch_db(monkeypatch, doc)

    class FlakyTool(_FakeTool):
        async def ainvoke(self, params):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("transient")
            return "recovered"

    flaky = FlakyTool()
    monkeypatch.setattr("app.engine.tool.tool_builder.build_tool", AsyncMock(return_value=flaky))

    result = await _make(
        {"tool_id": "tool_7", "retry_policy": {"max_retries": 2, "backoff_ms": 1}}
    ).execute({})

    assert result.success
    assert result.output["result"] == "recovered"


# ── 失败路径 ──────────────────────────────────────────────────────────


async def test_tool_not_found(monkeypatch):
    _patch_db(monkeypatch, None)
    result = await _make({"tool_id": "missing"}).execute({})
    assert not result.success
    assert "不存在" in result.error_message


async def test_missing_tool_id():
    result = await _make({}).execute({})
    assert not result.success
    assert "tool_id" in result.error_message


# ── 组织库工具（uto_ 前缀，治理校验走 resolve_org_tool） ─────────────


async def test_user_tool_direct_invoke(monkeypatch):
    """uto_ 工具：resolve_org_tool（published+enabled）通过后按 code 直调，
    凭证用工具级统一配置（org_user_args 解密值）。"""
    doc = {"_id": "uto_1", "name": "my-tool", "source": "code", "code": "def run(): pass"}
    monkeypatch.setattr(
        "app.services.user_tool_service.UserToolService.resolve_org_tool",
        AsyncMock(return_value=(doc, {"token": "org-tk"})),
    )
    monkeypatch.setattr(
        "app.services.user_tool_service.UserToolService.record_load",
        AsyncMock(return_value=None),
    )
    captured: dict = {}

    async def fake_build(d, *, user_args=None):
        captured.update(user_args or {})
        return _FakeTool(result="user-tool-ok")

    monkeypatch.setattr("app.engine.tool.tool_builder.build_tool", fake_build)

    result = await _make({"tool_id": "uto_1"}).execute({})

    assert result.success
    assert result.output == {"result": "user-tool-ok", "tool_id": "uto_1"}
    assert captured == {"token": "org-tk"}  # 工具级凭证注入


async def test_user_tool_unavailable(monkeypatch):
    """uto_ 工具：resolve_org_tool 返回 None（未开启/停用/未过审）→ 节点失败。"""
    monkeypatch.setattr(
        "app.services.user_tool_service.UserToolService.resolve_org_tool",
        AsyncMock(return_value=None),
    )
    result = await _make({"tool_id": "uto_x"}).execute({})
    assert not result.success
    assert "不可用" in result.error_message

