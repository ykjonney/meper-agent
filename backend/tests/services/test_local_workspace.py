"""本地接入 workspace（workspace 重设计）单元测试。

覆盖：
- get_local_workspace 白名单校验（未启用/越权/不存在/路径非法）
- layout_for_workspace 双模式分发（cloud→CloudLayout / local→LocalLayout）
- describe() 经 layout_for_workspace 输出模式正确的环境段
- 环境段注入（slot_renderer 的 environment 参数 → ## Environment 段落）
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from app.core.config import settings
from app.engine.tool.workspace import WorkspaceManager, layout_for_workspace

# ── get_local_workspace 白名单校验 ───────────────────────────────────


def test_local_workspace_disabled_by_default(tmp_path, monkeypatch):
    """LOCAL_WORKSPACE_ROOT 为空 → 本地模式禁用（默认安全）。"""
    monkeypatch.setattr(settings, "LOCAL_WORKSPACE_ROOT", "")
    with pytest.raises(ValueError, match="disabled"):
        WorkspaceManager.get_local_workspace("proj")


def test_local_workspace_within_allowlist(tmp_path, monkeypatch):
    root = tmp_path / "repos"
    proj = root / "proj"
    proj.mkdir(parents=True)
    monkeypatch.setattr(settings, "LOCAL_WORKSPACE_ROOT", str(root))
    ws = WorkspaceManager.get_local_workspace("proj")
    assert ws.is_local is True
    assert ws.local_dir == "proj"
    assert ws.root == proj.resolve()
    assert ws.tmp_dir == proj.resolve()  # local 模式三字段占位同指 root


def test_local_workspace_rejects_escape(tmp_path, monkeypatch):
    root = tmp_path / "repos"
    root.mkdir(parents=True)
    (root / "outside").mkdir(parents=True)
    monkeypatch.setattr(settings, "LOCAL_WORKSPACE_ROOT", str(root))
    with pytest.raises(ValueError, match="invalid"):
        WorkspaceManager.get_local_workspace("../outside")
    # 绝对路径 / 家目录展开显式拒绝（只接受白名单内相对路径）
    with pytest.raises(ValueError, match="must be relative"):
        WorkspaceManager.get_local_workspace("/etc")
    with pytest.raises(ValueError, match="must be relative"):
        WorkspaceManager.get_local_workspace("~/x")
    with pytest.raises(ValueError, match="invalid"):
        WorkspaceManager.get_local_workspace("..")


def test_local_workspace_rejects_missing_dir(tmp_path, monkeypatch):
    root = tmp_path / "repos"
    root.mkdir(parents=True)
    monkeypatch.setattr(settings, "LOCAL_WORKSPACE_ROOT", str(root))
    with pytest.raises(ValueError, match="does not exist"):
        WorkspaceManager.get_local_workspace("ghost")


# ── layout_for_workspace 双模式分发 ──────────────────────────────────


def test_layout_for_cloud_workspace(tmp_path):
    del tmp_path  # get_workspace 走全局 workspaces root（纯路径计算，无 I/O）
    ws = WorkspaceManager.get_workspace("u1", "s1")
    assert ws.is_local is False
    layout = layout_for_workspace(ws)
    assert layout.mode == "cloud"
    text = layout.describe()
    assert "tmp/" in text and "output/" in text


def test_layout_for_local_workspace(tmp_path, monkeypatch):
    root = tmp_path / "repos"
    proj = root / "proj"
    proj.mkdir(parents=True)
    monkeypatch.setattr(settings, "LOCAL_WORKSPACE_ROOT", str(root))
    ws = WorkspaceManager.get_local_workspace("proj")
    layout = layout_for_workspace(ws)
    assert layout.mode == "local"
    text = layout.describe()
    assert str(proj.resolve()) in text


# ── 环境段注入（render_system_prompt_full 的 environment 参数）────────


@pytest.mark.asyncio
async def test_render_prompt_inserts_environment_before_tool_declaration():
    """environment 段必须出现在 ## Environment 标题下、工具声明之前。"""
    from unittest.mock import AsyncMock, patch

    from app.engine.agent.slot_renderer import render_system_prompt_full

    agent = {"system_prompt": "你是助手。"}
    with patch(
        "app.engine.agent.builder.build_tool_declaration",
        new=AsyncMock(return_value="## Built-in Tools\n- read"),
    ):
        text = await render_system_prompt_full(
            agent,
            environment="Working directory: /tmp/repo",
        )

    assert "## Environment" in text
    assert "Working directory: /tmp/repo" in text
    env_pos = text.index("## Environment")
    decl_pos = text.index("## Built-in Tools")
    assert env_pos < decl_pos  # 环境段在工具声明之前


