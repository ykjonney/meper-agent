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
    """read 返回 cat -n 风格行号文本。"""
    (tmp_path / "note.txt").write_text("hello world", encoding="utf-8")
    sb = _make_sandbox(tmp_path)
    assert sb.read_file("note.txt") == "     1\thello world"


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
    """唯一匹配 → 替换成功，返回成功消息（read 后编辑）。"""
    (tmp_path / "app.py").write_text("def foo():\n    return 1\n", encoding="utf-8")
    sb = _make_sandbox(tmp_path)
    sb.read_file("app.py")
    msg = sb.edit_file("app.py", "return 1", "return 42")
    assert "Successfully edited" in msg
    assert (tmp_path / "app.py").read_text(encoding="utf-8") == "def foo():\n    return 42\n"


def test_edit_file_not_found_string(tmp_path):
    """old_string 未出现 → ValueError（含提示）。"""
    (tmp_path / "app.py").write_text("print('x')\n", encoding="utf-8")
    sb = _make_sandbox(tmp_path)
    sb.read_file("app.py")
    with pytest.raises(ValueError, match="not found"):
        sb.edit_file("app.py", "return 1", "return 2")


def test_edit_file_multiple_matches_error(tmp_path):
    """多处匹配且非 replace_all → ValueError（含次数）。"""
    (tmp_path / "a.txt").write_text("x = 1\ny = 1\n", encoding="utf-8")
    sb = _make_sandbox(tmp_path)
    sb.read_file("a.txt")
    with pytest.raises(ValueError, match="2 times"):
        sb.edit_file("a.txt", "1", "2")
    # 文件未被改动
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "x = 1\ny = 1\n"


def test_edit_file_replace_all(tmp_path):
    """replace_all=True → 全部替换。"""
    (tmp_path / "a.txt").write_text("x = 1\ny = 1\n", encoding="utf-8")
    sb = _make_sandbox(tmp_path)
    sb.read_file("a.txt")
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
    sb.read_file("big.txt")
    sb.edit_file("big.txt", "TAIL_MARKER", "TAIL_EDITED")
    content = (tmp_path / "big.txt").read_text(encoding="utf-8")
    assert content.endswith("TAIL_EDITED")
    assert len(content) == len(body)


# ── 匹配加固：CRLF / BOM / 批量 ───────────────────────────────────────


def test_edit_file_crlf_line_endings(tmp_path):
    """CRLF 文件用 LF 风格 old_string 可命中，写回保持 CRLF。"""
    (tmp_path / "win.md").write_bytes(b"# title\r\nbody text\r\n")
    sb = _make_sandbox(tmp_path)
    sb.read_file("win.md")
    msg = sb.edit_file("win.md", "# title\nbody", "# TITLE\nbody")
    assert "Successfully edited" in msg
    data = (tmp_path / "win.md").read_bytes()
    assert data == b"# TITLE\r\nbody text\r\n"


def test_edit_file_bom_preserved(tmp_path):
    """带 BOM 文件：无 BOM 的 old_string 可命中，BOM 保留。"""
    (tmp_path / "bom.md").write_bytes(b"\xef\xbb\xbf# title\n")
    sb = _make_sandbox(tmp_path)
    sb.read_file("bom.md")
    sb.edit_file("bom.md", "# title", "# TITLE")
    data = (tmp_path / "bom.md").read_bytes()
    assert data == b"\xef\xbb\xbf# TITLE\n"


def test_edit_file_many_batch(tmp_path):
    """批量编辑：多条替换一次落盘，成功消息带 edits 计数。"""
    (tmp_path / "doc.md").write_text("one\ntwo\nthree\n", encoding="utf-8")
    sb = _make_sandbox(tmp_path)
    sb.read_file("doc.md")
    msg = sb.edit_file_many("doc.md", [("one", "1"), ("three", "3")])
    assert msg == "Successfully edited 'doc.md' (2 replacements across 2 edits)."
    assert (tmp_path / "doc.md").read_text(encoding="utf-8") == "1\ntwo\n3\n"


