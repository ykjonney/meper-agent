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
    """Mock app.db.mongodb.get_database → tools.find_one 返回 tool_doc。

    record_load（调用计数）单独 mock：ToolService 顶层 from-import 持有
    get_database 本地引用，模块属性 mock 拦不住，CI 无 Mongo 会真连。
    """
    find_one = AsyncMock(return_value=tool_doc)
    update_one = AsyncMock()
    db = {"tools": type(
        "Coll", (), {"find_one": staticmethod(find_one), "update_one": staticmethod(update_one)},
    )()}
    monkeypatch.setattr("app.db.mongodb.get_database", lambda: db)
    monkeypatch.setattr(
        "app.services.user_tool_service.UserToolService.record_load", AsyncMock()
    )
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


# ── code 工具文件通道：workspace 注入 + 产物注册进 files ──────────────


class _FileWritingTool(_FakeTool):
    """模拟 code 工具在沙箱内写产物——从 workspace contextvar 拿到
    output/ 目录落一个文件（真实链路：DockerSandbox bind mount 落宿主）。"""

    def __init__(self, filename: str, content: str):
        super().__init__(result="done")
        self.filename = filename
        self.content = content

    async def ainvoke(self, params):
        from app.engine.agent.builtin_tools import _get_workspace

        ws = _get_workspace()
        assert ws is not None, "workspace contextvar 必须在 ainvoke 期间可用"
        ws.output_dir.mkdir(parents=True, exist_ok=True)
        (ws.output_dir / self.filename).write_text(self.content)
        return self.result


def _patch_file_service(monkeypatch, registered: list) -> None:
    """Mock FileService：已注册 sha 查询为空 + create 返回 fake FileRef。"""
    from app.services.file_service import FileService

    class _Cursor:
        async def to_list(self, length=None):
            return []

    coll = type("Coll", (), {"find": staticmethod(lambda q, p=None: _Cursor())})()
    monkeypatch.setattr(FileService, "_file_refs", lambda self: coll)

    async def fake_create(self, data, filename, mime_type, owner_user_id, origin_kind, origin_id):
        fref = type(
            "F",
            (),
            {
                "id": f"file_{filename}", "name": filename, "size": len(data),
                "mime_type": mime_type, "storage_key": f"{owner_user_id}/files/f",
            },
        )()
        registered.append(fref)
        return fref

    monkeypatch.setattr(FileService, "create", fake_create)


async def test_code_tool_registers_output_files(monkeypatch, tmp_path):
    """code 工具 + 任务上下文：workspace 注入 → 产物写 output/ → 注册
    file_library → 输出契约扩为 {result, tool_id, files}。"""
    monkeypatch.setattr(
        "app.engine.tool.workspace.settings.WORKSPACES_CONTAINER_DIR", str(tmp_path)
    )
    doc = {"_id": "tool_f1", "name": "gen-report", "source": "code", "code": "def run(): pass"}
    _patch_db(monkeypatch, doc)
    monkeypatch.setattr(
        "app.engine.tool.tool_builder.build_tool",
        AsyncMock(return_value=_FileWritingTool("report.xlsx", "fake-xlsx")),
    )
    registered: list = []
    _patch_file_service(monkeypatch, registered)

    variables = {"system": {"user_id": "user_9", "task_id": "task_9"}}
    result = await _make({"tool_id": "tool_f1", "params": {}}).execute(variables)

    assert result.success
    out = result.output
    assert out["result"] == "done"
    assert out["tool_id"] == "tool_f1"
    assert len(out["files"]) == 1
    assert out["files"][0]["file_id"] == "file_report.xlsx"
    assert out["files"][0]["name"] == "report.xlsx"
    assert len(registered) == 1

    # 工作区真实落盘（沙箱 bind mount 语义）
    assert (tmp_path / "user_9" / "tasks" / "task_9" / "output" / "report.xlsx").exists()

    # contextvar 已在节点结束时 reset（不污染后续节点）
    from app.engine.agent.builtin_tools import _get_workspace
    assert _get_workspace() is None


