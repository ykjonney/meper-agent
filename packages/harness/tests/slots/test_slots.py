"""AC1-AC13 cover: SlotDef/SLOT_SCHEMA, renderer, simple, migration compat."""

from __future__ import annotations

import pytest

from agent_flow_harness.slots import (
    SLOT_NAMES,
    SLOT_SCHEMA,
    TOOL_DECLARATION_SLOT,
    SlotDef,
    render_system_prompt_full,
    render_system_prompt_simple,
)


# ---------------------------------------------------------------------------
# schema
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# renderer: core rendering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_slots_filled() -> None:
    doc = {
        "prompt_slots": {
            "role": "R",
            "task": "T",
            "constraints": "C",
            "context": "X",
            "output_format": "O",
        }
    }
    out = await render_system_prompt_full(doc)
    assert out == "【角色定义】\nR\n\n【任务描述】\nT\n\n【约束规则】\nC\n\n【上下文信息】\nX\n\n【输出格式】\nO"


@pytest.mark.asyncio
async def test_fixed_render_order() -> None:
    """Even if config dict orders slots differently, output order is fixed."""
    doc = {"prompt_slots": {"output_format": "O", "role": "R", "task": "T"}}
    out = await render_system_prompt_full(doc)
    assert out.index("角色定义") < out.index("任务描述") < out.index("输出格式")


@pytest.mark.asyncio
async def test_optional_missing_omitted() -> None:
    doc = {"prompt_slots": {"role": "R", "task": "T"}}
    out = await render_system_prompt_full(doc)
    assert "约束规则" not in out
    assert "上下文信息" not in out
    assert out == "【角色定义】\nR\n\n【任务描述】\nT"


@pytest.mark.asyncio
async def test_label_brackets_format() -> None:
    doc = {"prompt_slots": {"role": "R", "task": "T"}}
    out = await render_system_prompt_full(doc)
    assert "【角色定义】" in out
    # No colon after the bracket label (legacy format).
    assert "【角色定义】:" not in out


@pytest.mark.asyncio
async def test_double_newline_separator() -> None:
    doc = {"prompt_slots": {"role": "R", "task": "T", "constraints": "C"}}
    out = await render_system_prompt_full(doc)
    assert "\n\n" in out
    assert out.count("\n\n") == 2  # between 3 segments


# ---------------------------------------------------------------------------
# renderer: required / strict
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_required_strict_raises() -> None:
    doc = {"prompt_slots": {"role": "R"}}  # task missing
    with pytest.raises(ValueError, match="必填 Prompt Slot 缺失"):
        await render_system_prompt_full(doc)


@pytest.mark.asyncio
async def test_missing_required_non_strict_placeholder() -> None:
    doc = {"prompt_slots": {"role": "R"}}
    out = await render_system_prompt_full(doc, strict=False)
    assert "【任务描述】\n（未配置）" in out


@pytest.mark.asyncio
async def test_empty_agent_doc_strict_raises() -> None:
    with pytest.raises(ValueError, match="必填"):
        await render_system_prompt_full({})


@pytest.mark.asyncio
async def test_empty_agent_doc_non_strict_all_placeholders() -> None:
    out = await render_system_prompt_full({}, strict=False)
    assert "【角色定义】\n（未配置）" in out
    assert "【任务描述】\n（未配置）" in out


@pytest.mark.asyncio
async def test_falsy_value_treated_as_missing() -> None:
    """Empty string slot value is treated as absent (legacy behaviour)."""
    doc = {"prompt_slots": {"role": "", "task": "T"}}
    with pytest.raises(ValueError):
        await render_system_prompt_full(doc)


# ---------------------------------------------------------------------------
# renderer: node overrides + expression resolver
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_node_overrides_highest_priority() -> None:
    doc = {"prompt_slots": {"role": "agent-role", "task": "T"}}
    out = await render_system_prompt_full(doc, node_slot_overrides={"role": "override-role"})
    assert "override-role" in out
    assert "agent-role" not in out


@pytest.mark.asyncio
async def test_node_overrides_partial() -> None:
    doc = {"prompt_slots": {"role": "R", "task": "T"}}
    out = await render_system_prompt_full(doc, node_slot_overrides={"task": "T2"})
    assert "【任务描述】\nT2" in out
    assert "【角色定义】\nR" in out  # role unchanged


