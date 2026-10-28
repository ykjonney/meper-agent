"""同文件互斥锁 — 串行化对同一文件的并发变更（读→改→写 原子化）。

LangGraph 原生 ToolNode 对同一 AssistantMessage 的多个 tool_call 是并发
执行的；write/edit 这类"读全文→内存修改→全量写回"的有状态操作若不加
保护，并发时会出现丢更新（后写覆盖先写）、old_string not found（读到
被竞争者改过的中间态）甚至文件尾部交错损坏。加 per-path 进程内锁后，
同文件操作按到达顺序串行（等价于逐条单编辑），跨文件仍并行。

仅进程内有效：所有并发都发生在同一后端进程（工具经 asyncio.to_thread
卸载到线程池），threading.Lock 即足够；无需跨进程文件锁。
"""
from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from collections.abc import Iterator

_registry_lock = threading.Lock()
_locks: dict[str, threading.Lock] = {}


@contextmanager
def file_mutation_lock(path: os.PathLike[str] | str) -> Iterator[None]:
    """按 realpath 串行化临界区；不同文件互不阻塞。

    key 用 realpath：同一文件经不同符号链接/相对路径到达时也互斥。
    锁条目不回收——进程生命周期内不同路径数量有限，条目开销可忽略。
    """
    key = os.path.realpath(str(path))
    with _registry_lock:
        lock = _locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _locks[key] = lock
    with lock:
        yield


__all__ = ["file_mutation_lock"]
