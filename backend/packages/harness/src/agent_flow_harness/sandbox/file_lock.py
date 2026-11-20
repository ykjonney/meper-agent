"""同文件互斥锁 — 串行化对同一文件的并发变更（读→改→写 原子化）。

两层防护：
1. **进程内** threading.Lock：LangGraph 原生 ToolNode 对同一
   AssistantMessage 的多个 tool_call 并发执行（工具经 asyncio.to_thread
   卸载到线程池），write/edit 这类"读全文→内存修改→全量写回"的有状态
   操作若不加保护，并发时会出现丢更新、old_string not found 甚至文件
   尾部交错损坏。per-path 进程内锁让同文件操作按到达顺序串行（等价于
   逐条单编辑），跨文件仍并行。
2. **跨进程** fcntl.flock：backend 的 API 进程与 celery worker、同一
   worker 的多个并发 run 可能分属不同进程操作同一 workspace 文件——
   进程内锁管不到。在目标文件 fd 上加 LOCK_EX，临界区跨进程互斥。

已知边界：
- flock 是 POSIX advisory lock，只约束"同样走本锁"的写入者；bash
  （sed -i 等）不经本锁——此类外部改动由 freshness mtime 校验兜底
  （edit 前拒绝盲改）；
- 目标文件不存在/不可打开时退化为仅进程内锁（新文件首写无跨进程
  竞争对象；后续写者会拿到 fd）；
- NFS 挂载上 flock 语义可能弱化为本地锁——当前部署假设单机工作区。
"""
from __future__ import annotations

import contextlib
import fcntl
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
        fd: int | None = None
        try:
            # O_RDWR（不带 O_CREAT）：文件已存在才有跨进程互斥的意义；
            # 新文件首写走退化路径（创建竞态由全量覆盖语义兜底）。
            fd = os.open(key, os.O_RDWR)
            fcntl.flock(fd, fcntl.LOCK_EX)
        except OSError:
            if fd is not None:
                os.close(fd)
            fd = None
        try:
            yield
        finally:
            if fd is not None:
                with contextlib.suppress(OSError):
                    fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)


__all__ = ["file_mutation_lock"]
