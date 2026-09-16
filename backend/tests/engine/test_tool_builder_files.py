"""ToolBuilder code 工具文件通道用例——读写闭环。

覆盖（TOOL_SANDBOX_MOUNT_WORKSPACE 开启 + 工作区 contextvar 场景）：
1. 工作区挂载：本地降级执行时相对路径 input/ 读、output/ 写（chdir 探测）
2. file_id 参数解析：命中 file_library → 暂存 input/_staged/ 并替换为路径；
   非本人文件 / 查无此文件 → 原样传递
3. 产物报告：output/ 新增文件以 [output_files] 清单附加到结果文本
4. 开关关闭 / 无工作区：退回无挂载单例沙箱，描述不带文件约定说明

FileService 访问全部 mock（conftest 规则：不连真实 Mongo）。
"""
from __future__ import annotations

from pathlib import Path

from app.engine.agent.builtin_tools import (
    reset_workspace_context,
    set_workspace_context,
)
from app.engine.tool.tool_builder import build_tool
from app.engine.tool.workspace import Workspace


def _make_workspace(root: Path) -> Workspace:
    """直接构造 Workspace（绕过 settings.WORKSPACES_CONTAINER_DIR）。"""
    return Workspace(
        root=root,
        input_dir=root / "input",
        output_dir=root / "output",
        tmp_dir=root / "tmp",
        scope="task",
    )


async def _build_code_tool(code: str, name: str = "file-tool", llm_schema: dict | None = None):
    return await build_tool(
        {
            "name": name,
            "description": "测试工具",
            "source": "code",
            "code": code,
            "llm_args_schema": llm_schema
            or {
                "type": "object",
                "properties": {"x": {"type": "string"}},
                "required": ["x"],
            },
        },
        user_args={},
    )


# ── 1. 工作区读写：本地降级下相对路径闭环 ──────────────────────────────


async def test_workspace_relative_read_write(tmp_path, monkeypatch):
    """有工作区时：input/ 相对路径可读、output/ 相对路径可写（chdir 到
    工作区根），产物文件真实落盘宿主 output/ 目录。"""
    ws = _make_workspace(tmp_path)
    ws.input_dir.mkdir(parents=True)
    (ws.input_dir / "note.txt").write_text("hello-input")

    tool = await _build_code_tool(
        "def run(x: str) -> str:\n"
        "    data = open('input/note.txt').read()\n"
        "    with open('output/result.txt', 'w') as f:\n"
        "        f.write(data + ':' + x)\n"
        "    return 'written'\n"
    )
    token = set_workspace_context(ws)
    try:
        result = await tool.ainvoke({"x": "hi"})
    finally:
        reset_workspace_context(token)

    assert result.startswith("written")
    assert (ws.output_dir / "result.txt").read_text() == "hello-input:hi"
    # 产物清单附加在结果尾部
    assert "[output_files]" in result
    assert "output/result.txt" in result


# ── 2. file_id 参数解析与暂存 ──────────────────────────────────────────


class _FakeFileRef:
    def __init__(self, file_id: str, name: str, owner: str, data: bytes):
        self.id = file_id
        self.name = name
        self.owner_user_id = owner
        self.size = len(data)
        self.storage_key = f"{owner}/files/{file_id}"


def _patch_file_service(monkeypatch, files: dict[str, tuple[_FakeFileRef, bytes]]):
    """Mock FileService.get / load_content——返回预置文件（或 None）。"""
    from app.services.file_service import FileService

    async def fake_get(self, file_id):
        entry = files.get(file_id)
        return entry[0] if entry else None

    async def fake_load_content(self, file_id):
        return files.get(file_id)

    monkeypatch.setattr(FileService, "get", fake_get)
    monkeypatch.setattr(FileService, "load_content", fake_load_content)


async def test_file_id_arg_staged_to_input(tmp_path, monkeypatch):
    """LLM 传 file_id → 参数值替换为 input/_staged/ 路径，用户代码直接
    open() 读到内容（本地降级执行全链路验证）。"""
    ws = _make_workspace(tmp_path)
    for d in (ws.input_dir, ws.output_dir, ws.tmp_dir):
        d.mkdir(parents=True)

    fref = _FakeFileRef("file_abc123", "周报.xlsx", ws.user_id, b"xlsx-bytes")
    _patch_file_service(monkeypatch, {"file_abc123": (fref, b"xlsx-bytes")})

    tool = await _build_code_tool(
        "def run(attachment: str) -> str:\n"
        "    with open(attachment, 'rb') as f:\n"
        "        return 'size=' + str(len(f.read()))\n",
        llm_schema={
            "type": "object",
            "properties": {"attachment": {"type": "string"}},
            "required": ["attachment"],
        },
    )
    token = set_workspace_context(ws)
    try:
        result = await tool.ainvoke({"attachment": "file_abc123"})
    finally:
        reset_workspace_context(token)

    assert result.startswith("size=10")  # 用户代码读到了暂存文件内容
    staged = ws.input_dir / "_staged" / "file_abc123" / "周报.xlsx"
    assert staged.read_bytes() == b"xlsx-bytes"


