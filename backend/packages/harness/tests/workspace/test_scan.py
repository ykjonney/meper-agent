"""iter_workspace_files — gitignore 感知遍历单元测试。"""
from __future__ import annotations

from pathlib import Path

from agent_flow_harness.workspace.scan import iter_workspace_files


def test_skip_noise_dirs(tmp_path):
    """硬跳过 .git/node_modules/.venv/__pycache__ 等（无视 gitignore）。"""
    for d in (".git", "node_modules", ".venv", "__pycache__", "dist"):
        (tmp_path / d).mkdir()
        (tmp_path / d / "noise.py").write_text("x")
    (tmp_path / "app.py").write_text("real")
    found = {p.name for p in iter_workspace_files(tmp_path)}
    assert found == {"app.py"}


def test_respect_root_gitignore(tmp_path):
    """根 .gitignore 规则生效。"""
    (tmp_path / ".gitignore").write_text("*.log\nbuild/\n")
    (tmp_path / "debug.log").write_text("x")
    (tmp_path / "app.py").write_text("real")
    found = {p.name for p in iter_workspace_files(tmp_path)}
    assert found == {"app.py", ".gitignore"}


def test_respect_nested_gitignore(tmp_path):
    """子目录 .gitignore 按其所在目录解析相对规则。"""
    sub = tmp_path / "pkg"
    sub.mkdir()
    (sub / ".gitignore").write_text("generated.py\n")
    (sub / "generated.py").write_text("x")
    (sub / "real.py").write_text("y")
    found = {p.name for p in iter_workspace_files(tmp_path)}
    assert "generated.py" not in found
    assert "real.py" in found


def test_nested_gitignore_inside_skipped_dir_ignored(tmp_path):
    """被跳过目录（node_modules）内的 .gitignore 不参与收集。"""
    nm = tmp_path / "node_modules"
    nm.mkdir()
    (nm / ".gitignore").write_text("*.py\n")  # 恶意/意外：全忽略 py
    (nm / "x.py").write_text("x")  # 目录整体被硬跳过，不受影响
    (tmp_path / "app.py").write_text("real")
    found = {p.name for p in iter_workspace_files(tmp_path)}
    assert found == {"app.py"}


def test_single_file_base(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("x")
    assert list(iter_workspace_files(f)) == [f]


def test_negate_pattern(tmp_path):
    """gitignore 取反模式（!keep.log）主干行为。"""
    (tmp_path / ".gitignore").write_text("*.log\n!keep.log\n")
    (tmp_path / "debug.log").write_text("x")
    (tmp_path / "keep.log").write_text("y")
    found = {p.name for p in iter_workspace_files(tmp_path)}
    assert "debug.log" not in found
    assert "keep.log" in found


def test_directory_pruning(tmp_path: Path):
    """深层噪音目录被剪枝（tmp/deep/node_modules/x 不产出）。"""
    deep = tmp_path / "deep" / "node_modules"
    deep.mkdir(parents=True)
    (deep / "x.py").write_text("x")
    (tmp_path / "deep" / "real.py").write_text("y")
    found = {p.name for p in iter_workspace_files(tmp_path)}
    assert found == {"real.py"}