@pytest.mark.asyncio
async def test_expression_resolver_applied() -> None:
    doc = {"prompt_slots": {"role": "Hello {{name}}", "task": "T"}}
    out = await render_system_prompt_full(
        doc, expression_resolver=lambda v: v.replace("{{name}}", "World")
    )
    assert "Hello World" in out


@pytest.mark.asyncio
async def test_expression_resolver_applied_to_overrides() -> None:
    doc = {"prompt_slots": {"role": "R", "task": "T"}}
    out = await render_system_prompt_full(
        doc,
        node_slot_overrides={"role": "Hi {{x}}"},
        expression_resolver=lambda v: v.replace("{{x}}", "there"),
    )
    assert "Hi there" in out


@pytest.mark.asyncio
async def test_no_resolver_passes_values_through() -> None:
    doc = {"prompt_slots": {"role": "{{raw}}", "task": "T"}}
    out = await render_system_prompt_full(doc)
    assert "{{raw}}" in out


# ---------------------------------------------------------------------------
# renderer: tool declaration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_declaration_appended() -> None:
    async def builder(_doc):
        return "可用工具: bash"

    doc = {"prompt_slots": {"role": "R", "task": "T"}}
    out = await render_system_prompt_full(doc, build_tool_declaration=builder)
    assert out.endswith("可用工具: bash")


@pytest.mark.asyncio
async def test_tool_declaration_sync_builder_supported() -> None:
    def builder(_doc):
        return "tools here"

    doc = {"prompt_slots": {"role": "R", "task": "T"}}
    out = await render_system_prompt_full(doc, build_tool_declaration=builder)
    assert "tools here" in out


@pytest.mark.asyncio
async def test_tool_declaration_empty_when_no_builder() -> None:
    doc = {"prompt_slots": {"role": "R", "task": "T"}}
    out = await render_system_prompt_full(doc)
    assert "tool" not in out.lower()
    assert not out.endswith("\n\n")


@pytest.mark.asyncio
async def test_tool_declaration_empty_string_not_appended() -> None:
    async def builder(_doc):
        return ""

    doc = {"prompt_slots": {"role": "R", "task": "T"}}
    out = await render_system_prompt_full(doc, build_tool_declaration=builder)
    assert out == "【角色定义】\nR\n\n【任务描述】\nT"


# ---------------------------------------------------------------------------
# simple renderer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_simple_no_tool_declaration_non_strict() -> None:
    doc = {"prompt_slots": {"role": "R"}}  # task missing
    out = await render_system_prompt_simple(doc)
    assert "（未配置）" in out  # non-strict placeholder
    # No builder → no tool section.
    assert "tool" not in out.lower()


@pytest.mark.asyncio
async def test_simple_renders_filled_slots() -> None:
    doc = {"prompt_slots": {"role": "R", "task": "T", "constraints": "C"}}
    out = await render_system_prompt_simple(doc)
    assert "【角色定义】\nR" in out
    assert "【约束规则】\nC" in out


@pytest.mark.asyncio
async def test_simple_ignores_build_tool_declaration_kwarg() -> None:
    """simple() never appends tools regardless of agent_doc."""
    doc = {"prompt_slots": {"role": "R", "task": "T"}}
    out = await render_system_prompt_simple(doc)
    assert out == "【角色定义】\nR\n\n【任务描述】\nT"


# ---------------------------------------------------------------------------
# migration compat: byte-identical to legacy renderer (sans tool decl / jinja)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_migration_compat_output_matches_legacy_shape() -> None:
    """The rendered prompt matches the legacy slot_renderer byte-for-byte
    when there is no tool declaration / variable pool (pure slot rendering)."""
    doc = {
        "prompt_slots": {
            "role": "You are a professional product manager.",
            "task": "分析用户需求并撰写 PRD。",
            "constraints": "- 不超过 2000 字\n- 使用简体中文",
            "context": "当前在做 agent-flow 项目",
            "output_format": "Markdown 格式",
        }
    }
    expected = (
        "【角色定义】\nYou are a professional product manager."
        "\n\n【任务描述】\n分析用户需求并撰写 PRD。"
        "\n\n【约束规则】\n- 不超过 2000 字\n- 使用简体中文"
        "\n\n【上下文信息】\n当前在做 agent-flow 项目"
        "\n\n【输出格式】\nMarkdown 格式"
    )
    out = await render_system_prompt_full(doc)
    assert out == expected
