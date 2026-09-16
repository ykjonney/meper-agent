"""ToolTester 用例 — 工具定义试跑与 AI 测试用例生成。

覆盖：
1. code 工具试跑成功（真实本地降级执行）
2. code 工具沙箱失败（Error: 文本）→ ok=False
3. 依赖白名单违规 → UserToolError（构建前拦截）
4. 非法 source / 非法名 → UserToolError
5. openapi 工具试跑（mock httpx）
6. AI 生成用例：围栏解析 + 未声明参数被剔除
"""
from __future__ import annotations

import json

import pytest
from app.services.tool_tester import generate_cases, run_once
from app.services.user_tool_service import UserToolError

CODE_DEF = {
    "name": "add-tool",
    "description": "加法",
    "source": "code",
    "code": "def run(a: int, b: int = 1) -> int:\n    return a + b\n",
    "llm_args_schema": {
        "type": "object",
        "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
        "required": ["a"],
    },
}


# ── 1. code 试跑成功 ─────────────────────────────────────────────────


async def test_run_once_code_ok():
    result = await run_once(CODE_DEF, {"a": 2, "b": 3}, {})
    assert result["ok"] is True
    assert result["result"] == "5"  # int 返回自动 JSON 化后 print


# ── 2. 沙箱失败（Error: 文本）→ ok=False ─────────────────────────────


async def test_run_once_code_error_text():
    result = await run_once(CODE_DEF, {"a": "不是数字"}, {})
    assert result["ok"] is False
    assert "Error" in result["error"]  # TypeError 回显给调用方


# ── 3. 依赖白名单违规 → 构建前拦截 ──────────────────────────────────


async def test_run_once_rejects_invalid_import():
    bad = {**CODE_DEF, "code": "import flask\n\n\ndef run(a: int) -> int:\n    return a\n"}
    with pytest.raises(UserToolError, match="依赖不可用.*flask"):
        await run_once(bad, {"a": 1}, {})


# ── 4. 非法 source / 非法名 ──────────────────────────────────────────


async def test_run_once_rejects_bad_source_and_name():
    with pytest.raises(UserToolError, match="仅支持 code / openapi"):
        await run_once({**CODE_DEF, "source": "mcp"}, {}, {})
    with pytest.raises(UserToolError, match="工具名"):
        await run_once({**CODE_DEF, "name": "非法名字"}, {}, {})


# ── 5. openapi 试跑（mock httpx） ────────────────────────────────────


async def test_run_once_openapi(monkeypatch):
    import httpx

    class _FakeResp:
        text = "ok-text"

        def json(self):
            return {}

    class _FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, headers=None, params=None):
            return _FakeResp()

    monkeypatch.setattr(httpx, "AsyncClient", lambda timeout=None: _FakeClient())

    definition = {
        "name": "http-tool",
        "description": "GET 封装",
        "source": "openapi",
        "endpoint": {"method": "GET", "url": "https://x.example.com/v1"},
        "llm_args_schema": {},
    }
    result = await run_once(definition, {}, {})
    assert result["ok"] is True
    assert result["result"] == "ok-text"


# ── 6. AI 生成用例 ───────────────────────────────────────────────────


def _patch_llm(monkeypatch, reply: str):
    """打桩 tool_tester 模块的 resolve_chat_model（公共解析入口）。"""

    class _FakeLLM:
        async def ainvoke(self, messages):
            from langchain_core.messages import AIMessage
            return AIMessage(content=reply)

    async def _resolve(model_id: str = "", *, temperature: float = 0.2):
        return _FakeLLM()

    monkeypatch.setattr("app.services.tool_tester.resolve_chat_model", _resolve)


async def test_generate_cases_parses_and_filters(monkeypatch):
    reply = (
        "已生成 2 个用例。\n```json\n"
        + json.dumps({"cases": [
            {"name": "常规加法", "description": "验证正常路径", "params": {"a": 1, "b": 2}},
            {"name": "缺省参数", "description": "b 缺省", "params": {"a": 5, "未声明参数": "x"}},
        ]}, ensure_ascii=False)
        + "\n```"
    )
    _patch_llm(monkeypatch, reply)

    result = await generate_cases(CODE_DEF)

    assert len(result["cases"]) == 2
    assert result["cases"][0]["params"] == {"a": 1, "b": 2}
    # 未在 llm_args_schema 声明的参数被剔除
    assert result["cases"][1]["params"] == {"a": 5}


async def test_generate_cases_rejects_unformatted_reply(monkeypatch):
    _patch_llm(monkeypatch, "我不会输出 JSON")
    with pytest.raises(UserToolError, match="未按格式输出"):
        await generate_cases(CODE_DEF)


# ── 7. 按已保存工具试跑（工具节点调试路径） ──────────────────────────


async def test_run_saved_uto_tool(monkeypatch):
    """uto_ 工具：resolve_org_tool（治理校验+凭证解密）通过后按生产语义试跑。"""
    from unittest.mock import AsyncMock

    from app.services import tool_tester
    from app.services.user_tool_service import UserToolService

    doc = {**CODE_DEF, "_id": "uto_1"}
    monkeypatch.setattr(
        UserToolService, "resolve_org_tool",
        AsyncMock(return_value=(doc, {"password": "org-pwd"})),
    )
    captured: dict = {}

    async def fake_run_once(definition, params, user_args):
        captured.update(definition=definition, params=params, user_args=user_args)
        return {"ok": True, "result": "9", "error": None}

    monkeypatch.setattr(tool_tester, "run_once", fake_run_once)

    result = await tool_tester.run_saved_once("uto_1", {"a": 4, "b": 5}, {"password": "override"})

    assert result["ok"] is True
    assert captured["params"] == {"a": 4, "b": 5}
    # 组织凭证与临时覆盖合并（覆盖优先）
    assert captured["user_args"] == {"password": "override"}
    assert captured["definition"]["_id"] == "uto_1"


async def test_run_saved_uto_tool_unavailable(monkeypatch):
    """uto_ 工具未开启/停用 → 治理口径拒绝试跑。"""
    from unittest.mock import AsyncMock

    from app.services import tool_tester
    from app.services.user_tool_service import UserToolService

    monkeypatch.setattr(
        UserToolService, "resolve_org_tool", AsyncMock(return_value=None)
    )
    with pytest.raises(UserToolError, match="不可用"):
        await tool_tester.run_saved_once("uto_x", {}, {})
