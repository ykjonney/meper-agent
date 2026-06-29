"""token 估算器 — 复用 engine/context.py 的 estimate_messages_tokens。"""
from __future__ import annotations

from typing import TYPE_CHECKING, Sequence

if TYPE_CHECKING:
    from langchain_core.messages import BaseMessage

from agent_flow_harness.engine.context import estimate_messages_tokens


def count_tokens(messages_or_text: "Sequence[BaseMessage] | str") -> int:
    """估算 messages 列表或单段文本的 token 数。

    复用 engine/context.py 的 4字符≈1token 启发式，避免 tiktoken 依赖。
    """
    if isinstance(messages_or_text, str):
        return max(1, len(messages_or_text) // 4)
    return estimate_messages_tokens(messages_or_text)


__all__ = ["count_tokens"]
