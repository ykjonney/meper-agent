"""HybridStrategy — 默认策略：token < threshold 不动；≥ threshold 总结+滑动。

组合 SummarizationStrategy：未超阈值直接返回，超阈值调 Summarization 总结。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from agent_flow_harness.context_engineering.base import ContextStrategy
from agent_flow_harness.context_engineering.summarization import SummarizationStrategy
from agent_flow_harness.context_engineering.token_estimator import count_tokens

if TYPE_CHECKING:
    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.messages import BaseMessage


class HybridStrategy(ContextStrategy):
    """混合策略（默认推荐）：token 超阈值时触发总结+滑动。"""

    def __init__(
        self,
        llm: "BaseChatModel",
        threshold: float = 0.7,
        window_size: int = 10,
    ) -> None:
        self._threshold = threshold
        self._summarizer = SummarizationStrategy(llm=llm)
        self._window = window_size

    @property
    def name(self) -> str:
        return "hybrid"

    async def select(
        self, messages: "list[BaseMessage]", *, max_tokens: int
    ) -> "list[BaseMessage]":
        current_tokens = count_tokens(messages)
        if current_tokens < max_tokens * self._threshold:
            return list(messages)  # 未超阈值，不动
        # 超阈值：总结 + 保留最近 window_size 条
        return await self._summarizer.select(
            messages, max_tokens=max_tokens, keep_recent=self._window
        )


__all__ = ["HybridStrategy"]
