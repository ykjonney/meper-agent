"""Compatibility shim — adapters have moved to the application layer.

The real implementation now lives at
``app.engine.harness_integration.adapters``. This module uses lazy
``__getattr__`` to re-export the public symbols so that:

1. Harness-internal code (``api.py``) and existing harness tests continue
   to work without import changes.
2. Importing ``agent_flow_harness.adapters`` does NOT eagerly pull in
   the app layer (preserving harness's dependency isolation).

New code should import from ``app.engine.harness_integration.adapters``
directly.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.engine.harness_integration.adapters.app_event import (
        AppEvent,
        ErrorEvent,
        InterruptEvent,
        TextDeltaEvent,
        TextEvent,
        ThinkingDeltaEvent,
        ThinkingEvent,
        ToolCallEvent,
        ToolCallStartEvent,
        ToolResultEvent,
    )
    from app.engine.harness_integration.adapters.messages import messages_to_app_events
    from app.engine.harness_integration.adapters.stream_events import (
        OnEventCallback,
        stream_events_to_app_events,
    )

__all__ = [
    "AppEvent",
    "ErrorEvent",
    "InterruptEvent",
    "OnEventCallback",
    "TextDeltaEvent",
    "TextEvent",
    "ThinkingDeltaEvent",
    "ThinkingEvent",
    "ToolCallEvent",
    "ToolCallStartEvent",
    "ToolResultEvent",
    "messages_to_app_events",
    "stream_events_to_app_events",
]

_SYMBOLS = {
    "AppEvent": "app.engine.harness_integration.adapters.app_event",
    "ErrorEvent": "app.engine.harness_integration.adapters.app_event",
    "InterruptEvent": "app.engine.harness_integration.adapters.app_event",
    "TextDeltaEvent": "app.engine.harness_integration.adapters.app_event",
    "TextEvent": "app.engine.harness_integration.adapters.app_event",
    "ThinkingDeltaEvent": "app.engine.harness_integration.adapters.app_event",
    "ThinkingEvent": "app.engine.harness_integration.adapters.app_event",
    "ToolCallEvent": "app.engine.harness_integration.adapters.app_event",
    "ToolCallStartEvent": "app.engine.harness_integration.adapters.app_event",
    "ToolResultEvent": "app.engine.harness_integration.adapters.app_event",
    "messages_to_app_events": "app.engine.harness_integration.adapters.messages",
    "OnEventCallback": "app.engine.harness_integration.adapters.stream_events",
    "stream_events_to_app_events": "app.engine.harness_integration.adapters.stream_events",
}


def __getattr__(name: str) -> Any:
    if name in _SYMBOLS:
        import importlib
        mod = importlib.import_module(_SYMBOLS[name])
        return getattr(mod, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
