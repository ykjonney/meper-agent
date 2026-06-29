"""Harness engine — REACT node, context compression, depth guard.

Public surface for v0.1-1:

* :func:`react_node` — the single LangGraph node (v0.1-2 full REACT loop).
* Context helpers (:func:`compress_messages`, :func:`should_compress`,
  :func:`extract_model_name`, ...) and the depth guard (:func:`check_depth`)
  are migrated utilities consumed by the REACT loop in v0.1-2.

The legacy evaluator / direct / planner executors are intentionally absent:
Story v0.1-2 collapses execution onto a single REACT node.
"""

from agent_flow_harness.engine.context import (
    compress_messages,
    estimate_message_tokens,
    estimate_messages_tokens,
    estimate_tokens,
    extract_model_name,
    get_context_window,
    get_context_window_async,
    should_compress,
)
from agent_flow_harness.engine.depth_guard import (
    MAX_DEPTH,
    DepthCheckResult,
    check_depth,
    detect_cycle,
    format_call_chain,
)
from agent_flow_harness.engine.react import react_node

__all__ = [
    "MAX_DEPTH",
    "DepthCheckResult",
    "check_depth",
    "compress_messages",
    "detect_cycle",
    "estimate_message_tokens",
    "estimate_messages_tokens",
    "estimate_tokens",
    "extract_model_name",
    "format_call_chain",
    "get_context_window",
    "get_context_window_async",
    "react_node",
    "should_compress",
]
