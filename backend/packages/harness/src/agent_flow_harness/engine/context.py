"""Conversation context management and compression.

Provides utilities for:
- Estimating token counts for message lists
- Compressing conversation history when approaching context window limits
- Looking up a model's context-window size

Integrated into the REACT loop so the LLM never exceeds its context
window during multi-step reasoning or long conversations.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
import structlog

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Default model context windows (tokens)
# ---------------------------------------------------------------------------

_CONTEXT_WINDOWS: dict[str, int] = {
    "gpt-4o": 128000,
    "gpt-4o-mini": 128000,
    "gpt-4": 8192,
    "gpt-3.5-turbo": 16384,
    "claude-3-5-sonnet": 200000,
    "claude-3-haiku": 200000,
    "claude-opus-4": 200000,
    "claude-sonnet-4": 200000,
    "claude-4": 200000,
}

# Default compression settings
_DEFAULT_MAX_TOKENS = 128000
_DEFAULT_RESERVED_TOKENS = 4000  # Reserve space for the LLM response
_DEFAULT_COMPRESSION_THRESHOLD = 0.7  # Trigger at 70 % of limit
_DEFAULT_KEEP_MESSAGES = 10  # Keep this many most recent messages verbatim
_MAX_COMPRESS_DEPTH = 5  # Limit recursion depth to prevent infinite loops


# ---------------------------------------------------------------------------
# Token estimation (lightweight, no external tokenizer dependency)
# ---------------------------------------------------------------------------


def estimate_tokens(text: str) -> int:
    """Estimate token count for a string.

    Uses ~4 characters per token as a rough heuristic.  Works reasonably
    well for mixed Chinese/English content without pulling in a tokenizer
    library.
    """
    return max(1, len(text) // 4)


def estimate_message_tokens(message: BaseMessage | dict[str, Any]) -> int:
    """Estimate token count for a single message (LangChain or dict)."""
    if isinstance(message, dict):
        content = str(message.get("content", ""))
    else:
        content = str(message.content)
    tokens = estimate_tokens(content)
    tokens += 4  # approximate metadata overhead (role, etc.)
    return tokens


def estimate_messages_tokens(
    messages: Sequence[BaseMessage | dict[str, Any]],
) -> int:
    """Estimate total token count for a list of messages."""
    return sum(estimate_message_tokens(m) for m in messages)


# ---------------------------------------------------------------------------
# Context window helpers
# ---------------------------------------------------------------------------


def get_context_window(model: str) -> int:
    """Return the context window size for a given model name.

    Uses the hardcoded ``_CONTEXT_WINDOWS`` table.  For ``model_``
    (ULID) references, pass a pre-resolved window via
    :func:`get_context_window_async`'s ``model_window`` parameter.
    """
    for prefix, window in _CONTEXT_WINDOWS.items():
        if model.startswith(prefix):
            return window
    return _DEFAULT_MAX_TOKENS


async def get_context_window_async(
    model_ref: str,
    *,
    model_window: int | None = None,
) -> int:
    """Return the context window for ``model_ref``.

    The harness has no database access.  When the host application has
    already resolved the model document (e.g. by looking up the models
    collection), it can pass the window via ``model_window`` and the
    lookup is a simple return.

    Otherwise the hardcoded ``_CONTEXT_WINDOWS`` table is consulted.
    """
    if model_window is not None:
        return int(model_window)
    return get_context_window(model_ref)


def extract_model_name(llm: BaseChatModel) -> str:
    """Extract the model name from a LangChain chat model instance."""
    model: str = getattr(llm, "model_name", None) or getattr(llm, "model", "") or ""
    return model


# ---------------------------------------------------------------------------
# Compression
# ---------------------------------------------------------------------------


def should_compress(
    messages: list[BaseMessage],
    model: str,
    threshold: float = _DEFAULT_COMPRESSION_THRESHOLD,
    reserved_tokens: int = _DEFAULT_RESERVED_TOKENS,
    context_window: int | None = None,
) -> bool:
    """Check whether the message list exceeds the compression threshold.

    Args:
        messages: Full message list to evaluate.
        model: Model name (used to look up context window).
        threshold: Fraction of context window that triggers compression.
        reserved_tokens: Tokens to reserve for the LLM response.
        context_window: Optional override for context window size.
            When provided, used instead of the hardcoded table lookup.

    Returns:
        True if compression should be applied.
    """
    if context_window is not None:
        max_tokens = context_window - reserved_tokens
    else:
        max_tokens = get_context_window(model) - reserved_tokens
    estimated = estimate_messages_tokens(messages)
    return estimated > max_tokens * threshold


def compress_messages(
    messages: list[BaseMessage],
    model: str = "gpt-4o-mini",
    keep_last: int = _DEFAULT_KEEP_MESSAGES,
    _depth: int = 0,
    context_window: int | None = None,
) -> list[BaseMessage]:
    """Compress conversation history when approaching context window limits.

    Strategy:
    1. Keep the most recent ``keep_last`` messages verbatim.
    2. Compress older messages into a single ``SystemMessage`` summary.
    3. If the compressed result is still too large, recurse with a
       smaller ``keep_last``.

    Args:
        messages: Full message list to compress.
        model: Model name for context window lookup.
        keep_last: Number of most recent messages to preserve verbatim.
        _depth: Internal recursion depth counter.
        context_window: Optional override for context window size.

    Returns:
        Compressed (usually shorter) message list.
    """
    if not should_compress(messages, model, context_window=context_window):
        return list(messages)

    if len(messages) <= keep_last:
        return list(messages)

    if _depth >= _MAX_COMPRESS_DEPTH:
        logger.warning("context_max_depth_reached", depth=_depth)
        # Force-trim: keep only the most recent messages
        return list(messages[-keep_last:])

    # Split: older messages to compress, recent messages to keep
    to_compress = messages[:-keep_last]
    recent = messages[-keep_last:]

    # Build a summary from the older messages
    summary = _build_summary(to_compress)
    compressed: list[BaseMessage] = [
        SystemMessage(content=f"[对话历史摘要]\n{summary}"),
        *recent,
    ]

    # Recurse if still over threshold
    if should_compress(compressed, model, context_window=context_window):
        logger.info("context_recursive_compress", keep_last=keep_last)
        # Reduce keep_last by at least 1 each recursion to guarantee progress
        next_keep = max(keep_last - 1, 1)
        return compress_messages(
            compressed, model, next_keep, _depth=_depth + 1,
            context_window=context_window,
        )

    logger.info(
        "context_compressed",
        original=len(messages),
        compressed=len(compressed),
    )
    return compressed


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_summary(messages: list[BaseMessage]) -> str:
    """Build a compact text summary from a list of messages.

    Extracts role + content for each message.  Long messages are
    truncated to keep the summary itself concise.
    """
    parts: list[str] = []
    for m in messages:
        role = _get_role_label(m)
        content = _get_content_preview(m)
        # Truncate each entry to 300 chars max so the summary
        # itself doesn't blow up the context window
        if len(content) > 300:
            content = content[:300] + "..."
        parts.append(f"[{role}] {content}")
    return "\n".join(parts)


def _get_role_label(message: BaseMessage | dict[str, Any]) -> str:
    """Return a human-readable role label."""
    if isinstance(message, dict):
        role_map = {
            "user": "用户",
            "assistant": "助手",
            "tool": "工具结果",
            "system": "系统",
        }
        return role_map.get(message.get("role", ""), "未知")
    if isinstance(message, HumanMessage):
        return "用户"
    if isinstance(message, AIMessage):
        return "助手"
    if isinstance(message, ToolMessage):
        return "工具结果"
    if isinstance(message, SystemMessage):
        return "系统"
    return "未知"


def _get_content_preview(message: BaseMessage | dict[str, Any]) -> str:
    """Extract content text, truncating long tool results."""
    if isinstance(message, dict):
        content = str(message.get("content", ""))
        role = message.get("role", "")
    else:
        content = str(message.content)
        role = "tool" if isinstance(message, ToolMessage) else ""

    if role == "tool" and len(content) > 200:
        return content[:200] + "..."
    return content
