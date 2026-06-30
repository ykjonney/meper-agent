"""ContextStrategy — 可插拔上下文压缩策略协议。

react_node 在 LLM 调用前调 strategy.select() 压缩 messages。
无 strategy 时走 v0.1 的 compress_messages（向后兼容）。

select 是 async，因为 SummarizationStrategy 要调 LLM。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langchain_core.messages import BaseMessage


class ContextStrategy(ABC):
    """可插拔上下文压缩策略。"""

    @property
    @abstractmethod
    def name(self) -> str:
        """策略名（日志/事件用）。"""
        ...

    @abstractmethod
    async def select(
        self, messages: "list[BaseMessage]", *, max_tokens: int
    ) -> "list[BaseMessage]":
        """压缩/选择 messages，返回不超 max_tokens 的列表。

        必须保证 ToolMessage 配对完整（tool_call 有对应 tool_result）。
        """
        ...


__all__ = ["ContextStrategy"]
