"""Tool data model for MongoDB — unified tool pool (Markdown Skill / MCP / etc.)."""
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field
from pydantic.config import ConfigDict

from app.models.base import generate_id, utc_now


class ToolStatus(StrEnum):
    """Tool lifecycle status."""

    DRAFT = "draft"
    ACTIVE = "active"
    INACTIVE = "inactive"


class SkillFile(BaseModel):
    """A single file inside a Skill directory package."""

    path: str = Field(..., description="相对路径，如 'SKILL.md' 或 'steps/step-01.md'")
    content: str = Field(..., description="文件内容（UTF-8 文本）")
    size: int = Field(default=0, description="文件大小（bytes）")


class Tool(BaseModel):
    """MongoDB tool document model.

    Follows the same pattern as ``Agent`` — raw Pydantic model,
    serialized to dict for MongoDB insertion/update.

    ``source`` distinguishes the origin (``"markdown"`` for uploaded
    Skill files, ``"mcp"`` for MCP-discovered tools, etc.).

    ``files`` stores directory-based Skill packages: a list of
    :class:`SkillFile` entries (path + content).  Legacy single-file
    tools keep ``files`` as an empty list.
    """

    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(default_factory=lambda: generate_id("tool"), alias="_id")
    name: str = Field(..., min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    instructions: str = Field(default="", description="Markdown body / usage notes")
    source: str = Field(default="markdown", description="Origin: markdown / mcp")
    source_file: str = Field(default="", description="Original filename")
    mcp_connection_id: str = Field(
        default="",
        description="关联的 MCP 连接 ID（仅 source=mcp 时有效）",
    )
    status: ToolStatus = Field(default=ToolStatus.DRAFT)
    version: int = Field(default=1, ge=1)
    tags: list[str] = Field(default_factory=list)
    files: list[SkillFile] = Field(
        default_factory=list,
        description="目录模式下的文件列表（单文件模式为空）",
    )
    created_at: str = Field(default_factory=lambda: utc_now().isoformat())
    updated_at: str = Field(default_factory=lambda: utc_now().isoformat())
