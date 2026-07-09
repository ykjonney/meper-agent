"""astream_events → application-layer event adapter.

Public surface:

* :func:`stream_events_to_app_events` — translate a native ``astream_events``
  stream into the eight application-layer events the frontend consumes.
* :data:`AppEvent` and the eight event model classes (see
  :mod:`agent_flow_harness.adapters.app_event`).
"""

from agent_flow_harness.adapters.app_event import (
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
from agent_flow_harness.adapters.messages import messages_to_app_events
from agent_flow_harness.adapters.stream_events import (
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
