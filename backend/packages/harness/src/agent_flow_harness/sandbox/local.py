"""LocalSandbox — 默认 sandbox 实现（subprocess + 本地文件系统）。

cwd 限制为 work_dir；文件路径策略委托注入的 WorkspaceLayout
（cloud.py 的 CloudLayout，或本地接入的 LocalLayout），本类不再自带
路径映射逻辑。execute_command 超时强制 kill 进程。

生产环境多租户隔离应使用 DockerSandbox/E2BSandbox；LocalSandbox 适合
开发环境和单租户场景（也作为 DockerSandbox 的降级执行通道）。
"""
from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from collections.abc import Sequence

from agent_flow_harness.sandbox.base import GrepMatch, Sandbox, SandboxResult
from agent_flow_harness.sandbox.edit_ops import apply_edits
from agent_flow_harness.sandbox.file_lock import file_mutation_lock
from agent_flow_harness.sandbox.freshness import FileFreshnessTracker
from agent_flow_harness.sandbox.read_ops import format_read, sniff_binary_kind
from agent_flow_harness.sandbox.shell_state import extract_cwd, wrap_cwd_command
from agent_flow_harness.workspace.cloud import CloudLayout
from agent_flow_harness.workspace.layout import WorkspaceLayout
from agent_flow_harness.workspace.scan import glob_workspace_files, grep_workspace


