"""Conversation context utilities.

Provides utilities for:
- Estimating token counts for message lists (CJK-corrected, usage-aware)
- Looking up a model's context-window size
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage

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

_DEFAULT_MAX_TOKENS = 128000


# ---------------------------------------------------------------------------
# Token estimation (lightweight, no external tokenizer dependency)
# ---------------------------------------------------------------------------


# CJK 字符区段(汉字 + 全角标点 + 假名/谚文兼容区):这些字符在主流
# tokenizer 下约 0.6~1.0 token/字,而 len//4 的 0.25 token/字会低估 2~4 倍,
# 导致中文会话的压缩阈值判断系统性偏晚(真实 token 早已逼近窗口,账面
# 却显示安全)。取 0.75 token/字作中间偏保守值——宁可稍早压缩,不可迟到。
_CJK_RE = re.compile(r"[\u3000-\u303f\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff00-\uffef]")


def estimate_tokens(text: str) -> int:
    """Estimate token count for a string.

    Lightweight heuristic without a tokenizer dependency: ASCII content uses
    ~4 chars/token; CJK characters (Chinese text, full-width punctuation)
    count 0.75 token each — plain ``len//4`` underestimates Chinese 2-4×,
    which historically delayed compression decisions until the real prompt
    had already exceeded the model window.
    """
    if not text:
        return 0
    if text.isascii():
        return max(1, len(text) // 4)
    cjk = len(_CJK_RE.findall(text))
    other = len(text) - cjk
    return max(1, int(cjk * 0.75 + other * 0.25))


# Rough per-image vision-token estimate used when a message carries multimodal
# image blocks. Providers charge by tiles/resolution (roughly 700-3000 tokens
# for a ~2K-edge image); a mid value keeps compression decisions sane without
# counting the base64 payload (which would inflate estimates ~100×).
_IMAGE_BLOCK_TOKEN_ESTIMATE = 1200


def _estimate_block_content_tokens(content: Any) -> int:
    """Estimate tokens for a multimodal (list-of-blocks) content.

    Text blocks count normally; image blocks count as a fixed per-image
    estimate (base64 payload itself is never counted); unknown block types
    fall back to their string repr (e.g. audio/file blocks carry small refs).
    """
    tokens = 0
    for block in content:
        if isinstance(block, dict):
            btype = block.get("type", "")
            if btype == "text":
                tokens += estimate_tokens(str(block.get("text", "")))
            elif btype == "image_url":
                tokens += _IMAGE_BLOCK_TOKEN_ESTIMATE
            else:
                tokens += estimate_tokens(str(block))
        else:
            tokens += estimate_tokens(str(block))
    return tokens


def estimate_message_tokens(message: BaseMessage | dict[str, Any]) -> int:
    """Estimate token count for a single message (LangChain or dict).

    Multimodal list content goes through :func:`_estimate_block_content_tokens`
    — image blocks are estimated per-image instead of by base64 length, so
    vision messages don't blow past the oversized-tool-result guard.
    """
    if isinstance(message, dict):
        content = message.get("content", "")
    else:
        content = message.content
    if isinstance(content, list):
        tokens = _estimate_block_content_tokens(content)
    else:
        tokens = estimate_tokens(str(content))
    tokens += 4  # approximate metadata overhead (role, etc.)
    return tokens


def estimate_messages_tokens(
    messages: Sequence[BaseMessage | dict[str, Any]],
) -> int:
    """Estimate total token count for a list of messages."""
    return sum(estimate_message_tokens(m) for m in messages)


def estimate_context_tokens(messages: Sequence[Any], *, prefer_usage: bool = True) -> int:
    """Estimate the current context size using the model's real token count.

    Prefers the ``input_tokens`` recorded on the **last** AIMessage's
    ``usage_metadata`` — this is the exact token count the model provider
    computed for its last invocation (far more accurate than ``len//4``,
    especially for Chinese text). Messages appended *after* that AIMessage
    (new tool results / user input) are estimated with ``len//4``.

    Falls back to full ``estimate_messages_tokens`` when there is no AIMessage
    yet (first turn), when ``usage_metadata`` is missing, or when
    ``prefer_usage=False`` — the usage base describes the prompt of a past
    invocation, so it is only valid while the messages preceding (and
    including) that AIMessage are unchanged. Compression replaces/trims
    history in place; callers must pass ``prefer_usage=False`` for lists
    produced by compression, otherwise the stale (larger) base keeps
    inflating every subsequent budget check until the next real call.
    """
    from langchain_core.messages import AIMessage

    # Find the last AIMessage with usage_metadata.
    last_ai_idx = -1
    base_input_tokens = 0
    if prefer_usage:
        for i in range(len(messages) - 1, -1, -1):
            m = messages[i]
            if isinstance(m, AIMessage):
                um = getattr(m, "usage_metadata", None)
                if isinstance(um, dict) and um.get("input_tokens"):
                    last_ai_idx = i
                    base_input_tokens = int(um["input_tokens"])
                break

    if last_ai_idx < 0:
        # No usable AIMessage usage (or invalidated by compression)
        # → full estimate.
        return estimate_messages_tokens(messages)

    # Tokens for messages after the last AIMessage (new additions).
    new_tokens = sum(estimate_message_tokens(m) for m in messages[last_ai_idx + 1:])
    return base_input_tokens + new_tokens


# ---------------------------------------------------------------------------
# Context window helpers
# ---------------------------------------------------------------------------


def get_context_window(model: str) -> int:
    """Return the context window size for a given model name.

    Uses the hardcoded ``_CONTEXT_WINDOWS`` table.
    """
    for prefix, window in _CONTEXT_WINDOWS.items():
        if model.startswith(prefix):
            return window
    return _DEFAULT_MAX_TOKENS


def extract_model_name(llm: BaseChatModel) -> str:
    """Extract the model name from a LangChain chat model instance."""
    model: str = getattr(llm, "model_name", None) or getattr(llm, "model", "") or ""
    return model
