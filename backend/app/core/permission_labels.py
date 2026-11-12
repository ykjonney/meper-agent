"""权限键 → 中文名映射（单一权威源）。

前端展示权限一律用中文名（/auth/me 的 permission_labels 下发），新增权限
只需在此表加一行——前端零改动。未登记的键回退原始 key（永不白屏）。
"""
from __future__ import annotations

# 资源 → 中文名（含动作细分时用完整键精确映射，其余按「资源·动作」合成）。
PERMISSION_LABELS: dict[str, str] = {
    # 用户与设置
    "user:read": "用户·查看",
    "user:write": "用户·管理",
    "settings:manage": "系统设置·管理",
    "apikey:manage": "API 密钥·管理",
    # 智能体
    "agent:read": "智能体·查看",
    "agent:write": "智能体·管理",
    "agent:invoke": "智能体·调用",
    # 工作流与工具
    "workflow:read": "工作流·查看",
    "workflow:write": "工作流·管理",
    "tool:read": "工具·查看",
    "tool:write": "工具·管理",
    "skill:read": "技能·查看",
    "skill:write": "技能·管理",
    "mcp:read": "MCP 接入·查看",
    "mcp:write": "MCP 接入·管理",
    "knowledge:read": "知识库·查看",
    "knowledge:write": "知识库·管理",
    # 任务与执行
    "task:read": "任务·查看",
    "task:write": "任务·管理",
    "task:invoke": "任务·发起",
    "execution:read:all": "执行记录·查看全部",
    "execution:read:own": "执行记录·查看本人",
    "trigger:read": "调度规则·查看",
    "trigger:write": "调度规则·管理",
    "trigger:manage": "调度规则·跨用户管理",
    # 模型与渠道
    "model:read": "模型·查看",
    "model:write": "模型·管理",
    "channel:read": "渠道·查看",
    "channel:write": "渠道·管理",
    # 应用授权
    "application:read": "应用授权·查看",
    "application:write": "应用授权·管理",
}

# 资源段 → 中文（未精确登记的键按「资源·动作」合成兜底）
_RESOURCE_ZH: dict[str, str] = {
    "user": "用户", "agent": "智能体", "workflow": "工作流", "tool": "工具",
    "application": "应用授权", "mcp": "MCP 接入", "skill": "技能", "task": "任务",
    "knowledge": "知识库", "execution": "执行记录", "apikey": "API 密钥",
    "settings": "系统设置", "model": "模型", "trigger": "调度规则", "channel": "渠道",
}
_ACTION_ZH: dict[str, str] = {
    "read": "查看", "write": "管理", "invoke": "调用", "manage": "管理",
}


def permission_label(key: str) -> str:
    """权限键的中文名；精确表未登记时按「资源·动作」合成，仍无法识别回退原 key。"""
    label = PERMISSION_LABELS.get(key)
    if label:
        return label
    parts = key.split(":")
    if len(parts) >= 2:
        res = _RESOURCE_ZH.get(parts[0])
        action = _ACTION_ZH.get(":".join(parts[1:])) or _ACTION_ZH.get(parts[1])
        if res and action:
            return f"{res}·{action}"
    return key
