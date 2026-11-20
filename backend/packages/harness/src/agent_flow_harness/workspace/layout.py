"""WorkspaceLayout — workspace 路径策略的域模型（模式感知，无 I/O）。

设计原则（与工具/prompt 的职责切分）：
- **工具只讲语法**：工具描述/参数 schema 不再携带 workspace 语义
  （哪些目录可写、write 落在哪），路径怎么传由工具 schema 说；
- **prompt 讲环境**：目录布局、读写策略、双坐标系对应由
  ``describe()`` 生成环境段，注入 system prompt（宿主负责插装）；
- **layout 讲策略**：路径解析与越权/角色校验收敛在本包，
  Local/Docker 两个 Sandbox 共用（原来各复制一份 ~100 行映射代码）。

两个实现：
- ``CloudLayout``：云端托管布局（input 只读附件 / tmp 工作区 /
  output 产物交付），挂 Sandbox（Docker 优先，Local 降级）执行 bash；
- ``LocalLayout``：本地接入布局（同机单 root 目录树，树内全权，
  类 Claude Code 的 cwd 模式），bash 直接本机执行（安全策略点 TBD）。

ResolvedPath 是解析结果：host 为宿主进程视角路径（文件工具实际
操作它），container 为容器视角路径（sandboxed 模式 bash 内写法，
本地模式为 None）。"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path


def is_within(path: Path, base: Path) -> bool:
    """path 是否位于 base 目录树内。"""
    try:
        path.relative_to(base)
    except ValueError:
        return False
    return True


def _strip_leading_slash(user_path: str) -> str:
    return user_path.lstrip("/") if os.path.isabs(user_path) else user_path


@dataclass(frozen=True)
class ResolvedPath:
    """路径解析结果。"""

    host: Path  # 宿主进程视角绝对路径（read/write/edit/glob/grep 实际操作它）
    role: str  # "tmp" | "input" | "output" | "root"
    writable: bool  # write/edit 是否允许（input=False）
    container: str | None = None  # 容器视角路径（CloudLayout），local 为 None


@dataclass(frozen=True)
class SetupSpec:
    """环境预配规格（B5 预留——仅数据位，执行机制后置）。

    未来语义：workspace/容器冷启动时执行 setup_commands 装依赖/配
    工具（对齐 Codex setup script / Copilot setup-steps 模式），
    解决"复用容器被清扫后依赖蒸发"的环境漂移问题。当前字段仅供
    上层存放配置，harness 不消费。
    """

    commands: list[str] = field(default_factory=list)


class WorkspaceLayout(ABC):
    """workspace 路径策略 ABC。纯策略无 I/O，Sandbox 持有并调用。"""

    mode: str  # "cloud" | "local"

    # ── 路径解析（越权/角色校验在此抛 PermissionError）────────────────

    @abstractmethod
    def resolve_read(self, user_path: str) -> ResolvedPath:
        """解析读路径（裸相对路径的回退规则在此实现）。"""
        ...

    @abstractmethod
    def resolve_write(self, user_path: str) -> ResolvedPath:
        """解析 write 工具的目标路径（写策略硬闸在此实现）。"""
        ...

    def resolve_edit(self, user_path: str) -> ResolvedPath:
        """解析 edit 路径：默认与 read 同规则，不可写角色（input）拒绝。

        错误文案与历史 ``_reject_input_write`` 逐字一致（测试依赖）。
        """
        resolved = self.resolve_read(user_path)
        if not resolved.writable:
            raise PermissionError(
                f"Cannot edit '{user_path}' — read-only input; "
                "copy it into the workspace to modify"
            )
        return resolved

    # ── 环境感知（注入 system prompt）────────────────────────────────

    @abstractmethod
    def describe(self) -> str:
        """生成环境段文本（## Environment 段的主体，不含标题）。

        内容契约：目录布局与读写策略、bash 工作目录、双坐标系对应
        （如有容器）、write/edit 分工。英文（与工具反馈通道一致）。
        """
        ...

    @abstractmethod
    def bash_cwd(self) -> str:
        """bash 工作目录（容器视角或宿主视角字符串）。"""
        ...

    # ── 生命周期预留（B5 预配 / B4 快照）────────────────────────────

    setup: SetupSpec | None = None  # 上层可挂预配规格，harness 暂不消费

    def snapshot(self) -> str:
        """B4 预留：workspace 快照，返回快照标识。暂未实现。"""
        raise NotImplementedError("workspace snapshot is not implemented yet")


__all__ = [
    "ResolvedPath",
    "SetupSpec",
    "WorkspaceLayout",
    "is_within",
]
