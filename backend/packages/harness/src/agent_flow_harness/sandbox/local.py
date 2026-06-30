"""LocalSandbox — 默认 sandbox 实现（subprocess + 本地文件系统）。

cwd 限制为 work_dir，所有文件操作做 work_dir 白名单校验（防路径越权）。
execute_command 超时强制 kill 进程。

生产环境多租户隔离应使用 DockerSandbox/E2BSandbox；LocalSandbox 适合
开发环境和单租户场景。
"""
from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path

from agent_flow_harness.sandbox.base import GrepMatch, Sandbox, SandboxResult


class LocalSandbox(Sandbox):
    """本地 subprocess + 文件系统的 sandbox 实现。"""

    def __init__(
        self,
        sandbox_id: str,
        work_dir: Path,
        timeout: int = 120,
        max_output_chars: int = 50_000,
    ) -> None:
        self._id = sandbox_id
        self._work_dir = Path(work_dir).resolve()
        self._work_dir.mkdir(parents=True, exist_ok=True)
        self._timeout = timeout
        self._max_output = max_output_chars

    @property
    def id(self) -> str:
        return self._id

    # ── 命令执行 ──────────────────────────────────────────────────────

    def execute_command(self, command: str, *, timeout: int | None = None) -> SandboxResult:
        """执行 shell 命令，超时强制 kill。"""
        effective_timeout = timeout if timeout is not None else self._timeout
        start = time.monotonic()
        try:
            proc = subprocess.run(
                ["bash", "-c", command],
                cwd=str(self._work_dir),
                capture_output=True,
                timeout=effective_timeout,
            )
            duration = time.monotonic() - start
            return SandboxResult(
                stdout=self._truncate(proc.stdout.decode("utf-8", "replace")),
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

    def read_file(self, path: str) -> str:
        resolved = self._safe_resolve(path, for_write=False)
        if not resolved.exists():
            raise FileNotFoundError(f"File not found: {path}")
        content = resolved.read_text(encoding="utf-8", errors="replace")
        return self._truncate(content)

    def write_file(self, path: str, content: str) -> None:
        resolved = self._safe_resolve(path, for_write=True)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(content, encoding="utf-8")

    def glob(self, path: str, pattern: str) -> list[str]:
        base = self._safe_resolve(path, for_write=False)
        if not base.exists():
            return []
        return sorted(str(p) for p in base.glob(pattern))

    def grep(self, path: str, pattern: str) -> list[GrepMatch]:
        base = self._safe_resolve(path, for_write=False)
        if not base.exists():
            return []
        regex = re.compile(pattern)
        matches: list[GrepMatch] = []
        files = [base] if base.is_file() else list(base.rglob("*"))
        for f in files:
            if not f.is_file():
                continue
            try:
                lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for i, line in enumerate(lines, 1):
                if regex.search(line):
                    matches.append(GrepMatch(path=str(f), line_number=i, line=line))
        return matches

    # ── 内部 helpers ──────────────────────────────────────────────────

    def _safe_resolve(self, user_path: str, *, for_write: bool) -> Path:
        """解析路径并校验是否在 work_dir 内（防路径越权）。"""
        if os.path.isabs(user_path):
            resolved = Path(user_path).resolve()
        else:
            resolved = (self._work_dir / user_path).resolve()
        # 白名单校验：resolved 必须在 work_dir 树内
        try:
            resolved.relative_to(self._work_dir)
        except ValueError as exc:
            msg = f"Access denied — path '{user_path}' outside sandbox work_dir"
            raise PermissionError(msg) from exc
        return resolved

    def _truncate(self, text: str) -> str:
        if len(text) <= self._max_output:
            return text
        return text[: self._max_output] + f"\n... [truncated: {len(text):,} chars]"


__all__ = ["LocalSandbox"]
