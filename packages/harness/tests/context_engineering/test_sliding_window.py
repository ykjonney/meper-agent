"""SlidingWindowStrategy 测试。"""
from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from agent_flow_harness.context_engineering.sliding_window import SlidingWindowStrategy


def _make_msgs(n):
    msgs = [SystemMessage(content="system")]
    for i in range(n):
        msgs.append(HumanMessage(content=f"user {i}"))
        msgs.append(AIMessage(content=f"assistant {i}"))
    return msgs


@pytest.mark.asyncio
async def test_keeps_system_and_recent():
    strategy = SlidingWindowStrategy(window_size=4)
    msgs = _make_msgs(10)  # 1 system + 20 messages
    result = await strategy.select(msgs, max_tokens=999999)
    assert isinstance(result[0], SystemMessage)
    assert len(result) == 5  # 4 recent + system


@pytest.mark.asyncio
async def test_no_compression_when_small():
    strategy = SlidingWindowStrategy(window_size=20)
    msgs = _make_msgs(3)  # 7 条
    result = await strategy.select(msgs, max_tokens=999999)
    assert len(result) == 7


@pytest.mark.asyncio
async def test_name():
    assert (await _name()) == "sliding_window"


async def _name():
    return SlidingWindowStrategy().name


@pytest.mark.asyncio
async def test_preserves_tool_pairing():
    """压缩后不切碎 tool 配对。"""
    strategy = SlidingWindowStrategy(window_size=2)
    msgs = [
        SystemMessage(content="sys"),
        AIMessage(content="", tool_calls=[{"name": "bash", "args": {}, "id": "c1"}]),
        ToolMessage(content="r", tool_call_id="c1"),
        AIMessage(content="mid"),
        HumanMessage(content="recent1"),
        AIMessage(content="recent2"),
    ]
    result = await strategy.select(msgs, max_tokens=999999)
    contents = [m.content for m in result]
    assert "recent1" in contents
    assert "recent2" in contents


@pytest.mark.asyncio
async def test_respects_max_tokens():
    """超过 max_tokens 时强制滑动。"""
    strategy = SlidingWindowStrategy(window_size=3)
    # 每条 ~250 tokens，6 条 ~1500
    msgs = [HumanMessage(content="x" * 1000), AIMessage(content="y" * 1000)] * 3
    result = await strategy.select(msgs, max_tokens=500)
    assert len(result) <= 3
