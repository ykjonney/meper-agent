"""AC4/AC6/AC10 cover: 提取最终文本 + build_subagent_state + delegate 工具。

Task 4 覆盖 extract_final_text 和 build_subagent_state；
delegate 工具本身在 Task 5 追加测试到本文件。
"""
from __future__ import annotations

import asyncio
import time

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
async def test_delegate_tags_subagent_config(monkeypatch):
    """子图 config 必须带 subagent tag：嵌套事件冒泡进父图 astream_events 时，
    app 层适配器按此 tag 过滤（游离 text/thinking / 无法配对的 tool_result）。"""
    ctx = _setup_context_with_mock_subagent()
    captured: dict = {}

    async def _fake_ainvoke(state, config=None):
        captured["config"] = config
        return {"messages": [AIMessage(content="ok")]}

    fake_graph = MagicMock()
    fake_graph.ainvoke = _fake_ainvoke
    monkeypatch.setattr(
        "agent_flow_harness.subagents.delegate.build_agent_graph",
        lambda agent_doc, **kw: fake_graph,
    )
    monkeypatch.setattr(
        "agent_flow_harness.subagents.delegate.build_config",
        lambda *a, **kw: {"configurable": {}, "tags": ["keep"]},
    )
    token = set_subagent_context(ctx)
    try:
        await delegate_to_subagent.ainvoke(
            {"subagent_name": "coder", "task": "compute"}
        )
        tags = captured["config"].get("tags")
        assert "subagent" in tags  # 注入过滤标记
        assert "keep" in tags       # 原有 tag 不丢失
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


# --- usage 冒泡 + timeout (M1) ---


@pytest.mark.asyncio
async def test_delegate_accumulates_subagent_usage(monkeypatch):
    """委派完成后把子图 UsageMiddleware.summary 累加进 ctx.usage_totals
    （账本冒泡——子图 token 消耗必须回收到父级，否则账本有缺口）。"""
    ctx = _setup_context_with_mock_subagent()

    async def _fake_ainvoke(state, config=None):
        return {"messages": [AIMessage(content="ok")]}

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
        await delegate_to_subagent.ainvoke(
            {"subagent_name": "coder", "task": "compute"}
        )
        ctx.accumulate_usage.assert_called_once()
    finally:
        reset_subagent_context(token)


@pytest.mark.asyncio
async def test_delegate_times_out_honestly(monkeypatch):
    """超时按 spec.timeout_ms wall-clock 控制：诚实返回错误字符串，
    不阻塞父 REACT 循环（同步委派的已知瓶颈治理）。"""
    spec = SubAgentSpec(
        name="slow", description="slow sub", system_prompt="x",
        tools=[], timeout_ms=1_000,  # pydantic 下限 1s
    )
    ctx = _setup_context_with_mock_subagent()
    ctx.registry.get = MagicMock(return_value=spec)

    async def _slow_ainvoke(state, config=None):
        await asyncio.sleep(2.0)
        return {"messages": [AIMessage(content="late")]}

    fake_graph = MagicMock()
    fake_graph.ainvoke = _slow_ainvoke
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
        started = time.monotonic()
        result = await delegate_to_subagent.ainvoke(
            {"subagent_name": "slow", "task": "x"}
        )
        elapsed = time.monotonic() - started
        assert "timed out" in result
        assert elapsed < 1.8  # 1s 超时生效，而非等满 2s
    finally:
        reset_subagent_context(token)


def test_spec_timeout_validation():
    """timeout_ms 默认 120s；下限 1s（ge=1000）。"""
    assert SubAgentSpec(
        name="a", description="d", system_prompt="s",
    ).timeout_ms == 120_000
    with pytest.raises(Exception):
        SubAgentSpec(
            name="a", description="d", system_prompt="s", timeout_ms=500,
        )


@pytest.mark.asyncio
async def test_delegate_passes_tools_to_graph_builder(monkeypatch):
    """回归锁：tools 必须传 build_agent_graph——ToolNode 执行表在编译期
    决定（config 的 tools 只供 llm bind），不传则子 agent 所有工具调用
    报 "not a valid tool, try one of []"。"""
    ctx = _setup_context_with_mock_subagent()
    captured: dict = {}

    def _capture_build(agent_doc, **kw):
        captured["tools"] = kw.get("tools")
        fake_graph = MagicMock()

        async def _ok(state, config=None):
            return {"messages": [AIMessage(content="ok")]}

        fake_graph.ainvoke = _ok
        return fake_graph

    monkeypatch.setattr(
        "agent_flow_harness.subagents.delegate.build_agent_graph",
        _capture_build,
    )
    monkeypatch.setattr(
        "agent_flow_harness.subagents.delegate.build_config",
        lambda *a, **kw: {"configurable": {}},
    )
    token = set_subagent_context(ctx)
    try:
        await delegate_to_subagent.ainvoke(
            {"subagent_name": "coder", "task": "x"}
        )
        # resolve_tools 的结果（ctx.resolve_tools 的返回值）必须原样进入图构建
        assert captured["tools"] == ctx.resolve_tools.return_value
    finally:
        reset_subagent_context(token)