def test_edit_file_many_overlap_rejected(tmp_path):
    """批量编辑区间重叠 → ValueError，文件不被改动。"""
    (tmp_path / "doc.md").write_text("hello world\n", encoding="utf-8")
    sb = _make_sandbox(tmp_path)
    sb.read_file("doc.md")
    with pytest.raises(ValueError, match="overlaps edits"):
        sb.edit_file_many("doc.md", [("hello", "HI"), ("hello world", "X")])
    assert (tmp_path / "doc.md").read_text(encoding="utf-8") == "hello world\n"


def test_edit_file_many_not_found_index(tmp_path):
    """批量中某条未命中 → 带 edits[i] 前缀的错误。"""
    (tmp_path / "doc.md").write_text("a\nb\n", encoding="utf-8")
    sb = _make_sandbox(tmp_path)
    sb.read_file("doc.md")
    with pytest.raises(ValueError, match=r"^edits\[1\]: old_string not found"):
        sb.edit_file_many("doc.md", [("a", "A"), ("missing", "M")])


def test_concurrent_edit_same_file_serialized(tmp_path):
    """同文件并发 edit_file_many 全部成功且互不覆盖（回归：个人博客会话
    13 连发 edit 竞态）。"""
    import concurrent.futures

    # 两位数字编号防子串碰撞（"line-1" 会命中 "line-10" 的子串）
    (tmp_path / "doc.md").write_text(
        "".join(f"line-{i:02d}\n" for i in range(13)), encoding="utf-8"
    )
    sb = _make_sandbox(tmp_path)
    sb.read_file("doc.md")

    def apply_one(i: int) -> str:
        return sb.edit_file("doc.md", f"line-{i:02d}", f"EDITED-{i:02d}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=13) as pool:
        results = list(pool.map(apply_one, range(13)))

    assert all("Successfully edited" in r for r in results)
    content = (tmp_path / "doc.md").read_text(encoding="utf-8")
    for i in range(13):
        assert f"EDITED-{i:02d}\n" in content
    assert "line-" not in content


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
    assert sb.read_file("report.md") == "     1\t# data"


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
    assert sb.read_file("tmp/x.txt") == "     1\thi"
    assert sb.read_file("x.txt") == "     1\thi"


def test_ws_input_readable(tmp_path):
    """input/ 只读输入：read 可访问（相对路径与容器绝对路径）。"""
    sb = _make_workspace_sandbox(tmp_path)
    (tmp_path / "ws" / "input" / "spec.md").write_text("spec\n", encoding="utf-8")
    assert sb.read_file("input/spec.md") == "     1\tspec"
    assert sb.read_file("/workspace/input/spec.md") == "     1\tspec"


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


# ── read 分页/行号（read_ops.format_read 经 read_file 的行为）──────────


def test_read_file_line_numbers(tmp_path):
    """多行文件：1-based 行号右对齐 6 宽 + tab。"""
    (tmp_path / "app.py").write_text("a\nb\nc\n", encoding="utf-8")
    sb = _make_sandbox(tmp_path)
    out = sb.read_file("app.py")
    assert out == "     1\ta\n     2\tb\n     3\tc"


def test_read_file_offset_limit_paging(tmp_path):
    """offset/limit 分页：切片正确，尾部附续读提示。"""
    body = "".join(f"line-{i}\n" for i in range(1, 11))  # 10 行
    (tmp_path / "doc.txt").write_text(body, encoding="utf-8")
    sb = _make_sandbox(tmp_path)
    out = sb.read_file("doc.txt", offset=4, limit=3)
    assert "     4\tline-4" in out
    assert "     6\tline-6" in out
    assert "line-7" not in out
    assert "[Showing lines 4-6 of 10 total lines" in out
    assert "offset=7" in out

    # 用提示给的 offset 续读，能读到末行
    tail = sb.read_file("doc.txt", offset=7, limit=2000)
    assert "    10\tline-10" in tail
    assert "Showing lines" not in tail


def test_read_file_default_limit_caps_output(tmp_path):
    """默认 limit=2000：超长文件只返回前 2000 行 + 续读提示。"""
    body = "".join(f"row-{i}\n" for i in range(2500))
    (tmp_path / "big.txt").write_text(body, encoding="utf-8")
    sb = _make_sandbox(tmp_path)
    out = sb.read_file("big.txt")
    assert " 2000\trow-1999" in out
    assert "row-2000" not in out
    assert "[Showing lines 1-2000 of 2500 total lines" in out


def test_read_file_long_line_truncated(tmp_path):
    """单行超 2000 字符 → 截断加标记，不影响其他行。"""
    long_line = "x" * 3000
    (tmp_path / "wide.txt").write_text(f"{long_line}\nshort\n", encoding="utf-8")
    sb = _make_sandbox(tmp_path)
    out = sb.read_file("wide.txt")
    assert "... [line truncated]" in out
    first_line = [ln for ln in out.split("\n") if ln.startswith("     1")][0]
    assert len(first_line) < 2100
    assert "     2\tshort" in out


def test_read_file_empty_file(tmp_path):
    (tmp_path / "empty.txt").write_text("", encoding="utf-8")
    sb = _make_sandbox(tmp_path)
    assert sb.read_file("empty.txt") == "(empty file: empty.txt)"


def test_read_file_offset_beyond_end(tmp_path):
    (tmp_path / "doc.txt").write_text("a\nb\n", encoding="utf-8")
    sb = _make_sandbox(tmp_path)
    out = sb.read_file("doc.txt", offset=99)
    assert "beyond end of file" in out
    assert "2 lines total" in out


def test_read_file_respects_max_output_budget(tmp_path):
    """字符预算：max_output_chars 很小时按预算截停，仍给续读提示。"""
    body = "".join(f"line-{i:04d}\n" for i in range(500))
    (tmp_path / "big.txt").write_text(body, encoding="utf-8")
    sb = LocalSandbox(
        sandbox_id="t", work_dir=tmp_path, output_dir=tmp_path / "output",
        max_output_chars=300,
    )
    out = sb.read_file("big.txt")
    # 输出总体不超预算太多（预算 + 单行 + 提示的余量）
    assert len(out) < 300 + 400
    assert "offset=" in out  # 续读提示存活（未被字符兜底截断吃掉）


# ── read→edit 新鲜度校验（freshness）────────────────────────────────


def test_edit_requires_read_first(tmp_path):
    """严格模式：未 read 过的文件直接 edit → ValueError 引导先读。"""
    (tmp_path / "app.py").write_text("v = 1\n", encoding="utf-8")
    sb = _make_sandbox(tmp_path)
    with pytest.raises(ValueError, match="has not been read yet"):
        sb.edit_file("app.py", "v = 1", "v = 2")
    # 文件未被改动
    assert (tmp_path / "app.py").read_text(encoding="utf-8") == "v = 1\n"


def test_edit_rejected_after_external_modification(tmp_path):
    """read 后文件被外部（模拟 bash）改动 → edit 拒绝并要求重读。"""
    p = tmp_path / "app.py"
    p.write_text("v = 1\n", encoding="utf-8")
    sb = _make_sandbox(tmp_path)
    sb.read_file("app.py")
    # 外部改动：重写内容 + 显式前移 mtime，保证 mtime/size 双条件必变
    p.write_text("v = 999\n", encoding="utf-8")
    stat = p.stat()
    os.utime(p, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10**9))
    with pytest.raises(ValueError, match="modified since it was read"):
        sb.edit_file("app.py", "v = 999", "v = 1000")


