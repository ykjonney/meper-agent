"""ToolBuilder 邮件发送工具用例——真实场景验证 openapi/code 两条构建路径。

锁定三个修复：
1. render_dict 渲染数组内的模板（邮件 API body "to": ["{{llm.to}}"]）
2. code 工具无沙箱 fallback 时 user_args 以 USER_ 环境变量注入（SMTP 凭证可达），
   且执行后恢复进程环境
3. response_path 支持数组下标（data.items.0.name）
"""
from __future__ import annotations

import httpx
from app.engine.tool.tool_builder import build_tool, render_dict

# ── 1. 模板渲染：数组内的占位符 ───────────────────────────────────────


def test_render_dict_includes_list_values():
    """邮件 body 的收件人数组必须被渲染——修复前 to 是字面 '{{llm.to}}'。"""
    body = {
        "from": "{{user.from_addr}}",
        "to": ["{{llm.to}}"],
        "subject": "{{llm.subject}}",
        "text": "{{llm.body}}",
    }
    rendered = render_dict(body, {
        "user": {"from_addr": "bot@acme.com"},
        "llm": {"to": "alice@example.com", "subject": "Hi", "body": "content"},
    })
    assert rendered["from"] == "bot@acme.com"
    assert rendered["to"] == ["alice@example.com"]  # 数组内模板已替换
    assert rendered["subject"] == "Hi"


def test_render_dict_keeps_non_template_values():
    rendered = render_dict({"nested": {"list": [1, True, "{{llm.x}}"]}}, {"llm": {"x": "ok"}})
    assert rendered["nested"]["list"] == [1, True, "ok"]  # 非字符串原样保留


# ── 2. code 工具：沙箱执行（凭证 env 透传，不进 worker 进程） ──────────


SMTP_CODE = '''
import os

def run(to: str) -> str:
    host = os.environ["USER_smtp_host"]
    password = os.environ["USER_password"]
    return f"smtp={host} pwd={password} to={to}"
'''


async def test_code_tool_injects_user_env():
    """user_args 以 USER_ 前缀环境变量透传进执行环境（沙箱/子进程），
    worker 进程自身 os.environ 不被触碰。"""
    tool = await build_tool(
        {
            "name": "send-email-smtp",
            "source": "code",
            "code": SMTP_CODE,
            "llm_args_schema": {
                "type": "object",
                "properties": {"to": {"type": "string"}},
                "required": ["to"],
            },
        },
        user_args={"smtp_host": "smtp.qq.com", "password": "auth-code-123"},
    )
    assert tool is not None

    import os

    result = await tool.ainvoke({"to": "alice@example.com"})
    assert result == "smtp=smtp.qq.com pwd=auth-code-123 to=alice@example.com"
    # worker 进程环境不受污染（env 只进沙箱子进程）
    assert "USER_password" not in os.environ
    assert "USER_smtp_host" not in os.environ


async def test_code_tool_passes_command_and_env_to_sandbox(monkeypatch):
    """沙箱可用时：入口脚本以 base64 管道传入 + USER_ 凭证 env 透传 +
    LLM 参数以 JSON argv 传递。"""
    import base64

    from agent_flow_harness.sandbox.base import SandboxResult
    from app.engine.tool import tool_builder

    captured: dict = {}

    class FakeSandbox:
        id = "fake"

        def execute_command(self, command, *, timeout=None, env=None):
            captured["command"] = command
            captured["env"] = env
            return SandboxResult(stdout="ok-result\n", stderr="", exit_code=0)

    monkeypatch.setattr(tool_builder, "_get_tool_sandbox", lambda: FakeSandbox())

    tool = await build_tool(
        {
            "name": "send-email-smtp",
            "source": "code",
            "code": "def run(to: str) -> str:\n    return 'sent:' + to\n",
            "llm_args_schema": {
                "type": "object",
                "properties": {"to": {"type": "string"}},
                "required": ["to"],
            },
        },
        user_args={"password": "secret-1"},
    )
    result = await tool.ainvoke({"to": "bob@x.com"})
    assert result == "ok-result"

    # 命令：base64 管道 + JSON argv
    assert "| base64 -d | python3 - " in captured["command"]
    assert '"to": "bob@x.com"' in captured["command"]
    b64 = captured["command"].split("echo ", 1)[1].split(" |", 1)[0]
    script = base64.b64decode(b64).decode()
    assert "def run(to: str) -> str" in script  # 用户代码完整传入
    # env：USER_ 凭证透传
    assert captured["env"] == {"USER_password": "secret-1"}


