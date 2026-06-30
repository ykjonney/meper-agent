"""6-slot system prompt rendering.

Public surface:

* :class:`SlotDef` / :data:`SLOT_SCHEMA` — the fixed 5-slot schema.
* :func:`render_system_prompt_full` — render the full prompt (fixed slots +
  optional tool declaration).
* :func:`render_system_prompt_simple` — render only the fixed slots (non-strict).

The renderer owns no template engine; the host injects an
``expression_resolver`` for ``{{var}}`` resolution and a
``build_tool_declaration`` callable for the appended tool list (Story v0.1-6
方案 A — harness stays free of MongoDB / Jinja2 coupling).
"""

from agent_flow_harness.slots.renderer import (
    ExpressionResolver,
    render_system_prompt_full,
    render_system_prompt_simple,
)
from agent_flow_harness.slots.schema import (
    SLOT_NAMES,
    SLOT_SCHEMA,
    TOOL_DECLARATION_SLOT,
    SlotDef,
)

__all__ = [
    "ExpressionResolver",
    "SLOT_NAMES",
    "SLOT_SCHEMA",
    "TOOL_DECLARATION_SLOT",
    "SlotDef",
    "render_system_prompt_full",
    "render_system_prompt_simple",
]
