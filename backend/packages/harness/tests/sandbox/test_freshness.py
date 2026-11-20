"""FileFreshnessTracker 单元测试 — read→edit 新鲜度基线的三态行为。"""
from __future__ import annotations

import os

import pytest

from agent_flow_harness.sandbox.freshness import FileFreshnessTracker


def _bump_mtime(path) -> None:
    """显式前移 mtime（部分文件系统 mtime 粒度粗，靠位移保证必变）。"""
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10**9))


def test_check_without_record_raises(tmp_path):
    p = tmp_path / "f.txt"
    p.write_text("x")
    t = FileFreshnessTracker()
    with pytest.raises(ValueError, match="has not been read yet"):
        t.check(p, "f.txt")


def test_record_then_check_passes(tmp_path):
    p = tmp_path / "f.txt"
    p.write_text("x")
    t = FileFreshnessTracker()
    t.record(p)
    t.check(p, "f.txt")  # 不抛即通过


def test_check_after_modification_raises(tmp_path):
    p = tmp_path / "f.txt"
    p.write_text("x")
    t = FileFreshnessTracker()
    t.record(p)
    p.write_text("yy")
    _bump_mtime(p)
    with pytest.raises(ValueError, match="modified since it was read"):
        t.check(p, "f.txt")


def test_check_size_change_without_mtime_bump(tmp_path):
    """mtime 粒度粗的同刻写入：size 变化也能兜底捕捉。"""
    p = tmp_path / "f.txt"
    p.write_text("x")
    t = FileFreshnessTracker()
    t.record(p)
    # 只改 size，不位移 mtime（同一 mtime 粒度内的写入场景）
    p.write_text("yy")
    with pytest.raises(ValueError, match="modified since"):
        t.check(p, "f.txt")


def test_update_refreshes_baseline(tmp_path):
    p = tmp_path / "f.txt"
    p.write_text("x")
    t = FileFreshnessTracker()
    t.record(p)
    p.write_text("yy")
    _bump_mtime(p)
    t.update(p)  # 编辑成功后刷新
    t.check(p, "f.txt")  # 不抛


def test_record_missing_file_clears_baseline(tmp_path):
    """文件消失后 record 应清掉旧基线（而不是留下过期能过检的状态）。"""
    p = tmp_path / "f.txt"
    p.write_text("x")
    t = FileFreshnessTracker()
    t.record(p)
    p.unlink()
    t.record(p)  # stat 失败 → 清基线
    with pytest.raises(ValueError, match="has not been read yet"):
        t.check(p, "f.txt")


def test_check_missing_file_reports_modified(tmp_path):
    """read 后文件被删：check 按"已改动"引导（read_file 会另报 not found）。"""
    p = tmp_path / "f.txt"
    p.write_text("x")
    t = FileFreshnessTracker()
    t.record(p)
    p.unlink()
    with pytest.raises(ValueError, match="modified since"):
        t.check(p, "f.txt")


def test_symlink_alias_shares_baseline(tmp_path):
    """同文件经不同路径（符号链接/相对路径）到达时互认基线（realpath key）。"""
    real = tmp_path / "real.txt"
    real.write_text("x")
    link = tmp_path / "link.txt"
    link.symlink_to(real)
    t = FileFreshnessTracker()
    t.record(real)
    t.check(link, "link.txt")  # 不抛
