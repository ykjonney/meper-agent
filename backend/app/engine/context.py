"""Conversation context compression (placeholder).

Real compression (sliding window / summarization) added in Story 3.5.
"""
from loguru import logger


def compress_context(messages: list, max_tokens: int = 4000) -> list:
    """Compress a conversation history to fit a token budget (placeholder)."""
    logger.warning("compress_context is a placeholder; implement in Story 3.5")
    return messages
