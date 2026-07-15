"""AC5/AC10 cover: LocalSandbox 实现 + 路径越权 + 超时。"""
from __future__ import annotations

import os

import pytest

from agent_flow_harness.sandbox.base import SandboxResult
from agent_flow_harness.sandbox.local import LocalSandbox


def _make_sandbox(tmp_path) -> LocalSandbox:
    return LocalSandbox(sandbox_id="test", work_dir=tmp_path, output_dir=tmp_path / "output", timeout=10)


def test_execute_command_success(tmp_path):
    sb = _make_sandbox(tmp_path)
    result = sb.execute_command("echo hello")
    assert isinstance(result, SandboxResult)
    assert result.exit_code == 0
    assert "hello" in result.stdout


def test_execute_command_stderr(tmp_path):
    sb = _make_sandbox(tmp_path)
    result = sb.execute_command("echo oops >&2")
    assert result.exit_code == 0
    assert "oops" in result.stderr


def test_execute_command_nonzero_exit(tmp_path):
    sb = _make_sandbox(tmp_path)
    result = sb.execute_command("exit 3")
    assert result.exit_code == 3


def test_execute_command_timeout(tmp_path):
    """AC10: 超时 → timed_out=True, 进程被 kill。"""
    sb = LocalSandbox(sandbox_id="t", work_dir=tmp_path, timeout=1)
    result = sb.execute_command("sleep 10")
    assert result.timed_out is True
    assert result.exit_code != 0


def test_read_file_success(tmp_path):
    (tmp_path / "note.txt").write_text("hello world", encoding="utf-8")
    sb = _make_sandbox(tmp_path)
    assert sb.read_file("note.txt") == "hello world"


def test_read_file_path_traversal_blocked(tmp_path):
    """路径越权：读 work_dir 外的文件应被拒。"""
    sb = _make_sandbox(tmp_path)
    with pytest.raises((PermissionError, ValueError)):
        sb.read_file("../../../etc/passwd")


def test_read_file_not_found(tmp_path):
    sb = _make_sandbox(tmp_path)
    with pytest.raises(FileNotFoundError):
        sb.read_file("nonexistent.txt")


def test_write_file_success(tmp_path):
    sb = _make_sandbox(tmp_path)
    sb.write_file("out.txt", "data")
    assert (tmp_path / "output" / "out.txt").read_text(encoding="utf-8") == "data"


def test_write_file_creates_parent_dirs(tmp_path):
    sb = _make_sandbox(tmp_path)
    sb.write_file("sub/dir/out.txt", "data")
    assert (tmp_path / "output" / "sub" / "dir" / "out.txt").read_text() == "data"


def test_write_file_path_traversal_blocked(tmp_path):
    """路径越权：写 output_dir 外应被拒。"""
    sb = _make_sandbox(tmp_path)
    with pytest.raises((PermissionError, ValueError)):
        sb.write_file("../../../evil.txt", "data")


def test_glob_matches(tmp_path):
    (tmp_path / "a.py").write_text("")
    (tmp_path / "b.py").write_text("")
    (tmp_path / "c.txt").write_text("")
    sb = _make_sandbox(tmp_path)
    matches = sb.glob(".", "*.py")
    names = [os.path.basename(m) for m in matches]
    assert "a.py" in names
    assert "b.py" in names
    assert "c.txt" not in names


def test_grep_matches(tmp_path):
    (tmp_path / "app.py").write_text("print('hello')\nprint('world')\n", encoding="utf-8")
    sb = _make_sandbox(tmp_path)
    matches = sb.grep(".", "hello")
    assert len(matches) == 1
    assert matches[0].line_number == 1
    assert "hello" in matches[0].line


def test_grep_no_match(tmp_path):
    (tmp_path / "app.py").write_text("print('x')\n")
    sb = _make_sandbox(tmp_path)
    assert sb.grep(".", "zzz") == []


def test_id_property(tmp_path):
    sb = LocalSandbox(sandbox_id="my-id", work_dir=tmp_path)
    assert sb.id == "my-id"