def test_edit_after_write_allowed(tmp_path):
    """write 过的文件本 run 内可直接 edit（无需 read）。"""
    sb = _make_workspace_sandbox(tmp_path)
    sb.write_file("out.txt", "draft v1\n")
    msg = sb.edit_file("out.txt", "draft v1", "draft v2")
    assert "Successfully edited" in msg


def test_consecutive_edits_no_reread(tmp_path):
    """edit 成功后刷新基线：同文件连续编辑无需重读。"""
    (tmp_path / "app.py").write_text("a = 1\nb = 2\n", encoding="utf-8")
    sb = _make_sandbox(tmp_path)
    sb.read_file("app.py")
    sb.edit_file("app.py", "a = 1", "a = 10")
    msg = sb.edit_file("app.py", "b = 2", "b = 20")
    assert "Successfully edited" in msg
    content = (tmp_path / "app.py").read_text(encoding="utf-8")
    assert content == "a = 10\nb = 20\n"


def test_reread_after_external_change_unblocks_edit(tmp_path):
    """读后被外部改动 → 重读建立新基线 → edit 放行（错误文案引导的闭环）。"""
    p = tmp_path / "app.py"
    p.write_text("v = 1\n", encoding="utf-8")
    sb = _make_sandbox(tmp_path)
    sb.read_file("app.py")
    p.write_text("v = 999\n", encoding="utf-8")
    os.utime(p, ns=(p.stat().st_atime_ns, p.stat().st_mtime_ns + 10**9))
    with pytest.raises(ValueError, match="modified since"):
        sb.edit_file("app.py", "v = 999", "v = 1000")
    sb.read_file("app.py")  # 重读
    msg = sb.edit_file("app.py", "v = 999", "v = 1000")
    assert "Successfully edited" in msg


