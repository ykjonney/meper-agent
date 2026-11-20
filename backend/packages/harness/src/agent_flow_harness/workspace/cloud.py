"""CloudLayout — 云端托管布局：input 只读附件 / tmp 工作区 / output 产物。

收编原 LocalSandbox/DockerSandbox 各自复制的路径映射代码（逐字等价），
并在此落地 A1 写策略硬闸：write 只产出 output/，指向工作区（tmp/）
或只读输入（input/）时显式报错引导用 edit——把"静默错路由"变成
一次明确反馈。

workspace 模式（work_dir 为 {root}/tmp，app 场景恒成立）：
- read/edit：tmp/ output/ input/ 前缀映射对应目录，裸相对路径默认
  tmp/（不存在时回退查 output/——write 产物可裸名访问），绝对路径
  剥容器风格前缀（workspace/，容器内挂载点）；白名单 root 树内。
- write：一律映射进 output_dir（产物交付语义）；tmp//input/ 前缀
  被硬闸拒绝。

非 workspace 模式（独立使用 Sandbox 的场景）：保持旧行为——绝对
路径剥 tmp//workspace/ 前缀映射进 work_dir，白名单 work_dir 树内；
write 全部映射 output_dir（无 tmp/input 角色，不设 A1 闸）。
"""
from __future__ import annotations

import os
from pathlib import Path

from agent_flow_harness.workspace.layout import (
    ResolvedPath,
    WorkspaceLayout,
    is_within,
)

# 旧实现 write 剥前缀顺序（历史行为，保持逐字一致）
_LEGACY_WRITE_PREFIXES = ("output/", "workspace/output/", "workspace/")


