"""HybridStrategy 测试。"""
from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from agent_flow_harness.context_engineering.hybrid import HybridStrategy


class _FakeLLM:
    def __init__(self, response: str = "摘要内容"):
        self._response = response

    @property
    def model_name(self):
        return "fake"

    async def ainvoke(self, messages, _config=None):
        return AIMessage(content=self._response)


def _big_msgs():
    """制造超 token 的 messages（每条 ~250 tokens）。"""
    return [HumanMessage(content="x" * 1000), AIMessage(content="y" * 1000)] * 5


@pytest.mark.asyncio
async def test_no_compression_under_threshold():
    strategy = HybridStrategy(llm=_FakeLLM(), threshold=0.7)
    msgs = [HumanMessage(content="hi")]
    result = await strategy.select(msgs, max_tokens=100000)
    assert len(result) == 1


@pytest.mark.asyncio
async def test_compresses_over_threshold():
    # window_size=3 避免触发 summarization 的 keep_recent 早退
    strategy = HybridStrategy(llm=_FakeLLM("摘要"), threshold=0.5, window_size=3)
    msgs = _big_msgs()  # ~5000 tokens, 10 条
    result = await strategy.select(msgs, max_tokens=1000)  # 50% = 500
    assert len(result) < len(msgs)


@pytest.mark.asyncio
async def test_name():
    strategy = HybridStrategy(llm=_FakeLLM())
    assert strategy.name == "hybrid"


@pytest.mark.asyncio
async def test_threshold_boundary():
    """正好等于阈值不压缩（< 而非 <=）。"""
    strategy = HybridStrategy(llm=_FakeLLM(), threshold=0.5)
    # 构造正好 50% 的 messages：max_tokens=1000，阈值=500
    msgs = [HumanMessage(content="x" * 1996)]  # ~499 tokens
    result = await strategy.select(msgs, max_tokens=1000)
    assert len(result) == 1  # 未超 500，不压缩
