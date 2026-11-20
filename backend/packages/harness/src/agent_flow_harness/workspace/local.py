"""LocalLayout — 本地接入布局：同机单 root 目录树，树内全权。

形态（用户拍板）：backend 与目标目录同机/同内网，agent 操作用户指定
的目录树——类 Claude Code 的 cwd 模式。与 CloudLayout 的本质差异：

- 无目录角色分区：root 树内处处可读写，没有 input/output 职能；
- 防越权仍是底线：解析结果必须在 root 树内（绝对路径在树内也允许，
  符号链接逃逸经 resolve() 后被白名单拦下）；
- bash 直接本机执行（LocalSandbox），cwd = root。安全边界（直接
  执行 / HITL 审批 / 静态约束）为待讨论决策点，预留 command_policy
  策略位（见 sandbox/local.py），本模块只管文件路径策略。

环境感知（describe）对齐主流最小形态：一句话 Working directory。"""
from __future__ import annotations

import os
from pathlib import Path

from agent_flow_harness.workspace.layout import (
    ResolvedPath,
    WorkspaceLayout,
    is_within,
)


class LocalLayout(WorkspaceLayout):
    """本地单 root 布局：root 树内全权读写，树外拒绝。"""

    mode = "local"

    def __init__(self, root: Path) -> None:
        self._root = Path(root).resolve()

    @property
    def root(self) -> Path:
        return self._root

    def _resolve(self, user_path: str, user_path_label: str) -> ResolvedPath:
        if os.path.isabs(user_path):
            resolved = Path(user_path).resolve()
        else:
            resolved = (self._root / user_path).resolve()
        if not is_within(resolved, self._root):
            msg = (
                f"Access denied — path '{user_path_label}' outside local "
                f"workspace root ({self._root})"
            )
            raise PermissionError(msg)
        return ResolvedPath(host=resolved, role="root", writable=True, container=None)

    def resolve_read(self, user_path: str) -> ResolvedPath:
        return self._resolve(user_path, user_path)

    def resolve_write(self, user_path: str) -> ResolvedPath:
        # 本地模式树内全权：无 CloudLayout 的 output-only 硬闸
        return self._resolve(user_path, user_path)

    def bash_cwd(self) -> str:
        return str(self._root)

    def describe(self) -> str:
        return (
            f"Working directory: {self._root}\n"
            "All file operations (read/write/edit/glob/grep) and bash are "
            "confined to this directory tree. Use write to create new files "
            "and edit to modify existing ones (read the file first)."
        )


__all__ = ["LocalLayout"]
