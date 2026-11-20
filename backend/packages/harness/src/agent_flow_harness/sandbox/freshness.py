"""read→edit 新鲜度校验 — 防止对已被外部改动的文件盲改。

主流 coding agent（Claude Code / Cline）语义：edit 前要求本会话内 read 过
目标文件；read 之后文件若被其他通道（bash、并发 tool_call）改动，则拒绝
编辑并要求重读。harness 对应实现：Sandbox 实例维护 realpath → (mtime_ns,
size) 基线表，生命周期 = 单次 run（每次 run 经 resolve_harness_context 新建
Sandbox 实例，跨 turn 需重读——与主流会话语义一致）：

- read_file / write_file：record 记录/刷新基线（write 过的文件本 run 内
  可直接 edit）；
- edit_file_many：编辑前 check（未读拒绝 / 读后改动拒绝），成功写回后
  record 刷新基线（同文件连续编辑无需重读）。

基线同时比较 mtime_ns 与 size：部分文件系统 mtime 粒度粗（秒级），同刻
内两次写入 mtime 相同，size 可兜底捕捉绝大多数此类改动。线程安全：工具
经 asyncio.to_thread 卸载，ToolNode 并发执行同一消息的多个 tool_call，
基线表用 threading.Lock 保护。
"""
from __future__ import annotations

import os
import threading


def _not_read_msg(path: str) -> str:
    return (
        f"File '{path}' has not been read yet. "
        "Read it first, then edit (the file content may differ from your assumption)."
    )


def _modified_msg(path: str) -> str:
    return (
        f"File '{path}' has been modified since it was read "
        "(e.g. by bash or another tool). "
        "Read it again to see the current content, then retry the edit."
    )


class FileFreshnessTracker:
    """per-Sandbox 的"读后基线"表：read/write 记录，edit 校验。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # realpath → (st_mtime_ns, st_size)
        self._baselines: dict[str, tuple[int, int]] = {}

    def record(self, path: os.PathLike[str] | str) -> None:
        """记录文件当前状态为已知基线（read/write 之后调用）。

        文件此刻不可 stat（刚被删除等）则不记录——留给 edit 时按
        "未读过"处理。
        """
        key = os.path.realpath(str(path))
        try:
            stat = os.stat(key)
        except OSError:
            with self._lock:
                self._baselines.pop(key, None)
            return
        with self._lock:
            self._baselines[key] = (stat.st_mtime_ns, stat.st_size)

    def check(self, path: os.PathLike[str] | str, user_path: str) -> None:
        """编辑前校验新鲜度；未读过 / 读后已改动抛 ValueError。

        user_path 为工具入参原样路径（用于错误文案），path 为解析后的
        实际路径。
        """
        key = os.path.realpath(str(path))
        with self._lock:
            baseline = self._baselines.get(key)
        if baseline is None:
            raise ValueError(_not_read_msg(user_path))
        try:
            stat = os.stat(key)
        except OSError as exc:
            # read 之后文件消失了：按"已改动"引导重读（read_file 会报 not found）
            raise ValueError(_modified_msg(user_path)) from exc
        if (stat.st_mtime_ns, stat.st_size) != baseline:
            raise ValueError(_modified_msg(user_path))

    def check_overwrite(self, path: os.PathLike[str] | str, user_path: str) -> None:
        """write 覆写前校验（严格版，对齐 Claude Code 的 read-before-write）。

        - 目标未追踪且**存在** → 拒绝（跨 turn 旧文件：先 read 再覆写，
          防"凭记忆重产丢内容"）；未追踪且不存在 → 放行（新建文件）。
        - 已追踪 → 与 edit 同语义：read/write 之后被外部改动拒绝。
        """
        key = os.path.realpath(str(path))
        with self._lock:
            baseline = self._baselines.get(key)
        if baseline is None:
            if os.path.exists(key):
                raise ValueError(
                    f"File '{user_path}' already exists but has not been read "
                    "in this session. Read it first — write would replace the "
                    "whole file, and overwriting from memory can silently lose "
                    "content. (To fully regenerate from scratch you may still "
                    "read it briefly, then write.)"
                )
            return
        try:
            stat = os.stat(key)
        except OSError as exc:
            raise ValueError(_modified_msg(user_path)) from exc
        if (stat.st_mtime_ns, stat.st_size) != baseline:
            raise ValueError(_modified_msg(user_path))

    def update(self, path: os.PathLike[str] | str) -> None:
        """编辑成功后刷新基线（等价 record，语义别名）。"""
        self.record(path)


__all__ = ["FileFreshnessTracker"]
