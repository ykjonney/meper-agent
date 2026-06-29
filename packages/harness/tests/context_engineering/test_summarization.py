"""SummarizationStrategy 测试。"""
from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from agent_flow_harness.context_engineering.summarization import SummarizationStrategy


class _FakeLLM:
    def __init__(self, response: str = "这是摘要"):
        self._response = response

    @property
    def model_name(self):
        return "fake"

    async def ainvoke(self, messages, _config=None):
        return AIMessage(content=self._response)


@pytest.mark.asyncio
async def test_summarizes_old_messages():
    strategy = SummarizationStrategy(llm=_FakeLLM("早期对话讨论了项目架构"))
    msgs = [HumanMessage(content="hi"), AIMessage(content="hello")] * 10
    msgs += [HumanMessage(content="recent")]
    # max_tokens=10 强制触发总结（21 条 ~25 tokens > 10）
    result = await strategy.select(msgs, max_tokens=10, keep_recent=2)
    assert isinstance(result[0], SystemMessage)
    assert "架构" in result[0].content


@pytest.mark.asyncio
async def test_no_summary_when_small():
    strategy = SummarizationStrategy(llm=_FakeLLM())
    msgs = [HumanMessage(content="hi")]
    result = await strategy.select(msgs, max_tokens=999999, keep_recent=5)
    assert len(result) == 1


@pytest.mark.asyncio
async def test_name():
    s = SummarizationStrategy(llm=_FakeLLM())
    assert s.name == "summarization"


@pytest.mark.asyncio
async def test_keeps_recent_verbatim():
    strategy = SummarizationStrategy(llm=_FakeLLM("摘要"))
    msgs = [HumanMessage(content="old")] * 15 + [
        HumanMessage(content="recent1"),
        AIMessage(content="recent2"),
    ]
    result = await strategy.select(msgs, max_tokens=999999, keep_recent=2)
    # 最近 2 条原样保留
    contents = [m.content for m in result]
    assert "recent1" in contents
    assert "recent2" in contents


@pytest.mark.asyncio
async def test_summary_replaces_old():
    """总结后旧消息被摘要替换（数量变少）。"""
    strategy = SummarizationStrategy(llm=_FakeLLM("摘要"))
    msgs = [HumanMessage(content="x")] * 20
    # max_tokens=10 强制触发（20条 ~20 tokens > 10）
    result = await strategy.select(msgs, max_tokens=10, keep_recent=3)
    assert len(result) == 4  # 1 摘要 + 3 recent