async def test_code_tool_old_output_files_not_registered(monkeypatch, tmp_path):
    """mtime 早于节点开始的旧产物不重复注册（同任务重跑场景）。"""
    import os
    import time as _time

    monkeypatch.setattr(
        "app.engine.tool.workspace.settings.WORKSPACES_CONTAINER_DIR", str(tmp_path)
    )
    old_dir = tmp_path / "user_8" / "tasks" / "task_8" / "output"
    old_dir.mkdir(parents=True)
    old_file = old_dir / "old.txt"
    old_file.write_text("old")
    past = _time.time() - 3600
    os.utime(old_file, (past, past))

    doc = {"_id": "tool_f2", "name": "gen", "source": "code", "code": "def run(): pass"}
    _patch_db(monkeypatch, doc)
    monkeypatch.setattr(
        "app.engine.tool.tool_builder.build_tool",
        AsyncMock(return_value=_FileWritingTool("new.txt", "new")),
    )
    registered: list = []
    _patch_file_service(monkeypatch, registered)

    result = await _make({"tool_id": "tool_f2", "params": {}}).execute(
        {"system": {"user_id": "user_8", "task_id": "task_8"}}
    )

    assert result.success
    assert [f.name for f in registered] == ["new.txt"]  # 只注册新文件
    assert len(result.output["files"]) == 1


async def test_code_tool_without_task_context_no_files(monkeypatch):
    """无 system.task_id/user_id（工具预览等）：不建 workspace、输出契约
    保持 {result, tool_id}（不带空 files 字段）。"""
    doc = {"_id": "tool_f3", "name": "plain", "source": "code", "code": "def run(): pass"}
    _patch_db(monkeypatch, doc)
    monkeypatch.setattr(
        "app.engine.tool.tool_builder.build_tool",
        AsyncMock(return_value=_FakeTool(result="42")),
    )
    result = await _make({"tool_id": "tool_f3", "params": {}}).execute({})

    assert result.success
    assert result.output == {"result": "42", "tool_id": "tool_f3"}
    assert "files" not in result.output


# ── code 工具错误文本判定：直调路径失败变红（agent 路径不受影响） ────


async def test_code_tool_error_result_fails_node(monkeypatch):
    """code 工具返回 "Error: ..." 文本（沙箱执行失败，如用户代码异常）→
    直调节点必须失败（红色），不能绿色完成。"""
    doc = {"_id": "tool_e1", "name": "bad", "source": "code", "code": "def run(): pass"}
    _patch_db(monkeypatch, doc)
    fake = _FakeTool(
        result="Error: Traceback (most recent call last):\n"
        "AttributeError: 'dict' object has no attribute 'strip'"
    )
    monkeypatch.setattr("app.engine.tool.tool_builder.build_tool", AsyncMock(return_value=fake))

    result = await _make({"tool_id": "tool_e1"}).execute({})

    assert not result.success
    assert "执行失败" in result.error_message
    assert "AttributeError" in result.error_message


async def test_code_tool_error_result_retries(monkeypatch):
    """Error 文本走重试循环：max_retries=1 → 共调用 2 次后失败。"""
    doc = {"_id": "tool_e2", "name": "flaky", "source": "code", "code": "def run(): pass"}
    _patch_db(monkeypatch, doc)
    fake = _FakeTool(result="Error: transient sandbox failure")
    monkeypatch.setattr("app.engine.tool.tool_builder.build_tool", AsyncMock(return_value=fake))

    result = await _make(
        {"tool_id": "tool_e2", "retry_policy": {"max_retries": 1, "backoff_ms": 1}}
    ).execute({})

    assert not result.success
    assert fake.calls == 2  # 初次 + 1 次重试


async def test_openapi_error_like_result_still_success(monkeypatch):
    """openapi 工具返回恰好以 Error: 开头的响应原文不误伤——错误文本
    判定仅对 code 源启用（openapi 的 Error: 可能是接口正常返回文本）。"""
    doc = {"_id": "tool_e3", "name": "api", "source": "openapi", "endpoint": {"url": "https://x"}}
    _patch_db(monkeypatch, doc)
    fake = _FakeTool(result="Error: invalid input（接口原文）")
    monkeypatch.setattr("app.engine.tool.tool_builder.build_tool", AsyncMock(return_value=fake))

    result = await _make({"tool_id": "tool_e3"}).execute({})

    assert result.success
    assert result.output["result"].startswith("Error:")