async def test_code_tool_nonzero_exit_returns_error(monkeypatch):
    """沙箱内执行失败（非零退出）→ 返回 Error: 前缀（LLM 可见可重试）。"""
    from agent_flow_harness.sandbox.base import SandboxResult
    from app.engine.tool import tool_builder

    class FailingSandbox:
        id = "fail"

        def execute_command(self, command, *, timeout=None, env=None):
            return SandboxResult(
                stdout="", stderr="Traceback ... SMTPAuthenticationError", exit_code=1
            )

    monkeypatch.setattr(tool_builder, "_get_tool_sandbox", lambda: FailingSandbox())

    tool = await build_tool(
        {
            "name": "bad-tool",
            "source": "code",
            "code": "def run() -> str:\n    raise RuntimeError('boom')\n",
            "llm_args_schema": {},
        },
        user_args={},
    )
    result = await tool.ainvoke({})
    assert result.startswith("Error:")
    assert "SMTPAuthenticationError" in result


async def test_code_tool_runs_even_with_llm_sandbox_set():
    """LLM bash 沙箱（set_sandbox_context 注入，无网络）与治理工具沙箱
    相互独立——context 里挂一个「任何调用都炸」的哨兵沙箱，code 工具
    照常执行（走自己的工具沙箱）。"""
    from agent_flow_harness import (
        SandboxContext,
        reset_sandbox_context,
        set_sandbox_context,
    )

    class _RefusingSandbox:
        def __getattr__(self, attr):
            raise AssertionError(f"LLM sandbox must not be used, got {attr}")

    token = set_sandbox_context(SandboxContext(sandbox=_RefusingSandbox()))  # type: ignore[arg-type]
    try:
        tool = await build_tool(
            {
                "name": "plain-code",
                "source": "code",
                "code": "def run(x: str) -> str:\n    return 'echo:' + x\n",
                "llm_args_schema": {
                    "type": "object",
                    "properties": {"x": {"type": "string"}},
                    "required": ["x"],
                },
            },
            user_args={},
        )
        assert tool is not None
        result = await tool.ainvoke({"x": "hi"})
        assert result == "echo:hi"
    finally:
        reset_sandbox_context(token)


# ── 3. openapi 工具：Resend 风格邮件端点端到端 ────────────────────────


class _FakeResp:
    def __init__(self, json_data: dict | None):
        self._json = json_data
        self.text = "raw-text"

    def json(self) -> dict:
        return self._json or {}


async def test_openapi_email_tool_renders_request(monkeypatch):
    """完整邮件 endpoint：header 凭证 + 数组收件人 body 全部渲染，
    response_path 提取 id。"""
    captured: dict = {}

    class FakeClient:
        def __init__(self, timeout=None):
            captured["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, headers=None, params=None, json=None):
            captured.update({"url": url, "headers": headers, "json": json})
            return _FakeResp({"id": "evt-123", "message": "queued"})

    monkeypatch.setattr(httpx, "AsyncClient", lambda timeout=30.0: FakeClient())

    tool = await build_tool(
        {
            "name": "send-email",
            "description": "发送邮件",
            "source": "openapi",
            "endpoint": {
                "method": "POST",
                "url": "https://api.resend.com/emails",
                "headers": {"Authorization": "Bearer {{user.api_key}}"},
                "body": {
                    "from": "{{user.from_addr}}",
                    "to": ["{{llm.to}}"],
                    "subject": "{{llm.subject}}",
                    "text": "{{llm.body}}",
                },
                "response_path": "id",
            },
            "llm_args_schema": {
                "type": "object",
                "properties": {
                    "to": {"type": "string"},
                    "subject": {"type": "string"},
                    "body": {"type": "string"},
                },
                "required": ["to", "subject", "body"],
            },
        },
        user_args={"api_key": "re_abc123", "from_addr": "bot@acme.com"},
    )
    assert tool is not None

    result = await tool.ainvoke({
        "to": "alice@example.com", "subject": "报表", "body": "见附件",
    })

    # 请求侧：凭证 header + 数组收件人 body 均已渲染
    assert captured["url"] == "https://api.resend.com/emails"
    assert captured["headers"]["Authorization"] == "Bearer re_abc123"
    assert captured["json"]["to"] == ["alice@example.com"]
    assert captured["json"]["from"] == "bot@acme.com"
    assert captured["json"]["subject"] == "报表"
    # 响应侧：response_path 提取
    assert result == '"evt-123"'


async def test_openapi_response_path_array_index(monkeypatch):
    """response_path 支持数组下标：data.items.0.name。"""

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, headers=None, params=None):
            return _FakeResp({"data": {"items": [{"name": "first"}, {"name": "second"}]}})

    monkeypatch.setattr(httpx, "AsyncClient", lambda timeout=30.0: FakeClient())

    tool = await build_tool(
        {
            "name": "list-query",
            "description": "",
            "source": "openapi",
            "endpoint": {
                "method": "GET",
                "url": "https://api.example.com/x",
                "response_path": "data.items.0.name",
            },
            "llm_args_schema": {},
        },
        user_args={},
    )
    assert tool is not None
    result = await tool.ainvoke({})
    assert result == '"first"'


