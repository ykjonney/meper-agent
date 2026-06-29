"""System prompt renderer — fixed-slot composition.

Behaviour mirrors the legacy ``backend/app/engine/agent/slot_renderer.py`` so
the rendered prompt is byte-identical:

* Fixed order: role → task → constraints → context → output_format → tool_decl.
* Each segment: ``【{label}】\\n{value}``; segments joined by ``\\n\\n``.
* Priority: ``node_slot_overrides`` > ``agent_doc["prompt_slots"]`` > absent.
* Missing required slot → ``ValueError`` (strict) or a ``（未配置）`` placeholder.

The harness owns no template engine: ``expression_resolver`` lets the host
inject Jinja2 (or any) ``{{var}}`` resolution; without it, slot values pass
through unchanged. ``build_tool_declaration`` is a stub returning ``""`` — the
host appends its own tool declaration (Story v0.1-6 方案 A).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

from agent_flow_harness.slots.schema import SLOT_SCHEMA

if TYPE_CHECKING:
    pass

ExpressionResolver = Callable[[str], str]


async def render_system_prompt_full(
    agent_doc: dict[str, Any],
    *,
    node_slot_overrides: dict[str, str] | None = None,
    variable_pool: dict[str, Any] | None = None,
    expression_resolver: ExpressionResolver | None = None,
    build_tool_declaration: Callable[[dict[str, Any]], Any] | None = None,
    strict: bool = True,
) -> str:
    """Render the full system prompt from an Agent's prompt_slots.

    Args:
        agent_doc: Agent configuration document.
        node_slot_overrides: Per-node slot overrides (highest priority).
        variable_pool: Variable pool forwarded to ``expression_resolver`` if
            provided (kept for signature parity with the legacy renderer).
        expression_resolver: Optional ``{{var}}`` resolver; when ``None`` slot
            values pass through unchanged.
        build_tool_declaration: Optional callable returning the tool
            declaration text appended at the end. ``None`` → no declaration.
        strict: When ``True`` (default), missing required slots raise
            :class:`ValueError`; when ``False`` a ``（未配置）`` placeholder is
            written instead.

    Returns:
        The fully assembled system prompt string.
    """
    _ = variable_pool  # forwarded only via expression_resolver by the host
    agent_slots: dict[str, Any] = agent_doc.get("prompt_slots", {}) or {}
    overrides: dict[str, Any] = node_slot_overrides or {}

    resolved_agent_slots = agent_slots
    resolved_overrides = overrides
    if expression_resolver is not None:
        resolved_agent_slots = {
            k: expression_resolver(v) if isinstance(v, str) else v
            for k, v in agent_slots.items()
        }
        resolved_overrides = {
            k: expression_resolver(v) if isinstance(v, str) else v
            for k, v in overrides.items()
        }

    parts: list[str] = []
    missing_required: list[str] = []

    for slot_def in SLOT_SCHEMA:
        name = slot_def.name
        label = slot_def.label

        value: Any = None
        if name in resolved_overrides and resolved_overrides[name]:
            value = resolved_overrides[name]
        elif name in resolved_agent_slots and resolved_agent_slots[name]:
            value = resolved_agent_slots[name]

        if value:
            parts.append(f"【{label}】\n{value}")
        elif slot_def.required:
            missing_required.append(label)

    if missing_required:
        if strict:
            raise ValueError(
                f"必填 Prompt Slot 缺失: {', '.join(missing_required)}。"
                f"请在 Agent 配置或节点覆写中补充这些字段。"
            )
        for label in missing_required:
            parts.append(f"【{label}】\n（未配置）")

    if build_tool_declaration is not None:
        result = build_tool_declaration(agent_doc)
        tool_decl = await result if _is_awaitable(result) else result
        if tool_decl:
            parts.append(str(tool_decl))

    return "\n\n".join(parts)


async def render_system_prompt_simple(agent_doc: dict[str, Any]) -> str:
    """Render only the 5 fixed slots (no tool declaration), non-strict.

    Useful for unit tests / previews / embedding into other prompts.
    """
    return await render_system_prompt_full(agent_doc, strict=False)


def _is_awaitable(value: Any) -> bool:
    import inspect

    return inspect.isawaitable(value)


__all__ = [
    "ExpressionResolver",
    "render_system_prompt_full",
    "render_system_prompt_simple",
]