async def test_file_id_in_list_args_staged(tmp_path, monkeypatch):
    """list 参数内的 file_id 同样解析（如多附件场景）。"""
    ws = _make_workspace(tmp_path)
    for d in (ws.input_dir, ws.output_dir, ws.tmp_dir):
        d.mkdir(parents=True)

    fref = _FakeFileRef("file_l1", "a.pdf", ws.user_id, b"pdf-data")
    _patch_file_service(monkeypatch, {"file_l1": (fref, b"pdf-data")})

    # 用真实执行读回替换后的路径
    tool = await _build_code_tool(
        "def run(attachments: list) -> str:\n"
        "    import os\n"
        "    return ','.join(str(os.path.exists(p)) for p in attachments)\n",
        llm_schema={
            "type": "object",
            "properties": {"attachments": {"type": "array", "items": {"type": "string"}}},
        },
    )
    token = set_workspace_context(ws)
    try:
        result = await tool.ainvoke({"attachments": ["file_l1", "input/plain.txt"]})
    finally:
        reset_workspace_context(token)

    assert result == "True,False"  # file_l1 已暂存可读；不存在的路径保持原样


async def test_file_id_owner_mismatch_not_resolved(tmp_path, monkeypatch):
    """非本人文件：参数原样传递（防越权读他人 file_library）。"""
    ws = _make_workspace(tmp_path)
    for d in (ws.input_dir, ws.output_dir, ws.tmp_dir):
        d.mkdir(parents=True)

    fref = _FakeFileRef("file_other", "secret.txt", "user_2", b"other-user-data")
    _patch_file_service(monkeypatch, {"file_other": (fref, b"other-user-data")})

    tool = await _build_code_tool(
        "def run(x: str) -> str:\n    return x\n",
    )
    token = set_workspace_context(ws)
    try:
        result = await tool.ainvoke({"x": "file_other"})
    finally:
        reset_workspace_context(token)

    assert result == "file_other"  # 未被替换
    assert not (ws.input_dir / "_staged" / "file_other").exists()


async def test_staging_is_idempotent(tmp_path, monkeypatch):
    """同一 file_id 重复调用复用暂存文件，不重复写入。"""
    from app.engine.tool.tool_builder import _stage_library_file

    ws = _make_workspace(tmp_path)
    fref = _FakeFileRef("file_dup", "a.txt", "user_1", b"same-data")
    _stage_library_file(fref, b"same-data", ws)
    first_mtime = (ws.input_dir / "_staged" / "file_dup" / "a.txt").stat().st_mtime

    path_again = _stage_library_file(fref, b"same-data", ws)
    assert path_again == "input/_staged/file_dup/a.txt"
    assert (ws.input_dir / "_staged" / "file_dup" / "a.txt").stat().st_mtime == first_mtime


# ── 3. 产物报告边界 ────────────────────────────────────────────────────


async def test_no_output_files_no_report(tmp_path):
    """未产出文件时结果文本保持纯净（不附加空清单）。"""
    ws = _make_workspace(tmp_path)
    for d in (ws.input_dir, ws.output_dir, ws.tmp_dir):
        d.mkdir(parents=True)
    # 预置旧文件（mtime 早于本次执行）——不应出现在报告里
    (ws.output_dir / "old.txt").write_text("old")

    tool = await _build_code_tool("def run(x: str) -> str:\n    return 'plain:' + x\n")
    token = set_workspace_context(ws)
    try:
        result = await tool.ainvoke({"x": "v"})
    finally:
        reset_workspace_context(token)

    assert result == "plain:v"  # 无 [output_files] 段


async def test_output_report_only_lists_new_files(tmp_path):
    """报告只列本次新增文件，旧文件不重复列出。"""
    ws = _make_workspace(tmp_path)
    for d in (ws.input_dir, ws.output_dir, ws.tmp_dir):
        d.mkdir(parents=True)
    (ws.output_dir / "old.txt").write_text("old")

    tool = await _build_code_tool(
        "def run(x: str) -> str:\n"
        "    open('output/new.txt', 'w').write(x)\n"
        "    return 'ok'\n"
    )
    token = set_workspace_context(ws)
    try:
        result = await tool.ainvoke({"x": "new-content"})
    finally:
        reset_workspace_context(token)

    assert "[output_files]" in result
    assert "output/new.txt" in result
    assert "old.txt" not in result


