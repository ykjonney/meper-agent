"""Agent-related Pydantic schemas for API request/response."""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from app.models.agent import AgentStatus, RecommendedGroup, RecommendedItem
from app.utils.sanitize import sanitize_text


class CustomToolBinding(BaseModel):
    """绑定到 Agent 的自定义工具(openapi/code),携带 user_args。

    与单纯的 ``custom_tool_ids`` 不同,这里携带 ``user_args`` —— 即
    Agent 绑定时填入的参数(含敏感凭证如 token)。敏感字段在后端加密
    存储(前缀 ``enc:``),运行时由 ``decrypt_user_args`` 解密。
    """

    tool_id: str = Field(..., description="自定义工具 ID")
    user_args: dict = Field(
        default_factory=dict,
        description="绑定时填入的参数(sensitive 字段加密存储)",
    )


class AgentCreate(BaseModel):
    """Schema for creating a new Agent.

    Only essential fields at creation time. Configure system prompt,
    tools, workflows, and model via the update endpoint afterwards.
    """

    name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Agent 名称（唯一必填字段）",
        examples=["我的助手"],
    )
    description: str = Field(
        default="",
        max_length=500,
        description="Agent 简要描述",
        examples=["负责客户问答的智能助手"],
    )
    avatar: str = Field(default="", description="头像 URL 路径；空=默认 logo")

    @field_validator("name", "description", "avatar", mode="after")
    @classmethod
    def _sanitize_text_fields(cls, v: str) -> str:
        """后端纵深防御：清洗存储型 XSS 载荷（保留普通文本与 LLM 所需的
        代码/模板语法，详见 app.utils.sanitize）。"""
        return sanitize_text(v)




class AgentUpdate(BaseModel):
    """Schema for updating an existing Agent (full replacement via PUT).

    All fields optional except ``name``. Status is **not** settable —
    use the dedicated publish / archive endpoints instead.
    """

    name: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Agent 名称",
    )
    description: str = Field(
        default="",
        max_length=500,
        description="Agent 简要描述",
    )
    avatar: str = Field(
        default="",
        description="头像 URL 路径；空串=清除回默认 logo",
    )
    can_spawn_agents: bool = Field(
        default=False,
        description="允许该 agent 创建新 agent（能力门控；创建物为草稿态且不再拥有此能力）",
    )
    welcome_message: str = Field(
        default="",
        max_length=2000,
        description="终端用户首屏欢迎词（Markdown，可选）",
    )
    recommended_items: list[RecommendedItem] = Field(
        default_factory=list,
        max_length=200,
        description="首屏推荐问题/操作快捷项（≤200 条）",
    )
    recommended_groups: list[RecommendedGroup] = Field(
        default_factory=list,
        max_length=20,
        description="首屏推荐项分类分组（≤20 组，每组 ≤50 条，与独立项共存）",
    )
    system_prompt: str = Field(
        default="",
        max_length=50000,
        description="完整系统提示词（整段自由文本，支持 Jinja2 {{var}} 变量）",
    )
    # --- Categorized tool fields ---
    skill_ids: list[str] = Field(
        default_factory=list,
        description="绑定的 Skill 工具 ID（source=markdown）",
    )
    mcp_connection_ids: list[str] = Field(
        default_factory=list,
        description="绑定的 MCP 连接 ID",
    )
    builtin_config: list[str] = Field(
        default_factory=list,
        description="内置工具白名单（如 bash / read / write）",
    )
    workflow_ids: list[str] = Field(
        default_factory=list,
        description="绑定的工作流 ID",
    )
    custom_tool_ids: list[str] = Field(
        default_factory=list,
        description="绑定的自定义工具 ID（openapi/code）。向后兼容字段,"
        "优先使用 custom_tools(可携带 user_args)。",
    )
    custom_tools: list[CustomToolBinding] = Field(
        default_factory=list,
        description="绑定的自定义工具(含 user_args/凭证)。优先于 custom_tool_ids。",
    )
    knowledge_base_ids: list[str] = Field(
        default_factory=list,
        description="绑定的知识库 ID",
    )
    subagent_ids: list[str] = Field(
        default_factory=list,
        description="可委派子 Agent 池（chat 会话中可用 delegate_to_subagent 委派；仅 published 生效）",
    )
    default_model: str = Field(
        default="",
        description="绑定的 Model ID（model_xxx ULID 或纯模型名）",
    )
    voice_enabled: bool = Field(
        default=False,
        description="是否允许通过实时语音入口与该 Agent 对话",
    )
    max_retry: int = Field(
        default=3,
        ge=0,
        le=10,
        description="LLM 调用失败最大重试次数",
    )
    max_tokens: int = Field(
        default=0,
        ge=0,
        description="会话 Token 上限（累计，0 = 使用全局默认）",
    )

    @field_validator("name", "description", "welcome_message", "avatar", "system_prompt", mode="after")
    @classmethod
    def _sanitize_text_fields(cls, v: str) -> str:
        """后端纵深防御：清洗存储型 XSS 载荷。"""
        return sanitize_text(v)

    @field_validator("recommended_items", mode="after")
    @classmethod
    def _sanitize_recommended_items(cls, v: list[RecommendedItem]) -> list[RecommendedItem]:
        """逐条清洗推荐项 label / prompt 的 XSS 载荷。"""
        for item in v:
            item.label = sanitize_text(item.label)
            item.prompt = sanitize_text(item.prompt)
        return v

    @field_validator("recommended_groups", mode="after")
    @classmethod
    def _sanitize_recommended_groups(cls, v: list[RecommendedGroup]) -> list[RecommendedGroup]:
        """逐组清洗分组 title 及组内条目 label / prompt 的 XSS 载荷。"""
        for group in v:
            group.title = sanitize_text(group.title)
            for item in group.items:
                item.label = sanitize_text(item.label)
                item.prompt = sanitize_text(item.prompt)
        return v


class AgentResponse(BaseModel):
    """Agent data returned in API responses."""

    id: str
    name: str
    description: str
    avatar: str = Field(default="")
    can_spawn_agents: bool = Field(default=False, description="允许该 agent 创建新 agent")
    spawned_by_agent_id: str = Field(default="", description="父 agent id（自繁殖审计）")
    version: int = Field(default=1, description="配置版本号（每次 update +1）")
    welcome_message: str = Field(default="")
    recommended_items: list[RecommendedItem] = Field(default_factory=list)
    recommended_groups: list[RecommendedGroup] = Field(default_factory=list)
    system_prompt: str = ""
    skill_ids: list[str]
    mcp_connection_ids: list[str]
    builtin_config: list[str]
    workflow_ids: list[str]
    subagent_ids: list[str] = Field(default_factory=list, description="可委派子 Agent 池")
    custom_tool_ids: list[str] = Field(default_factory=list)
    custom_tools: list[CustomToolBinding] = Field(
        default_factory=list,
        description="绑定的自定义工具(含 user_args,敏感字段为 enc: 加密形态)",
    )
    knowledge_base_ids: list[str]
    default_model: str = Field(default="", description="Model Reference ID")
    voice_enabled: bool = Field(default=False, description="Realtime voice capability switch")
    max_retry: int = Field(default=3, description="Max LLM call retries")
    max_tokens: int = Field(default=0, description="Session token budget (0 = global default)")
    status: AgentStatus
    draft: dict | None = Field(
        default=None,
        description="草稿层（仅 published agent）：未发布的修改，publish 时合并生效",
    )
    created_at: str
    updated_at: str


class AgentListResponse(BaseModel):
    """Paginated agent list response."""

    items: list[AgentResponse]
    total: int
    page: int
    page_size: int
