"""AC9 cover: ContextVar set/get/reset + resolve_tools 工具排除 (AC7)。"""
from __future__ import annotations

import pytest
from langchain_core.tools import StructuredTool

from agent_flow_harness.subagents.context import (
    SubAgentContext,
    get_subagent_context,
    reset_subagent_context,
    set_subagent_context,
)
from agent_flow_harness.subagents.registry import SubAgentRegistry
from agent_flow_harness.subagents.spec import SubAgentSpec
from agent_flow_harness.tools.registry import ToolRegistry


def _make_tool(name: str) -> StructuredTool:
    def _fn(**_kwargs) -> str:
        return "ok"
    _fn.__name__ = name
    return StructuredTool.from_function(_fn, name=name, description=f"test {name}")


def _make_context(subagent_tool: StructuredTool | None = None) -> SubAgentContext:
    tool_reg = ToolRegistry()
    tool_reg.register(_make_tool("bash"))
    if subagent_tool is not None:
        tool_reg.register(subagent_tool)
    registry = SubAgentRegistry()
    return SubAgentContext(
        registry=registry,
        tool_registry=tool_reg,
        build_llm=lambda cfg: object(),  # 测试不实际构建 LLM
        parent_llm=None,
    )


def test_get_without_set_raises_runtime_error():
    """未设置 context 时 get 必须 raise RuntimeError。"""
    try:
        get_subagent_context()
        pytest.fail("get_subagent_context should raise when context is None")
    except RuntimeError:
        pass  # 期望：未设置时 raise


def test_set_then_get_returns_same_context():
    ctx = _make_context()
    token = set_subagent_context(ctx)
    try:
        assert get_subagent_context() is ctx
    finally:
        reset_subagent_context(token)


def test_reset_restores_previous_state():
    ctx = _make_context()
    token = set_subagent_context(ctx)
    reset_subagent_context(token)
    with pytest.raises(RuntimeError):
        get_subagent_context()


def test_resolve_tools_excludes_delegate():
    """AC7: resolve_tools 解析后必须排除 delegate_to_subagent。"""
    delegate_tool = _make_tool("delegate_to_subagent")
    ctx = _make_context(subagent_tool=delegate_tool)
    spec = SubAgentSpec(
        name="x", description="d", system_prompt="p",
        tools=["bash", "delegate_to_subagent"],
    )
    tools = ctx.resolve_tools(spec)
    names = [t.name for t in tools]
    assert "bash" in names
    assert "delegate_to_subagent" not in names


def test_resolve_tools_unknown_name_skipped():
    """未知工具名跳过（不 raise，与 TOOL_REGISTRY.resolve 行为一致）。"""
    ctx = _make_context()
    spec = SubAgentSpec(
        name="x", description="d", system_prompt="p",
        tools=["bash", "nonexistent_tool"],
    )
    tools = ctx.resolve_tools(spec)
    names = [t.name for t in tools]
    assert names == ["bash"]


# --- usage 累计器 + provider 注入通道 (M1) ---


def test_accumulate_usage_sums_numeric_and_skips_others():
    """数值型 key 累加；bool/字符串等非数值跳过（metrics 同构 key 才入账）。"""
    ctx = _make_context()
    ctx.accumulate_usage({"total_tokens": 100, "llm_calls": 2, "note": "x"})
    ctx.accumulate_usage({"total_tokens": 30, "llm_calls": 1, "flag": True})
    assert ctx.usage_totals == {"total_tokens": 130, "llm_calls": 3}


def test_tools_provider_overrides_registry_and_filters_delegate():
    """宿主 tools_provider 优先于 tool_registry（app 层动态工具集注入通道），
    且 provider 路径同样过滤 delegate（AC7 深度=1 不可绕过）。"""
    delegate_tool = _make_tool("delegate_to_subagent")
    dynamic_tool = _make_tool("mcp_search")
    ctx = _make_context(subagent_tool=delegate_tool)
    ctx.tools_provider = lambda spec: [delegate_tool, dynamic_tool]
    spec = SubAgentSpec(name="x", description="d", system_prompt="p", tools=[])
    tools = ctx.resolve_tools(spec)
    names = [t.name for t in tools]
    assert names == ["mcp_search"]
    assert "delegate_to_subagent" not in names


def test_llm_provider_overrides_inherit():
    """宿主 llm_provider 优先于 build_llm/parent_llm。"""
    sentinel = object()
    ctx = _make_context()
    ctx.llm_provider = lambda spec: sentinel
    spec = SubAgentSpec(name="x", description="d", system_prompt="p")
    assert ctx.resolve_llm(spec) is sentinel
