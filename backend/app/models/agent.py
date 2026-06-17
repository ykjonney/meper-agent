"""Agent data model for MongoDB."""
from enum import StrEnum

from pydantic import BaseModel, Field
from pydantic.config import ConfigDict

from app.models.base import generate_id, utc_now


class AgentStatus(StrEnum):
    """Agent lifecycle status."""

    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class SavedPrompt(BaseModel):
    """A saved system prompt template."""

    id: str = Field(default_factory=lambda: generate_id("prompt"))
    name: str = Field(default="default", max_length=100)
    content: str = Field(default="", max_length=10000)
    is_active: bool = Field(default=False)


class Agent(BaseModel):
    """MongoDB agent document model.

    Follows the same pattern as ``User`` — raw Pydantic model,
    serialized to dict for MongoDB insertion/update.

    Tool configuration is split into three categories:
    - ``skill_ids``: IDs of bound Skill tools (``source="markdown"``)
    - ``mcp_connection_ids``: IDs of bound MCP connections
    - ``builtin_config``: whitelist of enabled built-in tool names

    ``tool_ids`` is deprecated but kept for backward compatibility
    with old documents.  New writes should always populate both
    ``tool_ids`` and ``skill_ids``.
    """

    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(default_factory=lambda: generate_id("agent"), alias="_id")
    name: str = Field(..., min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)
    system_prompt: str = Field(default="", max_length=10000)
    saved_system_prompts: list[SavedPrompt] = Field(default_factory=list)
    # --- Deprecated: kept for backward compat ---
    tool_ids: list[str] = Field(default_factory=list)
    # --- New categorized fields ---
    skill_ids: list[str] = Field(default_factory=list)
    mcp_connection_ids: list[str] = Field(default_factory=list)
    builtin_config: list[str] = Field(default_factory=list)
    workflow_ids: list[str] = Field(default_factory=list)
    knowledge_base_ids: list[str] = Field(default_factory=list)
    llm_config: dict = Field(
        default_factory=lambda: {
            "default_model": "",
            "temperature": 0.7,
            "max_retry": 3,
        },
        description="Model configuration",
    )
    status: AgentStatus = Field(default=AgentStatus.DRAFT)
    created_at: str = Field(default_factory=lambda: utc_now().isoformat())
    updated_at: str = Field(default_factory=lambda: utc_now().isoformat())

    def model_post_init(self, __context: object) -> None:
        """Backward compat: populate skill_ids from tool_ids + migrate system_prompt."""
        super().model_post_init(__context)
        if not self.skill_ids and self.tool_ids:
            object.__setattr__(self, "skill_ids", list(self.tool_ids))
        # Migrate legacy system_prompt string to saved_system_prompts
        if not self.saved_system_prompts and self.system_prompt:
            prompt = SavedPrompt(
                id=generate_id("prompt"),
                name="default",
                content=self.system_prompt,
                is_active=True,
            )
            object.__setattr__(self, "saved_system_prompts", [prompt])
