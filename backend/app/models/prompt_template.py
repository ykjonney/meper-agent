"""PromptTemplate model — fixed-slot prompt composition.

Slot schema is fixed and defined in SLOT_SCHEMA:
  role → task → constraints → context → output_format → tool_declaration (auto)

Templates only store default values for each slot.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.base import generate_id, utc_now


# ── Fixed slot schema ────────────────────────────────────────────────

class SlotDef(BaseModel):
    """Definition of a single fixed slot (code-level constant)."""
    name: str
    label: str
    required: bool = False


SLOT_SCHEMA: list[SlotDef] = [
    SlotDef(name="role", label="角色定义", required=True),
    SlotDef(name="task", label="任务描述", required=True),
    SlotDef(name="constraints", label="约束规则"),
    SlotDef(name="context", label="上下文信息"),
    SlotDef(name="output_format", label="输出格式"),
]

SLOT_NAMES: list[str] = [s.name for s in SLOT_SCHEMA]

# tool_declaration is always appended automatically — not a user-editable slot.
TOOL_DECLARATION_SLOT = "tool_declaration"


class PromptTemplate(BaseModel):
    """A reusable prompt template with default values for fixed slots."""

    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(default_factory=lambda: generate_id("tmpl"), alias="_id")
    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="", max_length=1000)
    slot_defaults: dict[str, str] = Field(default_factory=dict)
    version: int = Field(default=1)
    tags: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: utc_now().isoformat())
    updated_at: str = Field(default_factory=lambda: utc_now().isoformat())