class LocalSandbox(Sandbox):
    """本地 subprocess + 文件系统的 sandbox 实现。"""

    def __init__(
        self,
        sandbox_id: str,
        work_dir: Path,
        timeout: int = 120,
        max_output_chars: int = 50_000,
        output_dir: Path | None = None,
        layout: WorkspaceLayout | None = None,
    ) -> None:
        self._id = sandbox_id
        self._work_dir = Path(work_dir).resolve()
        self._work_dir.mkdir(parents=True, exist_ok=True)
        self._timeout = timeout
        self._max_output = max_output_chars
        # output_dir: 用户可见文件目录（task workspace.output_dir）
        # 如果未提供，默认使用 work_dir 的父目录下的 output/
        self._output_dir = Path(output_dir).resolve() if output_dir else self._work_dir.parent / "output"
        self._output_dir.mkdir(parents=True, exist_ok=True)
        # 路径策略委托 layout（默认按旧参数构造 CloudLayout，向后兼容）。
        # 本地接入场景传入 LocalLayout(root)，work_dir 即 root。
        self._layout = layout or CloudLayout(
            self._work_dir, self._output_dir,
            container_workspace_dir="/workspace",
        )
        # cloud 布局才需要产物目录；local 布局（用户自有目录树）禁止在
        # root 外创建 output/——污染用户文件系统
        if self._layout.mode == "cloud":
            self._output_dir.mkdir(parents=True, exist_ok=True)
        # read→edit 新鲜度基线（per-run 生命周期）：edit 前必须 read/write 过
        self._freshness = FileFreshnessTracker()
        # bash cwd 跨调用状态（shell_state 追踪-重放，per-run 生命周期）
        self._cwd: str | None = None

    @property
    def layout(self) -> WorkspaceLayout:
        return self._layout

    @property
    def id(self) -> str:
        return self._id

    # ── 命令执行 ──────────────────────────────────────────────────────

    def execute_command(
        self,
        command: str,
        *,
        timeout: int | None = None,
        env: dict[str, str] | None = None,
    ) -> SandboxResult:
        """执行 shell 命令，超时强制 kill。env 合并注入子进程，不污染宿主。

        cwd 跨调用持久（Claude Code 同款追踪-重放）：注入 cd 到上次目录、
        尾部捕获 $PWD 存回实例状态（shell_state.py）；env 不持久。
        """
        effective_timeout = timeout if timeout is not None else self._timeout
        base_cwd = self._cwd or self._layout.bash_cwd()
        wrapped, parse_re = wrap_cwd_command(command, base_cwd)
        start = time.monotonic()
        try:
            proc = subprocess.run(
                ["bash", "-c", wrapped],
                cwd=str(self._work_dir),
                capture_output=True,
                timeout=effective_timeout,
                env={**os.environ, **(env or {})},
            )
            duration = time.monotonic() - start
            stdout_raw = proc.stdout.decode("utf-8", "replace")
            stdout, new_cwd = extract_cwd(stdout_raw, parse_re)
            if new_cwd:
                self._cwd = new_cwd
            return SandboxResult(
                stdout=self._truncate(stdout),
                stderr=self._truncate(proc.stderr.decode("utf-8", "replace")),
                exit_code=proc.returncode,
                duration=duration,
                timed_out=False,
            )
        except subprocess.TimeoutExpired:
            duration = time.monotonic() - start
            return SandboxResult(
                stdout="",
                stderr=f"[timeout] Command exceeded {effective_timeout}s and was killed.",
                exit_code=-1,
                duration=duration,
                timed_out=True,
            )

    # ── 文件操作 ──────────────────────────────────────────────────────

    def read_file(
        self,
        path: str,
        *,
        offset: int = 1,
        limit: int = 2000,
    ) -> str:
        """读文件内容：cat -n 风格行号 + offset/limit 行级分页（read_ops）。

        读取即记录新鲜度基线——edit 前必须 read 过，read 后被 bash 等
        外部改动的文件会被 edit 拒绝（freshness 校验）。
        """
        resolved = self._layout.resolve_read(path).host
        if not resolved.exists():
            raise FileNotFoundError(f"File not found: {path}")
        data = resolved.read_bytes()
        kind = sniff_binary_kind(data)
        if kind == "image":
            self._freshness.record(resolved)
            return (
                f"This is a binary image file ('{path}') and cannot be read as text. "
                "Use the view_image tool to view it."
            )
        if kind == "document":
            self._freshness.record(resolved)
            return (
                f"This is a binary file ('{path}') and cannot be read as text. "
                "If it is a document (PDF/Office), use the parse_file tool to "
                "extract its content; otherwise inspect it with bash tools."
            )
        content = data.decode("utf-8", errors="replace")
        self._freshness.record(resolved)
        return self._truncate(
            format_read(
                content, path=path, offset=offset, limit=limit,
                max_chars=self._max_output,
            )
        )

    def write_file(self, path: str, content: str) -> None:
        """写文件（路径策略由 layout 决定：cloud=产物 output/，local=root 内）。

        同文件并发经互斥锁串行；覆写已存在文件须本 run 内 read/write 过
        （freshness 校验——write 是全量替换，凭记忆覆写会静默丢内容）；
        写入即记录新鲜度基线：本 run 内 write 过的文件可直接 edit。
        """
        resolved = self._layout.resolve_write(path).host
        with file_mutation_lock(resolved):
            self._freshness.check_overwrite(resolved, path)
            resolved.parent.mkdir(parents=True, exist_ok=True)
            resolved.write_text(content, encoding="utf-8")
            self._freshness.record(resolved)

    def edit_file_many(
        self,
        path: str,
        edits: Sequence[tuple[str, str]],
        *,
        replace_all: bool = False,
    ) -> str:
        """就地编辑文件：互斥锁内 读全文（不截断）→ 快照匹配 → 替换写回。

        ToolNode 对同一消息的多个 tool_call 并发执行，锁保证同文件的
        读→改→写 临界区串行（否则丢更新/匹配错乱/尾部交错损坏）。
        匹配语义（BOM/行尾归一化、重叠校验）统一在 edit_ops.apply_edits。

        新鲜度校验（freshness，锁内进行）：文件须本 run 内 read/write 过，
        read 后被外部改动则抛 ValueError 拒绝编辑；成功写回后刷新基线，
        同文件连续编辑无需重读。
        """
        resolved = self._layout.resolve_edit(path).host
        with file_mutation_lock(resolved):
            if not resolved.exists():
                raise FileNotFoundError(f"File not found: {path}")
            self._freshness.check(resolved, path)
            # newline=""：关闭 universal newlines 翻译，保留原始 \r\n（否则
            # 读入已被翻成 \n，行尾归一化检测失效、写回会把整个文件转成 LF）
            with resolved.open("r", encoding="utf-8", errors="replace", newline="") as f:
                content = f.read()
            new_content, message = apply_edits(
                content, edits, path=path, replace_all=replace_all
            )
            with resolved.open("w", encoding="utf-8", newline="") as f:
                f.write(new_content)
            self._freshness.record(resolved)
        return message

    def glob(self, path: str, pattern: str) -> list[str]:
        base = self._layout.resolve_read(path).host
        if not base.exists():
            return []
        return [str(p) for p in glob_workspace_files(base, pattern)]

    def grep(
        self,
        path: str,
        pattern: str,
        *,
        context: int = 0,
        ignore_case: bool = False,
        glob_filter: str | None = None,
    ) -> list[GrepMatch]:
        base = self._layout.resolve_read(path).host
        if not base.exists():
            return []
        return grep_workspace(
            base, pattern,
            context=context, ignore_case=ignore_case, glob_filter=glob_filter,
        )

    # ── 内部 helpers ──────────────────────────────────────────────────

    def _truncate(self, text: str) -> str:
        if len(text) <= self._max_output:
            return text
        return text[: self._max_output] + f"\n... [truncated: {len(text):,} chars]"


__all__ = ["LocalSandbox"]