# ── 4. openapi 返回说明附加到工具描述（AI 可见） ────────────────────────


async def test_openapi_response_notes_in_description():
    """endpoint.response_notes 应拼进工具描述，帮助 AI 理解返回格式。"""
    tool = await build_tool(
        {
            "name": "weather-notes",
            "description": "查询天气",
            "source": "openapi",
            "endpoint": {
                "method": "GET",
                "url": "https://api.x.com/w",
                "response_notes": '{"temperature": 25, "unit": "celsius"}',
            },
            "llm_args_schema": {},
        },
        user_args={},
    )
    assert tool is not None
    assert tool.description.startswith("查询天气")
    assert '返回格式：{"temperature": 25, "unit": "celsius"}' in tool.description


# ── 5. 参数表模型：按位置组装请求（query/header/path/body + 凭证） ─────


async def test_openapi_params_table_assembles_request(monkeypatch):
    """参数声明一次、位置定发送：AI 填 query/path，凭证从 user_args 进 header，
    body 参数合成 JSON。"""
    captured: dict = {}

    class FakeClient:
        def __init__(self, timeout=None):
            captured["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, headers=None, params=None, json=None):
            captured.update({"url": url, "headers": headers, "params": params, "json": json})
            return _FakeResp({"ok": True})

    monkeypatch.setattr(httpx, "AsyncClient", lambda timeout=30.0: FakeClient())

    tool = await build_tool(
        {
            "name": "params-table-tool",
            "description": "参数表模型",
            "source": "openapi",
            "endpoint": {
                "method": "POST",
                "url": "https://api.x.com/cities/{city}",
                "params": [
                    {"name": "city", "in": "path", "required": True, "credential": False},
                    {"name": "unit", "in": "query", "required": False, "credential": False},
                    {"name": "Authorization", "in": "header", "credential": True},
                    {"name": "note", "in": "body", "required": False, "credential": False},
                ],
            },
            "llm_args_schema": {
                "type": "object",
                "properties": {"city": {"type": "string"}, "unit": {"type": "string"}, "note": {"type": "string"}},
                "required": ["city"],
            },
        },
        user_args={"Authorization": "Bearer sk-123"},  # 凭证（已解密）
    )
    assert tool is not None
    result = await tool.ainvoke({"city": "Beijing", "unit": "celsius", "note": "hi"})

    assert captured["url"] == "https://api.x.com/cities/Beijing"  # path 替换
    assert captured["headers"] == {"Authorization": "Bearer sk-123"}  # 凭证进 header
    assert captured["params"] == {"unit": "celsius"}  # query 分桶
    assert captured["json"] == {"note": "hi"}  # body 分桶
    assert result == "raw-text"  # 未配 response_path → 返回响应原文


async def test_openapi_params_table_signature_from_schema():
    """工具签名（AI 可填参数）来自 llm_args_schema——凭证参数不出现。"""
    from app.services.user_tool_service import UserToolService

    llm, user = UserToolService.derive_openapi_schemas({
        "method": "GET", "url": "https://x.com",
        "params": [
            {"name": "city", "in": "query", "required": True, "credential": False},
            {"name": "api_key", "in": "header", "credential": True},
        ],
    })
    assert set(llm["properties"]) == {"city"}
    assert set(user["properties"]) == {"api_key"}
    assert user["properties"]["api_key"]["sensitive"] is True
