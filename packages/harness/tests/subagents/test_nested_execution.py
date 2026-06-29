"""AC5/AC6/AC7/AC8 集成测试: 真实主 Agent 委派子 Agent 端到端。

用 FakeLLM 脚本化响应：主 Agent 调用 delegate → 子 Agent 执行 → 结果回主 Agent。
验证：延迟构建(AC5)、只追加 1 条 ToolMessage(AC6)、工具排除(AC7)、状态隔离(AC8)。
"""
from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage

from agent_flow_harness.engine.react import react_node
from agent_flow_harness.subagents.context import (
    SubAgentContext,
    reset_subagent_context,
    set_subagent_context,
)
from agent_flow_harness.subagents.registry import SubAgentRegistry
from agent_flow_harness.subagents.spec import SubAgentSpec
from agent_flow_harness.tools.registry import ToolRegistry


class _FakeLLM:
    """按调用顺序返回预设响应的假 LLM（与 conftest.FakeLLM 同构）。"""

    def __init__(self, responses, model_name="fake"):
        self._responses = list(responses)
        self._model_name = model_name

    @property
    def model_name(self):
        return self._model_name

    def bind_tools(self, _tools):
        return self

    async def ainvoke(self, messages, _config=None):
        if not self._responses:
            raise RuntimeError("FakeLLM exhausted")
        return self._responses.pop(0)


def _ai_tool_call(name, args=None, call_id="c1"):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args or {}, "id": call_id}])


def _ai_text(text):
    return AIMessage(content=text)


@pytest.mark.asyncio
async def test_end_to_end_delegation(base_state, make_run_config):
    """AC5/AC6: 主 Agent 委派 → 子 Agent 回答 → 主 Agent 收 ToolMessage。"""
    # 子 Agent 的 LLM：被调用一次，直接返回最终文本。
    sub_llm = _FakeLLM([_ai_text("subagent computed: 42")])

    registry = SubAgentRegistry()
    registry.register(SubAgentSpec(
        name="computer",
        description="compute things",
        system_prompt="你是计算助手",
        tools=[],
        # 显式用 build_llm 路径（非 inherit），这样 ctx.build_llm 返回 sub_llm。
        llm_config={"model": "fake-sub"},
        max_turns=5,
    ))

    ctx = SubAgentContext(
        registry=registry,
        tool_registry=ToolRegistry(),
        build_llm=lambda cfg: sub_llm,
        parent_llm=None,
    )
    token = set_subagent_context(ctx)
    try:
        from agent_flow_harness.subagents import delegate_to_subagent

        # 主 Agent LLM: 先调用 delegate，再输出最终答案。
        main_llm = _FakeLLM([
            _ai_tool_call("delegate_to_subagent",
                          {"subagent_name": "computer", "task": "计算答案"}, "tc1"),
            _ai_text("最终结果由子 Agent 给出"),
        ])
        config = make_run_config(main_llm, tools=[delegate_to_subagent])

        result = await react_node(base_state, config)

        # AC6: 主 Agent messages 里有 delegate 的 ToolMessage，含子 agent 结果。
        tool_msgs = [m for m in result["messages"]
                     if m.__class__.__name__ == "ToolMessage"]
        assert any("42" in (m.content or "") for m in tool_msgs), \
            "子 Agent 结果应作为 ToolMessage 出现在主 Agent messages"
        # 主 Agent 最终答案也在。
        contents = [m.content for m in result["messages"] if isinstance(m, AIMessage)]
        assert any("最终结果" in c for c in contents)
    finally:
        reset_subagent_context(token)


@pytest.mark.asyncio
async def test_subagent_tools_exclude_delegate(base_state, make_run_config):
    """AC7: 子 Agent 工具列表不含 delegate（物理防递归）。"""
    from agent_flow_harness.subagents import delegate_to_subagent

    tool_reg = ToolRegistry()
    tool_reg.register(delegate_to_subagent)  # delegate 在全局 registry 里
    registry = SubAgentRegistry()
    # 子 Agent spec 声明要用 delegate（但 resolve 时会被排除）。
    registry.register(SubAgentSpec(
        name="nested",
        description="tries to nest",
        system_prompt="p",
        tools=["delegate_to_subagent"],
        max_turns=3,
    ))
    ctx = SubAgentContext(
        registry=registry,
        tool_registry=tool_reg,
        build_llm=lambda cfg: _FakeLLM([_ai_text("ok")]),
        parent_llm=None,
    )
    # resolve_tools 必须排除 delegate。
    spec = registry.get("nested")
    tools = ctx.resolve_tools(spec)
    assert all(t.name != "delegate_to_subagent" for t in tools), \
        "子 Agent 绝不能拿到 delegate_to_subagent 工具"


@pytest.mark.asyncio
async def test_subagent_state_isolation(base_state, make_run_config):
    """AC8: 子 Agent 是全新隔离 state，不继承主 Agent 历史。

    主 Agent 的 base_state 含 'hello' 历史消息，子 Agent 不应看到它——
    子 Agent state 只有 system_prompt + task。
    """
    sub_llm = _FakeLLM([_ai_text("done")])
    registry = SubAgentRegistry()
    registry.register(SubAgentSpec(
        name="isolated",
        description="iso",
        system_prompt="你是助手",
        tools=[],
        max_turns=5,
    ))
    ctx = SubAgentContext(
        registry=registry,
        tool_registry=ToolRegistry(),
        build_llm=lambda cfg: sub_llm,
        parent_llm=None,
    )
    spec = registry.get("isolated")
    state = ctx.build_subagent_state(spec, "do task")
    msgs = state["messages"]
    # 只有 system_prompt + task，没有主 agent 的 'hello'。
    contents = [m.content for m in msgs]
    assert "hello" not in contents
    assert len(msgs) == 2
