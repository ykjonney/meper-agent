"""Sandbox 环境抽象 — 执行环境的统一接口（v0.2-2 三层工具模型第二层）。

工具代码（bash/read/write/glob/grep）只调 Sandbox 的抽象方法，从不直接做 I/O。
具体实现（Local/Docker）经 ContextVar 注入，换实现不改工具。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass
class SandboxResult:
    """命令执行结果。"""

    stdout: str
    stderr: str
    exit_code: int
    duration: float = 0.0
    timed_out: bool = False


@dataclass
class GrepMatch:
    """grep 单条匹配结果。context>0 时携带前后上下文行。"""

    path: str
    line_number: int
    line: str
    before: tuple[str, ...] = ()  # 命中行之前的上下文行（旧→新）
    after: tuple[str, ...] = ()  # 命中行之后的上下文行（旧→新）


class Sandbox(ABC):
    """执行环境抽象。工具代码只调这些方法，从不直接做 I/O。"""

    @property
    @abstractmethod
    def id(self) -> str:
        """sandbox 唯一标识。"""
        ...

    @abstractmethod
    def execute_command(
        self,
        command: str,
        *,
        timeout: int | None = None,
        env: dict[str, str] | None = None,
    ) -> SandboxResult:
        """执行 shell 命令。env 为额外注入的环境变量（凭证等，
        不污染宿主进程环境）。timeout=None 沿用实现配置的默认超时，
        传入值则覆盖（bash 工具的 per-call 超时即走此通道）。"""
        ...

    @abstractmethod
    def read_file(
        self,
        path: str,
        *,
        offset: int = 1,
        limit: int = 2000,
    ) -> str:
        """读文件内容（cat -n 风格行号 + 行级分页）。

        返回带 1-based 行号的格式化文本；offset 为起始行、limit 为返回
        行数，文件还有更多行时尾部附续读提示。格式化语义见
        read_ops.format_read（两实现共用）。

        同时记录新鲜度基线：edit 前必须本 run 内 read 过目标文件，
        read 后被外部改动的文件会被 edit 拒绝（见 freshness 模块）。
        """
        ...

    @abstractmethod
    def write_file(self, path: str, content: str) -> None:
        """写文件到 output 目录（用户可见/可下载）。

        写入即记录新鲜度基线：本 run 内 write 过的文件可直接 edit。
        """
        ...

    def edit_file(
        self,
        path: str,
        old_string: str,
        new_string: str,
        *,
        replace_all: bool = False,
    ) -> str:
        """就地编辑 work_dir 内文件（单条字符串替换）。

        old_string 在文件中必须唯一（replace_all=False 时），否则抛
        ValueError 说明匹配次数；未匹配抛 ValueError。返回成功消息。
        具体语义（BOM/行尾归一化、快照匹配）见 edit_ops.apply_edits，
        由 edit_file_many 统一实现。

        新鲜度契约：目标文件须本 run 内 read/write 过，且 read 之后未被
        外部改动（bash 等），否则抛 ValueError（见 freshness 模块）。
        """
        return self.edit_file_many(path, [(old_string, new_string)], replace_all=replace_all)

    @abstractmethod
    def edit_file_many(
        self,
        path: str,
        edits: Sequence[tuple[str, str]],
        *,
        replace_all: bool = False,
    ) -> str:
        """就地编辑 work_dir 内文件（批量字符串替换）。

        每条 (old_string, new_string) 都基于同一份原始内容快照匹配
        （非增量），多条编辑的命中区间不得重叠。单项编辑的错误文案与
        历史 edit_file 逐字一致；多条带 edits[i] 前缀。返回成功消息。
        """
        ...

    @abstractmethod
    def glob(self, path: str, pattern: str) -> list[str]:
        """glob 文件匹配。"""
        ...

    @abstractmethod
    def grep(
        self,
        path: str,
        pattern: str,
        *,
        context: int = 0,
        ignore_case: bool = False,
        glob_filter: str | None = None,
    ) -> list[GrepMatch]:
        """grep 内容搜索（gitignore/噪音目录感知）。

        context：每条命中携带前后各 N 行上下文；ignore_case：忽略大小写；
        glob_filter：按文件名过滤（fnmatch）。
        """
        ...


__all__ = ["Sandbox", "SandboxResult", "GrepMatch"]