@pytest.mark.asyncio
async def test_render_prompt_without_environment_has_no_section():
    """environment=None → 无 Environment 段（向后兼容）。"""
    from app.engine.agent.slot_renderer import render_system_prompt_full

    agent = {"system_prompt": "你是助手。"}
    with patch(
        "app.engine.agent.builder.build_tool_declaration",
        return_value="## Built-in Tools\n- read",
    ):
        text = await render_system_prompt_full(agent)
    assert "## Environment" not in text


# ── 后台任务 turn 边界注入（collect_background_task_notices）──────────


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """云端 session workspace（隔离到 tmp_path，防跨测试污染）。"""
    from app.core.config import settings
    from app.engine.tool.workspace import WorkspaceManager

    monkeypatch.setattr(settings, "WORKSPACES_CONTAINER_DIR", str(tmp_path))
    ws = WorkspaceManager.get_workspace("user_1", "sess_1")
    for d in (ws.input_dir, ws.output_dir, ws.tmp_dir):
        d.mkdir(parents=True, exist_ok=True)
    return ws



def _seed_bg_task(ws, tid: str, *, exit_code: str | None = None, read: bool = False,
                  started: float | None = None, cmd: str = "npm run build\n") -> None:
    import time as _time

    bg = ws.tmp_dir / ".af_bg"
    bg.mkdir(parents=True, exist_ok=True)
    (bg / f"{tid}.pid").write_text("12345")
    (bg / f"{tid}.start").write_text(str(started or _time.time()))
    (bg / f"{tid}.cmd").write_text(cmd, encoding="utf-8")
    if exit_code is not None:
        (bg / f"{tid}.exit").write_text(exit_code)
    if read:
        (bg / f"{tid}.read").write_text("1")


def test_bg_notices_empty_when_no_tasks(workspace):
    from app.engine.tool.workspace import collect_background_task_notices

    assert collect_background_task_notices(workspace) == ""


def test_bg_notices_finished_unread(workspace):
    from app.engine.tool.workspace import collect_background_task_notices

    _seed_bg_task(workspace, "bg-aa1111", exit_code="0")
    text = collect_background_task_notices(workspace)
    assert "[后台任务]" in text
    assert "已结束（exit 0，未读）" in text
    assert "bash_output(command_id='bg-aa1111')" in text
    assert "npm run build" in text


def test_bg_notices_finished_read_skipped(workspace):
    from app.engine.tool.workspace import collect_background_task_notices

    _seed_bg_task(workspace, "bg-bb2222", exit_code="0", read=True)
    assert collect_background_task_notices(workspace) == ""


def test_bg_notices_running(workspace):
    from app.engine.tool.workspace import collect_background_task_notices

    _seed_bg_task(workspace, "bg-cc3333")
    text = collect_background_task_notices(workspace)
    assert "进行中" in text
    assert "block=true" in text


def test_bg_notices_running_and_finished_sorted(workspace):
    from app.engine.tool.workspace import collect_background_task_notices

    _seed_bg_task(workspace, "bg-dd4444", exit_code="1")
    _seed_bg_task(workspace, "bg-ee5555")
    text = collect_background_task_notices(workspace)
    assert text.index("bg-ee5555") < text.index("bg-dd4444")  # 最新启动优先
    assert "exit 1" in text
