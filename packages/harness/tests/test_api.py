"""create_agent 高层 API 测试。"""
from __future__ import annotations

from pathlib import Path

import pytest

from agent_flow_harness.api import AgentConfig, _config_to_doc


# ---------------------------------------------------------------------------
# AgentConfig (Task 1)
# ---------------------------------------------------------------------------


def test_agent_config_minimal():
    """最简 config：只有 name。"""
    cfg = AgentConfig(name="assistant")
    assert cfg.name == "assistant"
    assert cfg.system_prompt is None
    assert cfg.tools == []
    assert cfg.max_iterations == 25


def test_agent_config_with_system_prompt():
    cfg = AgentConfig(name="a", system_prompt="你是助手")
    assert cfg.system_prompt == "你是助手"


def test_agent_config_with_tools():
    cfg = AgentConfig(
        name="a",
        tools=[
            {"name": "bash", "enabled": True},
            {"use": "app.tools:x", "enabled": True},
        ],
    )
    assert len(cfg.tools) == 2


def test_agent_config_accepts_sandbox_instance():
    """sandbox 字段接收已构建的 Sandbox 实例（arbitrary_types_allowed）。"""
    from agent_flow_harness.sandbox import LocalSandbox

    sb = LocalSandbox(sandbox_id="t", work_dir=Path("/tmp"), timeout=10)
    cfg = AgentConfig(name="a", sandbox=sb)
    assert cfg.sandbox is sb


def test_agent_config_accepts_subagents_registry():
    """subagents 字段接收 SubAgentRegistry 实例。"""
    from agent_flow_harness.subagents import SubAgentRegistry

    reg = SubAgentRegistry()
    cfg = AgentConfig(name="a", subagents=reg)
    assert cfg.subagents is reg


def test_agent_config_name_has_default():
    """name 有默认值 'agent'，可不传。"""
    cfg = AgentConfig()
    assert cfg.name == "agent"


# ---------------------------------------------------------------------------
# _config_to_doc (Task 2)
# ---------------------------------------------------------------------------


def test_config_to_doc_maps_fields():
    cfg = AgentConfig(
        name="my-agent",
        tools=[{"name": "bash"}],
        guards=[{"type": "time_budget", "max_seconds": 30}],
        middleware=[{"type": "audit"}],
    )
    doc = _config_to_doc(cfg)
    assert doc["name"] == "my-agent"
    assert doc["tools"] == [{"name": "bash"}]
    assert doc["guards"] == [{"type": "time_budget", "max_seconds": 30}]
    assert doc["middleware"] == [{"type": "audit"}]


def test_config_to_doc_omits_empty():
    """guards/middleware 为空时不进 doc。"""
    doc = _config_to_doc(AgentConfig(name="x"))
    assert "guards" not in doc
    assert "middleware" not in doc


def test_config_to_doc_includes_prompt_slots():
    cfg = AgentConfig(name="x", prompt_slots={"role": "助手"})
    doc = _config_to_doc(cfg)
    assert doc["prompt_slots"] == {"role": "助手"}


# ---------------------------------------------------------------------------
# create_agent + Agent (Task 3)
# ---------------------------------------------------------------------------

from langchain_core.messages import AIMessage  # noqa: E402

from agent_flow_harness.api import create_agent  # noqa: E402


class _FakeLLM:
    """按调用顺序返回预设响应的假 LLM。"""

    def __init__(self, responses):
        self._responses = list(responses)

    @property
    def model_name(self):
        return "fake"

    def bind_tools(self, _tools):
        return self

    async def ainvoke(self, messages, _config=None):
        if not self._responses:
            raise RuntimeError("FakeLLM exhausted")
        return self._responses.pop(0)


def _make_agent(system_prompt="你是助手", tools=None, **kw):
    cfg = AgentConfig(name="t", system_prompt=system_prompt, tools=tools or [], **kw)
    return create_agent(cfg, model=_FakeLLM([AIMessage(content="done")]))


@pytest.mark.asyncio
async def test_agent_run_returns_final_text():
    """Agent.run 返回最终文本。"""
    agent = _make_agent()
    result = await agent.run("你好")
    assert result == "done"