# ── 4. 开关与降级 ──────────────────────────────────────────────────────


async def test_switch_off_reverts_to_no_workspace(monkeypatch):
    """TOOL_SANDBOX_MOUNT_WORKSPACE=False：即使有工作区也不挂载、不解析
    file_id，描述不带文件约定说明（治理 kill-switch 回到现状）。"""
    from app.core.config import settings
    from app.engine.tool import tool_builder

    monkeypatch.setattr(settings, "TOOL_SANDBOX_MOUNT_WORKSPACE", False)
    # 无挂载单例沙箱若真连 docker 会失败——CI 里 enabled=False + local
    # fallback 走本机 subprocess，可真实执行；替换为桩更稳：
    from agent_flow_harness.sandbox.base import SandboxResult

    class _StubSandbox:
        def execute_command(self, command, *, timeout=None, env=None):
            return SandboxResult(stdout="stub-ok\n", stderr="", exit_code=0)

    monkeypatch.setattr(tool_builder, "_get_tool_sandbox", lambda: _StubSandbox())

    tool = await _build_code_tool("def run(x: str) -> str:\n    return 'unused'\n")
    assert "文件支持" not in tool.description  # 开关关闭 → 描述不带文件说明

    ws = _make_workspace(Path("/nonexistent-ws"))
    token = set_workspace_context(ws)
    try:
        result = await tool.ainvoke({"x": "q"})
    finally:
        reset_workspace_context(token)
    assert result == "stub-ok"  # 走无挂载单例（未被工作区路径影响）


async def test_description_includes_file_convention_by_default():
    """默认开关开启：code 工具描述附加文件约定（LLM 引导）。"""
    tool = await _build_code_tool("def run(x: str) -> str:\n    return x\n")
    assert "文件支持" in tool.description
    assert "file_id" in tool.description


# ── 5. bind mount 源换算（容器化部署 volumes 错位修复） ────────────────


def test_workspace_sandbox_carries_bind_source_mapper(monkeypatch, tmp_path):
    """CONTAINER ≠ HOST 时：code 工具沙箱 config 携带 mapper 且换算正确——
    backend 容器内路径经 mapper 变成 daemon 可见的宿主路径。"""
    from app.core.config import settings
    from app.engine.tool.tool_builder import _get_workspace_tool_sandbox

    container = tmp_path / "data" / "workspaces"
    host = tmp_path / "opt" / "agent-flow" / "ws"
    monkeypatch.setattr(settings, "WORKSPACES_CONTAINER_DIR", str(container))
    monkeypatch.setattr(settings, "WORKSPACES_HOST_DIR", str(host))

    ws = _make_workspace(container / "usr_A" / "tasks" / "task_9")
    sb = _get_workspace_tool_sandbox(ws)

    mapper = sb._config.bind_source_mapper
    assert mapper is not None
    assert mapper(str(ws.input_dir)) == str(host / "usr_A" / "tasks" / "task_9" / "input")
    # 无 mapper 时不换算（本地开发兼容）
    monkeypatch.setattr(settings, "WORKSPACES_CONTAINER_DIR", str(host))
    sb2 = _get_workspace_tool_sandbox(_make_workspace(host / "usr_A"))
    assert sb2._config.bind_source_mapper is None


async def test_dict_file_reference_normalized(tmp_path, monkeypatch):
    """工作流 {{node.files}} 整体渲染出的 dict 列表 → 取 file_id 归一化解析。
    （模板引擎的 files 契约是对象数组，参数层负责归一为工具声明的字符串。）"""
    ws = _make_workspace(tmp_path)
    for d in (ws.input_dir, ws.output_dir, ws.tmp_dir):
        d.mkdir(parents=True)

    fref = _FakeFileRef("file_d1", "报表.xlsx", ws.user_id, b"xlsx-data")
    _patch_file_service(monkeypatch, {"file_d1": (fref, b"xlsx-data")})

    tool = await _build_code_tool(
        "def run(attachments: list) -> str:\n"
        "    import os\n"
        "    return ','.join(str(os.path.exists(p)) if isinstance(p, str) else 'dict'\n"
        "                    for p in attachments)\n",
        llm_schema={
            "type": "object",
            "properties": {"attachments": {"type": "array", "items": {"type": "string"}}},
        },
    )
    token = set_workspace_context(ws)
    try:
        result = await tool.ainvoke({
            "attachments": [
                {"file_id": "file_d1", "name": "报表.xlsx", "size": 9},  # 结构化引用
                {"url": "https://x"},  # 无 file_id 的 dict 原样保留
            ]
        })
    finally:
        reset_workspace_context(token)

    assert result == "True,dict"  # dict 已归一化为暂存路径（可 open）；无关 dict 原样
