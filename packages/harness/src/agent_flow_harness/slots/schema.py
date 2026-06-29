"""SlotDef + SLOT_SCHEMA — fixed 5-slot system-prompt schema.

The schema and slot labels mirror the legacy application ``prompt_template``
module exactly (``角色定义`` / ``任务描述`` / ``约束规则`` / ``上下文信息`` /
``输出格式``) so the rendered prompt is byte-identical to the legacy
``slot_renderer`` output. ``description`` is an optional, UI/docs-only field
that does not affect rendering.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class SlotDef(BaseModel):
    """Metadata for a single fixed prompt slot."""

    name: str = Field(..., description="slot key in agent_doc['prompt_slots']")
    label: str = Field(..., description="UI label + the 【】 title used in rendering")
    required: bool = Field(False, description="whether strict rendering raises on absence")
    description: str = Field("", description="docs/UI-only; does not affect rendering")


# Fixed 5-slot schema (order is significant; tool_declaration is appended
# separately by the renderer, not a user-editable slot).
SLOT_SCHEMA: list[SlotDef] = [
    SlotDef(
        name="role",
        label="角色定义",
        required=True,
        description="Agent identity and persona.",
    ),
    SlotDef(
        name="task",
        label="任务描述",
        required=True,
        description="The Agent's core task.",
    ),
    SlotDef(
        name="constraints",
        label="约束规则",
        required=False,
        description="Behavioural constraints (do / don't).",
    ),
    SlotDef(
        name="context",
        label="上下文信息",
        required=False,
        description="Domain knowledge / business background.",
    ),
    SlotDef(
        name="output_format",
        label="输出格式",
        required=False,
        description="Output format requirements (Markdown / JSON / length).",
    ),
]

SLOT_NAMES: list[str] = [s.name for s in SLOT_SCHEMA]

# tool_declaration is appended automatically — not a user-editable slot.
TOOL_DECLARATION_SLOT = "tool_declaration"


__all__ = [
    "SLOT_NAMES",
    "SLOT_SCHEMA",
    "TOOL_DECLARATION_SLOT",
    "SlotDef",
]
