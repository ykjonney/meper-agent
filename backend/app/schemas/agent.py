"""Agent-related Pydantic schemas for API request/response."""
from __future__ import annotations

from pydantic import BaseModel, Field

from app.models.agent import AgentStatus


class SavedPromptItem(BaseModel):
    """A saved system prompt template in API payloads."""

    id: str = Field(default="", description="Prompt ID (auto-generated if empty)")
    name: str = Field(default="default", max_length=100, description="Prompt name")
    content: str = Field(default="", max_length=10000, description="Prompt content")
    is_active: bool = Field(default=False, description="Whether this is the active prompt")


class AgentCreate(BaseModel):
    """Schema for creating a new Agent."""

    name: str = Field(..., min_length=1, max_length=100, description="Agent name")
    description: str = Field(default="", max_length=500, description="Agent description")
    system_prompt: str = Field(default="", max_length=10000, description="Active system prompt")
    saved_system_prompts: list[SavedPromptItem] = Field(default_factory=list, description="Saved prompt templates")
    # --- Deprecated: use skill_ids instead ---
    tool_ids: list[str] = Field(default_factory=list, description="Deprecated: use skill_ids")
    # --- New categorized fields ---
    skill_ids: list[str] = Field(default_factory=list, description="Bound Skill tool IDs (source=markdown)")
    mcp_connection_ids: list[str] = Field(default_factory=list, description="Bound MCP connection IDs")
    builtin_config: list[str] = Field(default_factory=list, description="Enabled built-in tool names (whitelist)")
    workflow_ids: list[str] = Field(default_factory=list, description="Bound workflow IDs")
    knowledge_base_ids: list[str] = Field(default_factory=list, description="Bound knowledge base IDs")
    llm_config: dict = Field(
        default_factory=lambda: {
            "default_model": "",
            "temperature": 0.7,
            "max_retry": 3,
        },
        description="Model configuration",
    )


class AgentUpdate(BaseModel):
    """Schema for updating an existing Agent (full replacement via PUT).

    ``status`` is optional — when omitted (None), the service layer
    preserves the existing status so editing a published Agent does
    not reset it to draft.
    """

    name: str = Field(..., min_length=1, max_length=100, description="Agent name")
    description: str = Field(default="", max_length=500, description="Agent description")
    system_prompt: str = Field(default="", max_length=10000, description="Active system prompt")
    saved_system_prompts: list[SavedPromptItem] = Field(default_factory=list, description="Saved prompt templates")
    # --- Deprecated: use skill_ids instead ---
    tool_ids: list[str] = Field(default_factory=list, description="Deprecated: use skill_ids")
    # --- New categorized fields ---
    skill_ids: list[str] = Field(default_factory=list, description="Bound Skill tool IDs (source=markdown)")
    mcp_connection_ids: list[str] = Field(default_factory=list, description="Bound MCP connection IDs")
    builtin_config: list[str] = Field(default_factory=list, description="Enabled built-in tool names (whitelist)")
    workflow_ids: list[str] = Field(default_factory=list, description="Bound workflow IDs")
    knowledge_base_ids: list[str] = Field(default_factory=list, description="Bound knowledge base IDs")
    llm_config: dict = Field(
        default_factory=lambda: {
            "default_model": "",
            "temperature": 0.7,
            "max_retry": 3,
        },
        description="Model configuration",
    )
    status: AgentStatus | None = Field(
        default=None,
        description="Optional new status. None preserves existing status.",
    )


class AgentResponse(BaseModel):
    """Agent data returned in API responses."""

    id: str
    name: str
    description: str
    system_prompt: str
    saved_system_prompts: list[SavedPromptItem] = Field(default_factory=list)
    tool_ids: list[str]
    skill_ids: list[str]
    mcp_connection_ids: list[str]
    builtin_config: list[str]
    workflow_ids: list[str]
    knowledge_base_ids: list[str]
    llm_config: dict = Field(
        default_factory=lambda: {
            "default_model": "",
            "temperature": 0.7,
            "max_retry": 3,
        },
        description="Model configuration",
    )
    status: AgentStatus
    version: int
    created_at: str
    updated_at: str


class ModelConfigUpdate(BaseModel):
    """Schema for updating only the Agent's model configuration (PATCH)."""

    default_model: str = Field(
        default="",
        description="Model reference (_id) or legacy model name string",
    )
    temperature: float = Field(default=0.7, ge=0.0, le=2.0, description="Model temperature")
    max_retry: int = Field(default=3, ge=0, le=10, description="Max retry count")


class AgentListResponse(BaseModel):
    """Paginated agent list response."""

    items: list[AgentResponse]
    total: int
    page: int
    page_size: int