class CloudLayout(WorkspaceLayout):
    """云端托管布局（三目录角色分区），Sandbox 文件操作的路径策略。"""

    mode = "cloud"

    def __init__(
        self,
        tmp_dir: Path,
        output_dir: Path,
        input_dir: Path | None = None,
        *,
        workspace_mode: bool | None = None,
        container_workspace_dir: str = "/workspace",
    ) -> None:
        self._tmp_dir = Path(tmp_dir).resolve()
        self._output_dir = Path(output_dir).resolve()
        self._input_dir = Path(input_dir).resolve() if input_dir else self._tmp_dir.parent / "input"
        # workspace 模式默认由目录结构推断（tmp 为 {root}/tmp），可显式覆盖
        self._workspace_mode = (
            self._tmp_dir.name == "tmp" if workspace_mode is None else workspace_mode
        )
        self._root = self._tmp_dir.parent if self._workspace_mode else self._tmp_dir
        self._container_ws_dir = container_workspace_dir.rstrip("/")

    # ── 目录访问器（Sandbox 仍需独立取用，如 execute_command cwd）────

    @property
    def tmp_dir(self) -> Path:
        return self._tmp_dir

    @property
    def output_dir(self) -> Path:
        return self._output_dir

    @property
    def input_dir(self) -> Path:
        return self._input_dir

    @property
    def workspace_mode(self) -> bool:
        return self._workspace_mode

    # ── 路径解析 ─────────────────────────────────────────────────────

    def resolve_read(self, user_path: str) -> ResolvedPath:
        host = self._with_output_fallback(self._resolve(user_path), user_path)
        role = self._role_of(host)
        return ResolvedPath(
            host=host,
            role=role,
            writable=role != "input",
            container=self._to_container(host),
        )

    def resolve_write(self, user_path: str) -> ResolvedPath:
        rel = user_path.lstrip("/") if os.path.isabs(user_path) else user_path
        if rel.startswith("workspace/"):
            # 剥容器风格前缀后再判角色（与 read 侧一致，否则 /workspace/tmp/
            # 绕过 A1 闸）
            rel = rel[len("workspace/"):]
        # A1 硬闸：write 指向工作区/只读输入 → 显式引导（原行为是静默
        # 错路由到 output/tmp/...、output/input/...）
        if self._workspace_mode:
            for prefix in ("tmp/", "input/"):
                if rel == prefix.rstrip("/") or rel.startswith(prefix):
                    raise PermissionError(
                        f"write targets the {'scratch workspace' if prefix == 'tmp/' else 'read-only input'} "
                        f"('{user_path}') — write creates deliverables in output/ only; "
                        "use edit to modify existing files"
                    )
        # 以下保持旧 _safe_resolve_output 行为逐字等价
        if os.path.isabs(user_path):
            r = user_path.lstrip("/")
            for prefix in _LEGACY_WRITE_PREFIXES:
                if r.startswith(prefix):
                    r = r[len(prefix):]
                    break
            resolved = (self._output_dir / r).resolve()
        else:
            resolved = (self._output_dir / user_path).resolve()
        try:
            resolved.relative_to(self._output_dir)
        except ValueError as exc:
            msg = f"Access denied — path '{user_path}' outside sandbox output_dir"
            raise PermissionError(msg) from exc
        return ResolvedPath(
            host=resolved, role="output", writable=True,
            container=self._to_container(resolved),
        )

    def resolve_edit(self, user_path: str) -> ResolvedPath:
        resolved = self.resolve_read(user_path)
        if not resolved.writable:
            # 文案与历史 _reject_input_write 逐字一致（测试与 LLM 反馈通道依赖）
            msg = (
                f"Access denied — path '{user_path}' is read-only input; "
                "copy it into the workspace to modify"
            )
            raise PermissionError(msg)
        return resolved

    def bash_cwd(self) -> str:
        if self._workspace_mode:
            return f"{self._container_ws_dir}/tmp"
        return str(self._tmp_dir)

    # ── 内部：旧 _safe_resolve / _with_output_fallback / 映射（逐字等价）─

    def _resolve(self, user_path: str) -> Path:
        allowed: tuple[Path, ...]
        if self._workspace_mode:
            rel = user_path.lstrip("/") if os.path.isabs(user_path) else user_path
            if rel.startswith("workspace/"):
                rel = rel[len("workspace/"):]
            resolved = self._map_workspace_rel(rel).resolve()
            allowed = (self._root, self._output_dir, self._input_dir)
        else:
            if os.path.isabs(user_path):
                rel = user_path.lstrip("/")
                for prefix in ("tmp/", "workspace/tmp/", "workspace/"):
                    if rel.startswith(prefix):
                        rel = rel[len(prefix):]
                        break
                resolved = (self._tmp_dir / rel).resolve()
            else:
                resolved = (self._tmp_dir / user_path).resolve()
            allowed = (self._tmp_dir,)
        if not any(is_within(resolved, base) for base in allowed):
            msg = f"Access denied — path '{user_path}' outside sandbox work_dir"
            raise PermissionError(msg)
        return resolved

    def _map_workspace_rel(self, rel: str) -> Path:
        """工作区相对路径 → 实际目录；无目录前缀默认 work_dir（tmp）。"""
        if rel.startswith("tmp/"):
            return self._tmp_dir / rel[len("tmp/"):]
        if rel.startswith("output/"):
            return self._output_dir / rel[len("output/"):]
        if rel.startswith("input/"):
            return self._input_dir / rel[len("input/"):]
        return self._tmp_dir / rel

    def _with_output_fallback(self, resolved: Path, user_path: str) -> Path:
        """裸相对路径在 tmp 下不存在时回退查 output/（write 产物在 output）。"""
        if (
            resolved.exists()
            or not user_path
            or os.path.isabs(user_path)
            or not self._workspace_mode
            or user_path.startswith(("tmp/", "output/", "input/"))
        ):
            return resolved
        alt = (self._output_dir / user_path).resolve()
        return alt if alt.exists() else resolved

    def _role_of(self, host: Path) -> str:
        if is_within(host, self._input_dir) and host != self._tmp_dir:
            return "input"
        if is_within(host, self._output_dir):
            return "output"
        return "tmp"

    def _to_container(self, host: Path) -> str | None:
        """宿主路径 → 容器内路径（模型在 bash 里看到的写法）。"""
        if not self._workspace_mode:
            return None
        for base, role in (
            (self._tmp_dir, "tmp"),
            (self._input_dir, "input"),
            (self._output_dir, "output"),
        ):
            try:
                rel = host.resolve().relative_to(base)
            except ValueError:
                continue
            return f"{self._container_ws_dir}/{role}/{rel}"
        return None

    # ── 环境感知 ─────────────────────────────────────────────────────

    def describe(self) -> str:
        lines: list[str] = []
        if self._workspace_mode:
            lines.extend([
                "Workspace layout (platform-managed, role-partitioned):",
                f"- tmp/    — scratch working area. bash starts at "
                f"{self._container_ws_dir}/tmp; bare relative paths in read/edit resolve here.",
                "- input/  — READ-ONLY user attachments. Never write or edit here; "
                "copy a file into tmp/ (or bash `cp`) to modify it.",
                "- output/ — deliverables the user can browse and download. "
                "The write tool creates files here.",
                "Coordinate systems: bash sees "
                f"{self._container_ws_dir}/{{tmp,input,output}}; file tools accept plain "
                "relative paths with optional tmp/ input/ output/ prefixes. "
                f"bash path {self._container_ws_dir}/tmp/report.md equals tool path tmp/report.md.",
                "Policy: write creates NEW files (or fully rewrites) in output/ only — "
                "pointing it at tmp/ or input/ is rejected. To modify an existing file use "
                "edit, and read the file first.",
            ])
        else:
            lines.extend([
                "Workspace layout: single working directory "
                f"({self._tmp_dir}); deliverables are written to the output directory "
                f"({self._output_dir}).",
                "Policy: write creates NEW files in the output directory; to modify an "
                "existing file use edit, and read the file first.",
            ])
        return "\n".join(lines)


__all__ = ["CloudLayout"]
