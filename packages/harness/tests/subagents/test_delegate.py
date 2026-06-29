"""AC4/AC6/AC10 cover: 提取最终文本 + build_subagent_state + delegate 工具。

Task 4 覆盖 extract_final_text 和 build_subagent_state；
delegate 工具本身在 Task 5 追加测试到本文件。
"""
from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from agent_flow_harness.subagents.context import SubAgentContext
from agent_flow_harness.subagents.delegate import extract_final_text
from agent_flow_harness.subagents.spec import SubAgentSpec
from agent_flow_harness.tools.registry import ToolRegistry
from agent_flow_harness.subagents.registry import SubAgentRegistry


def _spec() -> SubAgentSpec:
    return SubAgentSpec(
        name="coder", description="coder sub", system_prompt="你是编码助手", tools=[]
    )


def _make_context() -> SubAgentContext:
    return SubAgentContext(
        registry=SubAgentRegistry(),
        tool_registry=ToolRegistry(),
        build_llm=lambda cfg: object(),
        parent_llm=None,
    )


# --- extract_final_text ---

def test_extract_final_text_str_content():
    """最后一条 AIMessage content 是 str → 直接返回。"""
    msgs = [HumanMessage(content="task"), AIMessage(content="final answer")]
    assert extract_final_text(msgs) == "final answer"


def test_extract_final_text_list_content():
    """content 是 list[dict] → 拼接 text 字段。"""
    msgs = [
        HumanMessage(content="task"),
        AIMessage(content=[{"type": "text", "text": "part1"}, {"type": "text", "text": "part2"}]),
    ]
    result = extract_final_text(msgs)
    assert "part1" in result
    assert "part2" in result


def test_extract_final_text_no_ai_message():
    """没有 AIMessage → 返回兜底字符串。"""
    msgs = [HumanMessage(content="task")]
    assert "No response" in extract_final_text(msgs)


def test_extract_final_text_empty_messages():
    assert isinstance(extract_final_text([]), str)


def test_extract_final_text_picks_last_ai_message():
    """多条 AIMessage → 取最后一条。"""
    msgs = [
        HumanMessage(content="task"),
        AIMessage(content="first"),
        AIMessage(content="second"),
    ]
    assert extract_final_text(msgs) == "second"


# --- build_subagent_state ---

def test_build_subagent_state_isolation():
    """AC8: 子 Agent state 全新——只有 system_prompt + task，无主 agent 历史。"""
    ctx = _make_context()
    spec = _spec()
    state = ctx.build_subagent_state(spec, "do something")
    msgs = state["messages"]
    # 第一条是 system_prompt，最后一条是 task
    assert isinstance(msgs[0], SystemMessage)
    assert msgs[0].content == "你是编码助手"
    assert isinstance(msgs[-1], HumanMessage)
    assert msgs[-1].content == "do something"
    # 只有 2 条——没有主 agent 的历史
    assert len(msgs) == 2


# --- delegate_to_subagent 工具 (Task 5) ---

from unittest.mock import MagicMock  # noqa: E402

from agent_flow_harness.subagents.context import (  # noqa: E402
    reset_subagent_context,
    set_subagent_context,
)
from agent_flow_harness.subagents.delegate import delegate_to_subagent  # noqa: E402


def _setup_context_with_mock_subagent(final_text: str = "subagent result"):
    """构建一个 ctx，run_subagent 返回固定文本（mock 掉 graph 执行）。

    因为 SubAgentContext 没有 run_subagent 方法（delegate 工具内部直接调
    build_agent_graph），这里改用 mock patch build_agent_graph 的方式。
    但为简化，Task5 的单测直接 patch context 的各步骤 + 验证异常隔离。
    """
    ctx = MagicMock()
    ctx.registry.get = MagicMock(return_value=_spec())
    ctx.resolve_tools = MagicMock(return_value=[])
    ctx.build_subagent_state = MagicMock(return_value={"messages": []})
    ctx.resolve_llm = MagicMock(return_value=object())
    return ctx


@pytest.mark.asyncio
async def test_delegate_returns_subagent_final_text(monkeypatch):
    """AC4: delegate 工具返回子 Agent 最终输出字符串。"""
    ctx = _setup_context_with_mock_subagent()
    # mock build_agent_graph 返回一个假 graph，ainvoke 返回带 AIMessage 的 state
    async def _fake_ainvoke(state, config=None):
        return {"messages": [AIMessage(content="the answer is 42")]}
    fake_graph = MagicMock()
    fake_graph.ainvoke = _fake_ainvoke
    monkeypatch.setattr(
        "agent_flow_harness.subagents.delegate.build_agent_graph",
        lambda agent_doc, **kw: fake_graph,
    )
    monkeypatch.setattr(
        "agent_flow_harness.subagents.delegate.build_config",
        lambda *a, **kw: {"configurable": {}},
    )
    token = set_subagent_context(ctx)
    try:
        result = await delegate_to_subagent.ainvoke(
            {"subagent_name": "coder", "task": "compute"}
        )
        assert "42" in result
        ctx.registry.get.assert_called_once_with("coder")
    finally:
        reset_subagent_context(token)


@pytest.mark.asyncio
async def test_delegate_unknown_subagent_returns_error_string():
    """AC10: 未知子 Agent → 返回错误字符串，不 raise。"""
    ctx = MagicMock()
    ctx.registry.get = MagicMock(side_effect=KeyError("not found"))
    token = set_subagent_context(ctx)
    try:
        result = await delegate_to_subagent.ainvoke(
            {"subagent_name": "ghost", "task": "x"}
        )
        assert "Error" in result or "ghost" in result
    finally:
        reset_subagent_context(token)


@pytest.mark.asyncio
async def test_delegate_subagent_exception_isolated(monkeypatch):
    """AC10: 子 Agent 执行抛异常 → 返回错误字符串，不中断。"""
    ctx = _setup_context_with_mock_subagent()
    async def _boom_ainvoke(state, config=None):
        raise RuntimeError("LLM down")
    fake_graph = MagicMock()
    fake_graph.ainvoke = _boom_ainvoke
    monkeypatch.setattr(
        "agent_flow_harness.subagents.delegate.build_agent_graph",
        lambda agent_doc, **kw: fake_graph,
    )
    monkeypatch.setattr(
        "agent_flow_harness.subagents.delegate.build_config",
        lambda *a, **kw: {"configurable": {}},
    )
    token = set_subagent_context(ctx)
    try:
        result = await delegate_to_subagent.ainvoke(
            {"subagent_name": "coder", "task": "x"}
        )
        assert "Error" in result
    finally:
        reset_subagent_context(token)


def test_delegate_tool_is_structured_tool():
    """delegate_to_subagent 是一个可注册的 StructuredTool/BaseTool。"""
    from langchain_core.tools import BaseTool
    assert isinstance(delegate_to_subagent, BaseTool)
    assert delegate_to_subagent.name == "delegate_to_subagent"
