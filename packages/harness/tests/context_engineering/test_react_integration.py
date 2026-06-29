"""react_node + ContextStrategy 集成测试（v0.2-5）。"""
from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from agent_flow_harness.context_engineering.hybrid import HybridStrategy
from agent_flow_harness.engine.react import react_node


class _FakeSummaryLLM:
    def __init__(self, response: str = "摘要内容"):
        self._response = response

    @property
    def model_name(self):
        return "fake"

    async def ainvoke(self, messages, _config=None):
        return AIMessage(content=self._response)


@pytest.mark.asyncio
async def test_react_uses_strategy_when_configured(
    base_state, fake_llm_factory, make_run_config
):
    """config 提供 context_strategy 时，react_node 用它而非默认 compress。"""
    llm = fake_llm_factory([AIMessage(content="done")])
    strategy = HybridStrategy(llm=_FakeSummaryLLM("summary"), threshold=0.5, window_size=3)
    config = make_run_config(llm)
    config["configurable"]["context_strategy"] = strategy

    result = await react_node(base_state, config)
    assert result["messages"][-1].content == "done"


@pytest.mark.asyncio
async def test_react_falls_back_without_strategy(
    base_state, fake_llm_factory, make_run_config
):
    """无 strategy 时走现有 compress_messages（向后兼容）。"""
    llm = fake_llm_factory([AIMessage(content="ok")])
    config = make_run_config(llm)
    # 不设 context_strategy
    result = await react_node(base_state, config)
    assert result["messages"][-1].content == "ok"


@pytest.mark.asyncio
async def test_react_strategy_actually_compresses(
    base_state, fake_llm_factory, make_run_config
):
    """strategy 触发压缩时，messages 变少。"""
    # 主 LLM 第一轮返回工具调用，第二轮返回最终答案
    from langchain_core.tools import tool

    @tool
    def echo(x: str) -> str:
        """Echo."""
        return x

    # 构造很长的 input 让 strategy 触发
    long_input = "x" * 5000
    llm = fake_llm_factory([
        AIMessage(content="", tool_calls=[{"name": "echo", "args": {"x": "hi"}, "id": "c1"}]),
        AIMessage(content="final"),
    ])
    strategy = HybridStrategy(llm=_FakeSummaryLLM("摘要"), threshold=0.1, window_size=2)
    config = make_run_config(llm, tools=[echo])
    config["configurable"]["context_strategy"] = strategy
    config["configurable"]["context_window"] = 1000  # 小窗口强制压缩

    base_state["messages"] = [HumanMessage(content=long_input)]
    result = await react_node(base_state, config)
    assert result["messages"][-1].content == "final"
