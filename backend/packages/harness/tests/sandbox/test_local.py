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


def test_edit_file_success(tmp_path):
    """唯一匹配 → 替换成功，返回成功消息。"""
    (tmp_path / "app.py").write_text("def foo():\n    return 1\n", encoding="utf-8")
    sb = _make_sandbox(tmp_path)
    msg = sb.edit_file("app.py", "return 1", "return 42")
    assert "Successfully edited" in msg
    assert (tmp_path / "app.py").read_text(encoding="utf-8") == "def foo():\n    return 42\n"


def test_edit_file_not_found_string(tmp_path):
    """old_string 未出现 → ValueError（含提示）。"""
    (tmp_path / "app.py").write_text("print('x')\n", encoding="utf-8")
    sb = _make_sandbox(tmp_path)
    with pytest.raises(ValueError, match="not found"):
        sb.edit_file("app.py", "return 1", "return 2")


def test_edit_file_multiple_matches_error(tmp_path):
    """多处匹配且非 replace_all → ValueError（含次数）。"""
    (tmp_path / "a.txt").write_text("x = 1\ny = 1\n", encoding="utf-8")
    sb = _make_sandbox(tmp_path)
    with pytest.raises(ValueError, match="2 times"):
        sb.edit_file("a.txt", "1", "2")
    # 文件未被改动
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "x = 1\ny = 1\n"


def test_edit_file_replace_all(tmp_path):
    """replace_all=True → 全部替换。"""
    (tmp_path / "a.txt").write_text("x = 1\ny = 1\n", encoding="utf-8")
    sb = _make_sandbox(tmp_path)
    msg = sb.edit_file("a.txt", "1", "2", replace_all=True)
    assert "2 replacements" in msg
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "x = 2\ny = 2\n"


def test_edit_file_missing_file(tmp_path):
    sb = _make_sandbox(tmp_path)
    with pytest.raises(FileNotFoundError):
        sb.edit_file("nonexistent.txt", "a", "b")


def test_edit_file_path_traversal_blocked(tmp_path):
    """路径越权：编辑 work_dir 外的文件应被拒。"""
    sb = _make_sandbox(tmp_path)
    with pytest.raises((PermissionError, ValueError)):
        sb.edit_file("../../../etc/passwd", "a", "b")


def test_edit_file_large_file_not_truncated(tmp_path):
    """超过 read 截断阈值的大文件仍能完整编辑（尾部不丢失）。"""
    sb = LocalSandbox(
        sandbox_id="t", work_dir=tmp_path, output_dir=tmp_path / "output",
        max_output_chars=100,
    )
    # 尾部标记在截断阈值之外
    body = "line\n" * 100 + "TAIL_MARKER"
    (tmp_path / "big.txt").write_text(body, encoding="utf-8")
    sb.edit_file("big.txt", "TAIL_MARKER", "TAIL_EDITED")
    content = (tmp_path / "big.txt").read_text(encoding="utf-8")
    assert content.endswith("TAIL_EDITED")
    assert len(content) == len(body)


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


# ── workspace 模式（work_dir 为 {root}/tmp 结构，app 场景）────────────


def _make_workspace_sandbox(tmp_path) -> LocalSandbox:
    root = tmp_path / "ws"
    work_dir = root / "tmp"
    work_dir.mkdir(parents=True)
    (root / "input").mkdir()
    (root / "output").mkdir()
    return LocalSandbox(sandbox_id="ws", work_dir=work_dir, timeout=10)


def test_ws_write_output_edit_bare_name(tmp_path):
    """write 产物在 output/，edit 裸文件名经回退找到并写回原位置。"""
    sb = _make_workspace_sandbox(tmp_path)
    sb.write_file("report.md", "# v1\n")
    msg = sb.edit_file("report.md", "# v1", "# v2")
    assert "Successfully edited" in msg
    assert (tmp_path / "ws" / "output" / "report.md").read_text(encoding="utf-8") == "# v2\n"


def test_ws_write_output_read_bare_name(tmp_path):
    """read 裸文件名同样回退查 output/。"""
    sb = _make_workspace_sandbox(tmp_path)
    sb.write_file("report.md", "# data\n")
    assert sb.read_file("report.md") == "# data\n"


def test_ws_edit_output_prefix_paths(tmp_path):
    """output/ 前缀与 /workspace/output/ 绝对路径均可编辑 write 产物。"""
    sb = _make_workspace_sandbox(tmp_path)
    sb.write_file("a.md", "one\n")
    sb.edit_file("output/a.md", "one", "two")
    sb.write_file("b.md", "bee\n")
    sb.edit_file("/workspace/output/b.md", "bee", "boo")
    assert (tmp_path / "ws" / "output" / "a.md").read_text(encoding="utf-8") == "two\n"
    assert (tmp_path / "ws" / "output" / "b.md").read_text(encoding="utf-8") == "boo\n"


def test_ws_tmp_prefix_resolves_to_work_dir(tmp_path):
    """tmp/ 前缀与裸相对路径等价，均解析到 work_dir（tmp）。"""
    sb = _make_workspace_sandbox(tmp_path)
    (tmp_path / "ws" / "tmp" / "x.txt").write_text("hi\n", encoding="utf-8")
    assert sb.read_file("tmp/x.txt") == "hi\n"
    assert sb.read_file("x.txt") == "hi\n"


def test_ws_input_readable(tmp_path):
    """input/ 只读输入：read 可访问（相对路径与容器绝对路径）。"""
    sb = _make_workspace_sandbox(tmp_path)
    (tmp_path / "ws" / "input" / "spec.md").write_text("spec\n", encoding="utf-8")
    assert sb.read_file("input/spec.md") == "spec\n"
    assert sb.read_file("/workspace/input/spec.md") == "spec\n"


def test_ws_edit_input_rejected(tmp_path):
    """input/ 只读：edit 被拒（提示复制到工作区修改）。"""
    sb = _make_workspace_sandbox(tmp_path)
    (tmp_path / "ws" / "input" / "spec.md").write_text("spec\n", encoding="utf-8")
    with pytest.raises(PermissionError, match="read-only input"):
        sb.edit_file("input/spec.md", "spec", "modified")


def test_ws_traversal_outside_root_blocked(tmp_path):
    """workspace 模式白名单为 root 树，越出 root 仍被拒。"""
    sb = _make_workspace_sandbox(tmp_path)
    (tmp_path / "secret.txt").write_text("s", encoding="utf-8")
    with pytest.raises((PermissionError, ValueError)):
        sb.read_file("../../secret.txt")
