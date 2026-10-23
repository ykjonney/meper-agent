"""SlotDef/SLOT_SCHEMA schema cover (rendering lives with the host app)."""

from __future__ import annotations

from agent_flow_harness.slots import (
    SLOT_NAMES,
    SLOT_SCHEMA,
    TOOL_DECLARATION_SLOT,
    SlotDef,
)


def test_slot_schema_has_five_fixed_slots_in_order() -> None:
    assert [s.name for s in SLOT_SCHEMA] == [
        "role",
        "task",
        "constraints",
        "context",
        "output_format",
    ]


def test_slot_schema_labels_match_legacy() -> None:
    """AC13: labels must match the legacy backend exactly."""
    assert [s.label for s in SLOT_SCHEMA] == [
        "角色定义",
        "任务描述",
        "约束规则",
        "上下文信息",
        "输出格式",
    ]


def test_required_flags() -> None:
    by_name = {s.name: s.required for s in SLOT_SCHEMA}
    assert by_name == {
        "role": True,
        "task": True,
        "constraints": False,
        "context": False,
        "output_format": False,
    }


def test_slot_names_and_tool_declaration_constant() -> None:
    assert SLOT_NAMES == [s.name for s in SLOT_SCHEMA]
    assert TOOL_DECLARATION_SLOT == "tool_declaration"


def test_slotdef_defaults() -> None:
    s = SlotDef(name="x", label="X")
    assert s.required is False
    assert s.description == ""
