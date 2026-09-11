"""User-level tool models — 组织工具库（ToB 治理模型）。

工具是**组织级资产**，走治理流程（与技能市场的个人资产模式不同）：

    有创建权限者（tool:write）创建 → submit 提交发布 → admin 审查
    （approve → published）→ admin「开启」（校验定义+凭证完整）
    → enabled 工具才能被 Agent 绑定 / 工作流节点使用

- UserTool   工具定义与治理状态（status 状态机 + enabled 开关 +
             org_user_args 工具级统一凭证，sensitive 字段 enc: 加密）
- 凭证工具级统一：admin 配置一次，所有使用点（Agent/工作流）共用，
  不存在个人凭证/个人池注入——ToB 语义下工具使用入口收敛为
  Agent 静态绑定与工作流工具节点。
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.models.base import generate_id, utc_now

# 工具名约束：字母数字开头，可含连字符/下划线，≤64 字符
TOOL_NAME_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_\-]{0,63}$"

# 组织库可流通的工具来源（prebuilt 已移除；markdown 属技能市场；mcp 走管理员接入）
MARKET_TOOL_SOURCES = ("openapi", "code")

# code 工具可用依赖白名单（import 顶层名口径）= 标准库 + 沙箱镜像预装包。
# 镜像清单与 deploy/Dockerfile.sandbox 的 pip 安装列表保持同步——
# 改镜像时同步此处。运行时防线是沙箱隔离；此清单在创建/编辑时前置反馈，
# 避免「写完才发现依赖跑不了」。
SANDBOX_PREINSTALLED_IMPORTS = frozenset({
    # pip 包（顶层 import 名；beautifulsoup4→bs4、pyyaml→yaml、pillow→PIL）
    "pandas", "numpy", "scipy", "matplotlib", "openpyxl", "requests", "httpx",
    "yaml", "jinja2", "toml", "bs4", "lxml", "PIL", "tabulate", "rich",
    "dateutil",
    # 镜像/运行时自带
    "setuptools", "pip",
})

# code 尺寸上限（字节）——代码以 base64 命令参数传入沙箱，需远离 OS
# execve 单参数上限（Linux ~128KB）。
TOOL_CODE_MAX_BYTES = 64_000


class UserTool(BaseModel):
    """组织工具库条目。DB 是事实源（endpoint/code/schema/凭证全存本档）。"""

    id: str = Field(default_factory=lambda: generate_id("uto"), alias="_id")
    owner_user_id: str = Field(..., description="创建者（tool:write 权限用户）")
    name: str = Field(..., description="工具名（组织内唯一）")
    description: str = Field(default="", max_length=500)
    source: str = Field(..., description="openapi | code")
    # ── 工具定义 ──
    user_args_schema: dict[str, Any] = Field(
        default_factory=dict,
        description="凭证参数 schema——admin 按此配置 org_user_args（sensitive 加密）",
    )
    llm_args_schema: dict[str, Any] = Field(default_factory=dict)
    endpoint: dict[str, Any] = Field(default_factory=dict, description="HTTP endpoint 定义（openapi）")
    code: str = Field(default="", description="用户 Python 代码（code，沙箱执行）")
    # ── 治理状态 ──
    status: str = Field(
        default="private",
        description="private | submitted | published | hidden（市场审查状态机）",
    )
    enabled: bool = Field(
        default=False,
        description="admin 开启开关——True 才能被 Agent 绑定/工作流使用；"
        "开启需校验定义完整 + 凭证完整",
    )
    org_user_args: dict[str, Any] = Field(
        default_factory=dict,
        description="工具级统一凭证（sensitive 字段 enc: 加密），全使用点共用",
    )
    derived_from: str | None = Field(default=None, description="fork 来源 tool_id")
    stats: dict[str, Any] = Field(
        default_factory=lambda: {"load_count": 0, "up": 0, "down": 0},
    )
    version: int = Field(default=1, ge=1)
    tags: list[str] = Field(default_factory=list)
    avatar: str = Field(default="", description="头像 URL（预留，空=默认图标）")
    created_at: str = Field(default_factory=lambda: utc_now().isoformat())
    updated_at: str = Field(default_factory=lambda: utc_now().isoformat())
    published_at: str | None = Field(default=None)
    approved_by: str | None = Field(default=None)


__all__ = [
    "TOOL_NAME_PATTERN",
    "MARKET_TOOL_SOURCES",
    "UserTool",
]