def test_write_overwrite_requires_read(tmp_path):
    """方案 B 严格版：覆写已存在文件须先 read（防凭记忆重产丢内容）。

    write 的作用面是 output/ 产物（tmp/ 被 A1 硬闸拦截）——上一 turn
    写出的产物，本 turn 直接覆写会被要求先 read。
    """
    sb = _make_workspace_sandbox(tmp_path)  # 先建沙箱（output/ 由其创建）
    (tmp_path / "ws" / "output" / "doc.md").write_text("precious\n", encoding="utf-8")
    with pytest.raises(ValueError, match="has not been read"):
        sb.write_file("doc.md", "new\n")
    assert (tmp_path / "ws" / "output" / "doc.md").read_text(encoding="utf-8") == "precious\n"


def test_write_new_file_allowed_without_read(tmp_path):
    """新建文件放行（无覆写风险）。"""
    sb = _make_workspace_sandbox(tmp_path)
    sb.write_file("brand-new.md", "content\n")
    assert (tmp_path / "ws" / "output" / "brand-new.md").read_text() == "content\n"


def test_write_after_read_allowed_then_rejected_after_external_change(tmp_path):
    """read 后覆写放行；外部改动后覆写拒绝（与 edit 同语义）。"""
    sb = _make_workspace_sandbox(tmp_path)
    target = tmp_path / "ws" / "output" / "doc.md"
    target.write_text("v1\n", encoding="utf-8")
    sb.read_file("doc.md")  # 裸名回退查 output/，记录基线
    sb.write_file("doc.md", "v2\n")  # 已 read → 放行
    assert target.read_text(encoding="utf-8") == "v2\n"
    target.write_text("v3-external\n", encoding="utf-8")
    os.utime(target, ns=(target.stat().st_atime_ns, target.stat().st_mtime_ns + 10**9))
    with pytest.raises(ValueError, match="modified since"):
        sb.write_file("doc.md", "v4\n")


