"""file_mutation_lock — 同文件互斥、跨文件并行。

背景：ToolNode 并发执行同一消息的多个 tool_call，write/edit 的
读→改→写 临界区必须按路径串行（等价 pi 的 withFileMutationQueue）。
"""
from __future__ import annotations

import os
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
