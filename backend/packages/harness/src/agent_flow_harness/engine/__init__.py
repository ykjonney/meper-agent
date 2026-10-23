"""Harness engine — context utilities and depth guard.

* Context helpers (:func:`estimate_tokens`, :func:`extract_model_name`, ...)
  consumed by the graph nodes.
* The depth guard (:func:`check_depth`).
"""

from agent_flow_harness.engine.context import (
    estimate_message_tokens,
    estimate_messages_tokens,
    estimate_tokens,
    extract_model_name,
    get_context_window,
)
from agent_flow_harness.engine.depth_guard import (
    MAX_DEPTH,
    DepthCheckResult,
    check_depth,
    detect_cycle,
    format_call_chain,
)
__all__ = [
    "MAX_DEPTH",
    "DepthCheckResult",
    "check_depth",
    "detect_cycle",
    "estimate_message_tokens",
    "estimate_messages_tokens",
    "estimate_tokens",
    "extract_model_name",
    "format_call_chain",
    "get_context_window",
]