def test_read_binary_image_returns_guidance(tmp_path):
    """read 二进制图片 → 引导 view_image（不返回乱码）。"""
    (tmp_path / "chart.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
    sb = _make_sandbox(tmp_path)
    out = sb.read_file("chart.png")
    assert "view_image" in out
    assert "\x00" not in out


def test_read_binary_document_returns_guidance(tmp_path):
    (tmp_path / "doc.pdf").write_bytes(b"%PDF-1.7\n" + b"x" * 32)
    sb = _make_sandbox(tmp_path)
    assert "parse_file" in sb.read_file("doc.pdf")


def test_glob_auto_recursive(tmp_path):
    """无斜杠 pattern 自动递归（主流 Glob 行为）。"""
    sub = tmp_path / "pkg" / "sub"
    sub.mkdir(parents=True)
    (tmp_path / "a.py").write_text("")
    (sub / "b.py").write_text("")
    (tmp_path / "c.txt").write_text("")
    sb = _make_sandbox(tmp_path)
    names = [p.rsplit("/", 1)[-1] for p in sb.glob(".", "*.py")]
    assert set(names) == {"a.py", "b.py"}


def test_glob_mtime_descending(tmp_path):
    import time as _time
    a = tmp_path / "a.py"
    a.write_text("")
    _time.sleep(0.02)
    b = tmp_path / "b.py"
    b.write_text("")
    sb = _make_sandbox(tmp_path)
    names = [p.rsplit("/", 1)[-1] for p in sb.glob(".", "*.py")]
    assert names[0] == "b.py"  # 最新优先


def test_grep_context_lines(tmp_path):
    (tmp_path / "app.py").write_text("import os\n\nVALUE = 42\nprint(VALUE)\n", encoding="utf-8")
    sb = _make_sandbox(tmp_path)
    matches = sb.grep(".", "VALUE", context=1)
    assert len(matches) == 2
    first = matches[0]  # 行 3：VALUE = 42
    assert first.before == ("import os", "", ) or first.before[-1] == ""
    assert "import os" in first.before or len(first.before) == 1
    assert matches[0].after == ("print(VALUE)",) or matches[1].before == ("VALUE = 42",)


def test_grep_ignore_case_and_filter(tmp_path):
    (tmp_path / "a.py").write_text("HELLO\n", encoding="utf-8")
    (tmp_path / "b.md").write_text("hello world\n", encoding="utf-8")
    sb = _make_sandbox(tmp_path)
    assert len(sb.grep(".", "hello", ignore_case=True)) == 2
    assert len(sb.grep(".", "hello", ignore_case=True, glob_filter="*.py")) == 1
    assert len(sb.grep(".", "hello")) == 1  # 默认大小写敏感


def test_bash_cwd_persists(tmp_path):
    """cwd 跨调用持久（Claude Code 同款追踪-重放）。"""
    sub = tmp_path / "proj"
    sub.mkdir(parents=True)
    sb = _make_sandbox(tmp_path)
    r1 = sb.execute_command(f"cd {sub} && pwd >/dev/null")
    assert r1.exit_code == 0
    r2 = sb.execute_command("pwd")
    assert r2.stdout.strip() == str(sub)
    assert r2.exit_code == 0


def test_bash_cwd_deleted_dir_falls_back(tmp_path):
    """追踪的目录被删 → cd 失败回退默认 cwd（不报错、不卡死）。"""
    gone = tmp_path / "temp-dir"
    gone.mkdir()
    sb = _make_sandbox(tmp_path)
    sb.execute_command(f"cd {gone} && pwd >/dev/null")
    import shutil as _shutil
    _shutil.rmtree(gone)
    r = sb.execute_command("pwd")
    assert r.exit_code == 0
    assert r.stdout.strip() == str(tmp_path)


def test_bash_env_not_persistent(tmp_path):
    """env 不跨调用持久（与 Claude Code 同语义，工具描述已告知）。"""
    sb = _make_sandbox(tmp_path)
    sb.execute_command("export AF_TEST_VAR=hello")
    r = sb.execute_command("echo -n \"${AF_TEST_VAR:-unset}\"")
    assert r.stdout.strip() == "unset"


def test_freshness_isolated_between_sandboxes(tmp_path):
    """基线挂 Sandbox 实例（per-run）：新实例无基线 → 需重读（跨 turn 语义）。"""
    (tmp_path / "app.py").write_text("v = 1\n", encoding="utf-8")
    sb1 = _make_sandbox(tmp_path)
    sb1.read_file("app.py")
    sb2 = _make_sandbox(tmp_path)
    with pytest.raises(ValueError, match="has not been read yet"):
        sb2.edit_file("app.py", "v = 1", "v = 2")