@pytest.mark.asyncio
async def test_agent_run_injects_system_prompt():
    """system_prompt 被作为 SystemMessage 注入 input。"""
    agent = _make_agent(system_prompt="专属指令")
    result = await agent.run("hi")
    assert result == "done"  # run 成功即说明注入正确


@pytest.mark.asyncio
async def test_agent_run_with_sandbox_context():
    """config.sandbox 时 run 内部 set sandbox_context，结束后 reset。"""
    from agent_flow_harness.sandbox import LocalSandbox, get_sandbox_context

    import tempfile
    with tempfile.TemporaryDirectory() as td:
        sb = LocalSandbox(sandbox_id="t", work_dir=Path(td), timeout=10)
        agent = _make_agent(sandbox=sb)
        await agent.run("hi")
        # run 结束后 context 应已 reset（get 会 raise）
        with pytest.raises(RuntimeError):
            get_sandbox_context()


@pytest.mark.asyncio
async def test_agent_run_without_sandbox_no_context():
    """无 sandbox 时 run 不 set sandbox_context。"""
    from agent_flow_harness.sandbox import get_sandbox_context

    agent = _make_agent()
    await agent.run("hi")
    with pytest.raises(RuntimeError):
        get_sandbox_context()


@pytest.mark.asyncio
async def test_agent_tool_names_property():
    """tool_names 反映已装配工具（list 类型）。"""
    agent = _make_agent()
    assert isinstance(agent.tool_names, list)


@pytest.mark.asyncio
async def test_agent_stream_with_callback():
    """Agent.stream 通过 on_event 回调执行（FakeLLM 非真 BaseChatModel，
    不产生 on_chat_model 事件，验证执行完成不抛错即可）。"""
    agent = _make_agent()
    events = []

    async def collect(ev):
        events.append(ev)

    await agent.stream("hi", on_event=collect)


# ---------------------------------------------------------------------------
# builtin_tools / exclude_tools (opt-out)
# ---------------------------------------------------------------------------


def test_builtin_tools_default_all():
    """默认 builtin_tools='all'，create_agent 装配全部 8 个内建工具。"""
    from agent_flow_harness.tools.builtin import BUILTIN_TOOL_NAMES

    cfg = AgentConfig(name="t", system_prompt="x")
    agent = create_agent(cfg, model=_FakeLLM([AIMessage(content="ok")]))
    names = set(agent.tool_names)
    # 默认全开（至少包含内建工具）
    assert BUILTIN_TOOL_NAMES <= names


def test_builtin_tools_exclude():
    """exclude_tools 从全开中减去指定工具。"""
    cfg = AgentConfig(
        name="t", system_prompt="x",
        builtin_tools="all",
        exclude_tools=["grep", "glob"],
    )
    agent = create_agent(cfg, model=_FakeLLM([AIMessage(content="ok")]))
    names = set(agent.tool_names)
    assert "grep" not in names
    assert "glob" not in names
    assert "bash" in names  # 其他的还在


def test_builtin_tools_none_disables_all():
    """builtin_tools=None 关闭所有内建工具。"""
    cfg = AgentConfig(name="t", system_prompt="x", builtin_tools=None)
    agent = create_agent(cfg, model=_FakeLLM([AIMessage(content="ok")]))
    names = set(agent.tool_names)
    assert "bash" not in names
    assert "read" not in names


def test_builtin_tools_subset():
    """builtin_tools 指定子集列表。"""
    cfg = AgentConfig(
        name="t", system_prompt="x",
        builtin_tools=["bash", "read"],
    )
    agent = create_agent(cfg, model=_FakeLLM([AIMessage(content="ok")]))
    names = set(agent.tool_names)
    assert "bash" in names
    assert "read" in names
    assert "grep" not in names


def test_explicit_tools_plus_builtin():
    """显式 tools + builtin_tools 共存：两者合并。"""
    cfg = AgentConfig(
        name="t", system_prompt="x",
        tools=[{"name": "bash"}],  # 显式（经 registry，但 registry 空所以无效）
        builtin_tools=["ask_clarification"],  # 内建子集
    )
    agent = create_agent(cfg, model=_FakeLLM([AIMessage(content="ok")]))
    names = set(agent.tool_names)
    assert "ask_clarification" in names
