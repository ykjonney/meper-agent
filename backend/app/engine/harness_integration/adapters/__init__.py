"""Application-layer event adapter — translates harness/LangGraph events
into the business events the frontend SSE client consumes.

Moved from ``agent_flow_harness.adapters`` to the application layer so
that the harness package stays a pure engine without app-specific
event schemas.
"""

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
