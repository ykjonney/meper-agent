"""6-slot system prompt schema.

Public surface:

* :class:`SlotDef` / :data:`SLOT_SCHEMA` — the fixed 5-slot schema.

Rendering lives with the host application (the app has its own
``slot_renderer``); the harness only owns the schema.
"""

from agent_flow_harness.slots.schema import (
    SLOT_NAMES,
    SLOT_SCHEMA,
    TOOL_DECLARATION_SLOT,
    SlotDef,
)

__all__ = [
    "SLOT_NAMES",
    "SLOT_SCHEMA",
    "TOOL_DECLARATION_SLOT",
    "SlotDef",
]