# --- 委派 trace（M2.1 委派可观测：ok/timeout/error 全路径留痕） ---


def _real_ctx() -> SubAgentContext:
    """真 SubAgentContext（ MagicMock 无法验证 record_delegation 行为）。"""
    from agent_flow_harness.tools.registry import ToolRegistry

    ctx = SubAgentContext(
        registry=SubAgentRegistry(),
        tool_registry=ToolRegistry(),
        build_llm=lambda cfg: object(),
        parent_llm=object(),  # spec 默认 model='inherit' 需要父 LLM
    )
    ctx.registry.register(_spec())
    return ctx


@pytest.mark.asyncio
async def test_delegation_trace_ok_path(monkeypatch):
    """ok 路径：trace 含子 agent 名/task/轮次摘要（从终态 messages 提取）。"""
    ctx = _real_ctx()

    async def _fake_ainvoke(state, config=None):
        return {"messages": [
            __import__("langchain_core.messages", fromlist=["AIMessage"]).AIMessage(
                content="", tool_calls=[{"name": "kb_search", "args": {"q": "x"}, "id": "t1"}],
            ),
            __import__("langchain_core.messages", fromlist=["ToolMessage"]).ToolMessage(
                content="找到3条", tool_call_id="t1", name="kb_search",
            ),
            AIMessage(content="done"),
        ]}

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
            {"subagent_name": "coder", "task": "do research"}
        )
        assert "done" in result
        assert len(ctx.delegation_traces) == 1
        tr = ctx.delegation_traces[0]
        assert tr["subagent"] == "coder"
        assert tr["task"] == "do research"
        assert tr["status"] == "ok"
        kinds = [r["t"] for r in tr["rounds"]]
        assert "tool_call" in kinds and "tool_result" in kinds and "llm" in kinds
        assert tr["duration_ms"] >= 0
    finally:
        reset_subagent_context(token)


@pytest.mark.asyncio
async def test_delegation_trace_timeout_path(monkeypatch):
    """timeout 路径：messages 不可达 → rounds 空，但 status/task 留痕。"""
    import asyncio as _asyncio

    ctx = _real_ctx()
    spec = SubAgentSpec(name="coder", description="d", system_prompt="s", timeout_ms=1_000)
    ctx.registry = SubAgentRegistry()
    ctx.registry.register(spec)

    async def _slow(state, config=None):
        await _asyncio.sleep(2.0)
        return {"messages": []}

    fake_graph = MagicMock()
    fake_graph.ainvoke = _slow
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
        assert "timed out" in result
        tr = ctx.delegation_traces[0]
        assert tr["status"] == "timeout"
        assert tr["rounds"] == []
        assert "timed out" in tr["error"]
    finally:
        reset_subagent_context(token)


@pytest.mark.asyncio
async def test_delegation_trace_error_path():
    """error 路径（如未知子 agent）：ctx 未建立也必须不崩（trace 无处提交，
    静默跳过——主流程返回错误字符串）。"""
    broken = MagicMock()
    broken.registry.get = MagicMock(side_effect=KeyError("ghost"))
    token = set_subagent_context(broken)
    try:
        result = await delegate_to_subagent.ainvoke(
            {"subagent_name": "ghost", "task": "x"}
        )
        assert "Error" in result
    finally:
        reset_subagent_context(token)


def test_delegation_traces_cap():
    """traces 封顶丢最旧（防失控委派撑爆内存/落库 payload）。"""
    ctx = _real_ctx()
    for i in range(ctx._DELEGATION_TRACES_CAP + 20):
        ctx.record_delegation({"subagent": f"a{i}", "task": "t", "status": "ok"})
    assert len(ctx.delegation_traces) == ctx._DELEGATION_TRACES_CAP
    assert ctx.delegation_traces[0]["subagent"] == f"a{20}"  # 最旧被丢
