"""WorkspaceLayout 策略矩阵 — CloudLayout/LocalLayout 双后端单元测试。

覆盖：
- 路径解析（前缀映射、裸路径默认、output 回退、容器前缀剥离、越权拒绝）
- A1 写策略硬闸（write 指向 tmp//input/ 显式拒绝）
- resolve_edit 的 input 只读拒绝（历史文案逐字保留）
- describe() 环境段内容契约（目录地图/坐标系/写策略）
- LocalLayout 单 root 全权 + 树外拒绝
"""
from __future__ import annotations

import pytest

from agent_flow_harness.workspace.cloud import CloudLayout
from agent_flow_harness.workspace.local import LocalLayout


# ── CloudLayout（workspace 模式，app 场景）────────────────────────────


def _make_cloud(tmp_path, **kwargs) -> CloudLayout:
    root = tmp_path / "ws"
    tmp = root / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    return CloudLayout(
        tmp, root / "output", root / "input",
        container_workspace_dir="/workspace", **kwargs,
    )


def test_cloud_resolve_read_prefix_mapping(tmp_path):
    layout = _make_cloud(tmp_path)
    assert layout.resolve_read("tmp/a.py").host == (tmp_path / "ws" / "tmp" / "a.py").resolve()
    assert layout.resolve_read("output/a.md").host == (tmp_path / "ws" / "output" / "a.md").resolve()
    assert layout.resolve_read("input/spec.md").host == (tmp_path / "ws" / "input" / "spec.md").resolve()
    # 裸相对路径默认 tmp
    assert layout.resolve_read("a.py").host == (tmp_path / "ws" / "tmp" / "a.py").resolve()
    # 容器风格绝对路径剥前缀
    assert layout.resolve_read("/workspace/tmp/a.py").host == (tmp_path / "ws" / "tmp" / "a.py").resolve()
    assert layout.resolve_read("/workspace/input/spec.md").host == (tmp_path / "ws" / "input" / "spec.md").resolve()


def test_cloud_resolve_read_output_fallback(tmp_path):
    """裸相对路径 tmp 不存在时回退查 output/（write 产物裸名可读）。"""
    layout = _make_cloud(tmp_path)
    out = tmp_path / "ws" / "output"
    out.mkdir(parents=True)
    (out / "report.md").write_text("x")
    resolved = layout.resolve_read("report.md")
    assert resolved.host == (out / "report.md").resolve()
    assert resolved.role == "output"
    # 带前缀不回退
    assert layout.resolve_read("tmp/report.md").host == (tmp_path / "ws" / "tmp" / "report.md").resolve()


def test_cloud_resolve_read_outside_blocked(tmp_path):
    layout = _make_cloud(tmp_path)
    with pytest.raises(PermissionError, match="outside sandbox work_dir"):
        layout.resolve_read("../../secret.txt")


def test_cloud_resolve_roles_and_writability(tmp_path):
    layout = _make_cloud(tmp_path)
    assert layout.resolve_read("tmp/x").role == "tmp"
    assert layout.resolve_read("input/x").role == "input"
    assert layout.resolve_read("input/x").writable is False
    assert layout.resolve_read("tmp/x").writable is True


def test_cloud_resolve_edit_input_rejected(tmp_path):
    """input 只读拒绝，文案与历史 _reject_input_write 逐字一致。"""
    layout = _make_cloud(tmp_path)
    with pytest.raises(PermissionError, match="read-only input; copy it into the workspace to modify"):
        layout.resolve_edit("input/spec.md")


def test_cloud_resolve_edit_tmp_allowed(tmp_path):
    layout = _make_cloud(tmp_path)
    assert layout.resolve_edit("tmp/x.py").writable is True


# ── A1 写策略硬闸 ────────────────────────────────────────────────────


def test_cloud_write_rejects_tmp(tmp_path):
    """A1: write("tmp/x") 显式拒绝（原行为：静默错路由到 output/tmp/x）。"""
    layout = _make_cloud(tmp_path)
    with pytest.raises(PermissionError, match="use edit to modify existing files"):
        layout.resolve_write("tmp/report.md")


def test_cloud_write_rejects_input(tmp_path):
    layout = _make_cloud(tmp_path)
    with pytest.raises(PermissionError, match="read-only input|use edit"):
        layout.resolve_write("input/attachment.pdf")


def test_cloud_write_rejects_container_tmp_prefix(tmp_path):
    layout = _make_cloud(tmp_path)
    with pytest.raises(PermissionError, match="use edit"):
        layout.resolve_write("/workspace/tmp/report.md")


def test_cloud_write_maps_to_output(tmp_path):
    layout = _make_cloud(tmp_path)
    # 裸相对路径 → output 树内
    assert layout.resolve_write("report.md").host == (tmp_path / "ws" / "output" / "report.md").resolve()
    # 相对路径不剥 output/ 前缀（legacy 行为：output_dir/output/sub/a.md）
    assert layout.resolve_write("output/sub/a.md").host == (
        tmp_path / "ws" / "output" / "output" / "sub" / "a.md"
    ).resolve()
    # 容器绝对路径剥前缀
    assert layout.resolve_write("/workspace/output/a.md").host == (tmp_path / "ws" / "output" / "a.md").resolve()
    # 非 workspace 模式无 tmp/input 角色，不设闸（旧行为：全映射 output）
    flat = CloudLayout(tmp_path / "flat", tmp_path / "flat_out", workspace_mode=False)
    assert flat.resolve_write("tmp/x.md").host == (tmp_path / "flat_out" / "tmp" / "x.md").resolve()


# ── describe() 环境段契约 ────────────────────────────────────────────


def test_cloud_describe_covers_contract(tmp_path):
    """环境段必须包含：三目录地图、bash cwd、双坐标系对应、写策略。"""
    text = _make_cloud(tmp_path).describe()
    assert "tmp/" in text and "input/" in text and "output/" in text
    assert "/workspace/tmp" in text  # bash cwd
    assert "/workspace/tmp/report.md" in text  # 双坐标系示例
    assert "READ-ONLY" in text
    assert "edit" in text and "read" in text  # 写策略：先读再改


def test_cloud_bash_cwd(tmp_path):
    assert _make_cloud(tmp_path).bash_cwd() == "/workspace/tmp"


# ── LocalLayout ──────────────────────────────────────────────────────


def test_local_layout_full_access_within_root(tmp_path):
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    layout = LocalLayout(root)
    assert layout.resolve_read("src/a.py").host == (root / "src" / "a.py").resolve()
    assert layout.resolve_write("notes.md").host == (root / "notes.md").resolve()
    assert layout.resolve_edit("src/a.py").writable is True
    # 绝对路径在树内也允许
    assert layout.resolve_read(str(root / "src" / "a.py")).host == (root / "src" / "a.py").resolve()


def test_local_layout_outside_blocked(tmp_path):
    layout = LocalLayout(tmp_path / "repo")
    with pytest.raises(PermissionError, match="outside local workspace root"):
        layout.resolve_read("../secret.txt")
    with pytest.raises(PermissionError, match="outside local workspace root"):
        layout.resolve_write("/etc/hosts")


def test_local_layout_describe_and_cwd(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    layout = LocalLayout(root)
    text = layout.describe()
    assert str(root.resolve()) in text
    assert layout.bash_cwd() == str(root.resolve())


def test_snapshot_reserved_stub(tmp_path):
    with pytest.raises(NotImplementedError):
        _make_cloud(tmp_path).snapshot()
