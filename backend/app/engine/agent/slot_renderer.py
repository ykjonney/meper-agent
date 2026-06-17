"""System prompt renderer — reads prompt_slots directly from Agent document.

Rendering order is fixed:
  role → task → constraints → context → output_format → tool_declaration (auto)

AgentNode overrides have highest priority for individual slots.

Usage::

    from app.engine.agent.slot_renderer import render_system_prompt_full

    system_text = await render_system_prompt_full(
        agent_doc,
        node_slot_overrides={"role": "You are a pirate."},
        variable_pool={"input": {"query": "Hello"}},
    )
"""
from __future__ import annotations

from typing import Any

from app.models.prompt_template import SLOT_SCHEMA, TOOL_DECLARATION_SLOT


async def render_system_prompt_full(
    agent_doc: dict,
    *,
    node_slot_overrides: dict[str, str] | None = None,
    variable_pool: dict[str, Any] | None = None,
    strict: bool = True,
) -> str:
    """Render the full system prompt from Agent's prompt_slots.

    Args:
        agent_doc: The Agent MongoDB document.
        node_slot_overrides: Per-node slot overrides (highest priority).
        variable_pool: Variable pool for Jinja2 ``{{var}}`` resolution.
        strict: When True (default), missing required slots raise ValueError.
            When False, missing slots are silently skipped (for preview).

    Returns:
        Fully assembled system prompt string.
    """
    agent_slots = agent_doc.get("prompt_slots", {})
    overrides = node_slot_overrides or {}

    # ── Resolve Jinja2 expressions in slot values ──
    resolved_agent_slots = agent_slots
    resolved_overrides = overrides
    if variable_pool:
        from app.engine.workflow.expression import ExpressionEngine

        engine = ExpressionEngine(variable_pool)
        if agent_slots:
            resolved_agent_slots = {
                k: engine.resolve(v) if isinstance(v, str) else v
                for k, v in agent_slots.items()
            }
        if overrides:
            resolved_overrides = {
                k: engine.resolve(v) if isinstance(v, str) else v
                for k, v in overrides.items()
            }

    # ── Render each fixed slot in order ──
    # Priority: node override > agent prompt_slots
    # ── Resolve + validate each fixed slot in order ──
    # Priority: node override > agent prompt_slots
    parts: list[str] = []
    missing_required: list[str] = []

    for slot_def in SLOT_SCHEMA:
        name = slot_def.name
        label = slot_def.label

        value: str | None = None
        if name in resolved_overrides and resolved_overrides[name]:
            value = resolved_overrides[name]
        elif name in resolved_agent_slots and resolved_agent_slots[name]:
            value = resolved_agent_slots[name]

        if value:
            # 用 label 作为结构化前缀，让 LLM 理解每段语义角色
            parts.append(f"【{label}】\n{value}")
        elif slot_def.required:
            missing_required.append(label)

    if missing_required:
        if strict:
            raise ValueError(
                f"必填 Prompt Slot 缺失: {', '.join(missing_required)}。"
                f"请在 Agent 配置或节点覆写中补充这些字段。"
            )
        # Non-strict mode: add placeholder for missing required slots
        for label in missing_required:
            parts.append(f"【{label}】\n（未配置）")

    # ── Always append tool_declaration at the end ──
    from app.engine.agent.builder import build_tool_declaration

    tool_decl = await build_tool_declaration(agent_doc)
    if tool_decl:
        parts.append(tool_decl)

    return "\n\n".join(parts)
