"""file_mutation_lock — 同文件互斥、跨文件并行。

背景：ToolNode 并发执行同一消息的多个 tool_call，write/edit 的
读→改→写 临界区必须按路径串行（等价 pi 的 withFileMutationQueue）。
"""
from __future__ import annotations

import os
from pathlib import Path
import threading
import time

from agent_flow_harness.sandbox.file_lock import file_mutation_lock


def test_same_path_serialized(tmp_path):
    """同一路径的并发临界区互斥：并发计数不丢、不重。"""
    target = tmp_path / "f.txt"
    target.write_text("0", encoding="utf-8")
    counter = {"value": 0, "max_concurrent": 0}
    active = {"n": 0}
    guard = threading.Lock()
    n_threads = 8

    def worker():
        for _ in range(20):
            with file_mutation_lock(target):
                with guard:
                    active["n"] += 1
                    counter["max_concurrent"] = max(counter["max_concurrent"], active["n"])
                counter["value"] += 1
                time.sleep(0.001)  # 扩大竞争窗口
                with guard:
                    active["n"] -= 1

    threads = [threading.Thread(target=worker) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert counter["value"] == n_threads * 20
    assert counter["max_concurrent"] == 1  # 临界区从未重叠


def test_same_file_via_symlink_serialized(tmp_path):
    """同一文件经符号链接到达（realpath 归一）也互斥。"""
    real = tmp_path / "real.txt"
    real.write_text("x", encoding="utf-8")
    alias = tmp_path / "alias.txt"
    os.symlink(real, alias)

    order: list[str] = []
    guard = threading.Lock()

    def touch(path, tag):
        with file_mutation_lock(path):
            with guard:
                order.append(f"{tag}-in")
            time.sleep(0.02)
            with guard:
                order.append(f"{tag}-out")

    t1 = threading.Thread(target=touch, args=(real, "real"))
    t2 = threading.Thread(target=touch, args=(alias, "alias"))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    # in/out 必须成对交错（无重叠），不允许 real-in alias-in
    assert order[0].endswith("-in") and order[1].endswith("-out")


def test_different_paths_not_serialized(tmp_path):
    """不同路径互不阻塞：两个临界区可同时持锁。"""
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    both_entered = threading.Event()

    def hold(path, release):
        with file_mutation_lock(path):
            release.set()
            time.sleep(0.05)

    t1 = threading.Thread(target=hold, args=(a, both_entered))
    t1.start()
    assert both_entered.wait(timeout=2)
    t2 = threading.Thread(target=hold, args=(b, threading.Event()))
    t2.start()
    t2.join(timeout=2)
    assert not t2.is_alive()  # 未被 a 的锁阻塞
    t1.join()


# ── A3: 跨进程互斥（fcntl.flock）────────────────────────────────────


def _cross_process_child(target: str, start_flag: str, done_flag: str) -> None:
    """子进程体（模块级——macOS spawn 启动方式不能 pickle 闭包）。"""
    target_path = Path(target)
    with file_mutation_lock(target_path):
        Path(start_flag).write_text("1", encoding="utf-8")
        time.sleep(0.4)
        target_path.write_text("child-done", encoding="utf-8")
    Path(done_flag).write_text("1", encoding="utf-8")


def test_cross_process_serialized(tmp_path):
    """A3: 另一进程持锁期间，本进程临界区被 flock 阻塞直至其释放。

    模拟 API 进程 vs celery worker 并发写同一 workspace 文件。
    """
    import multiprocessing

    target = tmp_path / "shared.txt"
    target.write_text("", encoding="utf-8")
    start_flag = tmp_path / ".child-in"
    done_flag = tmp_path / ".child-out"

    proc = multiprocessing.Process(
        target=_cross_process_child,
        args=(str(target), str(start_flag), str(done_flag)),
    )
    proc.start()

    # 等子进程确认已进入临界区（拿到 flock）
    deadline = time.monotonic() + 5
    while not start_flag.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert start_flag.exists(), "child never entered critical section"

    # 本进程此刻尝试拿锁：必须等到子进程释放（期间文件内容已是 child 写的）
    entered_at = time.monotonic()
    with file_mutation_lock(target):
        held = time.monotonic() - entered_at
        content = target.read_text(encoding="utf-8")

    assert content == "child-done"  # 拿到锁时子进程已写完
    assert held >= 0.05  # 确实等过子进程的临界区（flock 生效，非并行进入）
    proc.join(timeout=5)
    assert done_flag.exists()
    assert not proc.is_alive()


def test_missing_file_degrades_to_process_lock(tmp_path):
    """目标文件不存在：退化为仅进程内锁（不抛错，新文件首写场景）。"""
    ghost = tmp_path / "not-yet.txt"
    with file_mutation_lock(ghost):
        ghost.write_text("created inside lock", encoding="utf-8")
    assert ghost.read_text(encoding="utf-8") == "created inside lock"
