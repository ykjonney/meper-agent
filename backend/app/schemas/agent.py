"""Agent-related Pydantic schemas for API request/response."""
from __future__ import annotations

from pydantic import BaseModel, Field

from app.models.agent import AgentStatus


class AgentCreate(BaseModel):
    """Schema for creating a new Agent.

    Only essential fields at creation time. Configure prompt slots,
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
    prompt_slots: dict[str, str] = Field(
        default_factory=dict,
        description="提示词卡槽内容",
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
    knowledge_base_ids: list[str] = Field(
        default_factory=list,
        description="绑定的知识库 ID",
    )
    default_model: str = Field(
        default="",
        description="绑定的 Model ID（model_xxx ULID 或纯模型名）",
    )
    max_retry: int = Field(
        default=3,
        ge=0,
        le=10,
        description="LLM 调用失败最大重试次数",
    )


class AgentResponse(BaseModel):
    """Agent data returned in API responses."""

    id: str
    name: str
    description: str
    prompt_slots: dict[str, str] = Field(default_factory=dict)
    skill_ids: list[str]
    mcp_connection_ids: list[str]
    builtin_config: list[str]
    workflow_ids: list[str]
    knowledge_base_ids: list[str]
    default_model: str = Field(default="", description="Model reference ID")
    max_retry: int = Field(default=3, description="Max LLM call retries")
    status: AgentStatus
    created_at: str
    updated_at: str


class AgentListResponse(BaseModel):
    """Paginated agent list response."""

    items: list[AgentResponse]
    total: int
    page: int
    page_size: int
