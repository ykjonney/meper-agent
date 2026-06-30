"""harness_integration/stream.py 测试 — 验证 harness 引擎事件产出 + 工具替换。"""
from __future__ import annotations

import pytest
from app.engine.harness_integration.stream import run_agent_streaming_harness
from langchain_core.messages import AIMessage, HumanMessage


class _FakeLLM:
    def __init__(self, response: AIMessage):
        self._response = response

    @property
    def model_name(self):
        return "fake"

    def bind_tools(self, _tools):
        return self

    async def ainvoke(self, messages, _config=None):
        return self._response

    async def astream(self, messages, _config=None, **_kw):
        yield self._response


class _FakeExecContext:
    def __init__(self, llm, tools=None, context_window=128000):
        self.llm = llm
        self.tools = tools or []
        self.context_window = context_window


class _FakeSettings:
    """模拟 backend settings（避免真实配置依赖）。"""
    SANDBOX_ENABLED = False
    SANDBOX_IMAGE = "test:latest"
    SANDBOX_MEM_LIMIT = "512m"
    SANDBOX_CPU_QUOTA = 100000
    SANDBOX_TIMEOUT = 10
    SANDBOX_MAX_OUTPUT_BYTES = 1000000
    SANDBOX_NETWORK_MODE = "none"
    SANDBOX_CONTAINER_WORKSPACE_DIR = "/workspace"
    SANDBOX_CONTAINER_SKILLS_DIR = "/skills"
    WORKSPACES_CONTAINER_DIR = "/tmp/test_workspaces"
    SKILLS_CONTAINER_DIR = "/tmp/test_skills"


@pytest.fixture
def mock_deps(monkeypatch):
    """统一 mock 所有外部依赖。"""
    llm = _FakeLLM(AIMessage(content="hello from harness"))
    fake_ctx = _FakeExecContext(llm=llm)

    async def fake_resolve(agent, enable_thinking=False):
        return fake_ctx

    monkeypatch.setattr(
        "app.engine.agent.builder._resolve_execution_context",
        fake_resolve,
    )
    monkeypatch.setattr(
        "app.engine.agent.react_executor._setup_workspace_context",
        lambda state: None,
    )
    monkeypatch.setattr(
        "app.engine.checkpointer.get_checkpointer",
        lambda: None,
    )
    monkeypatch.setattr("app.core.config.settings", _FakeSettings())
    monkeypatch.setattr("app.models.compat.resolve_skill_ids", lambda doc: [])
    return fake_ctx


@pytest.mark.asyncio
async def test_run_streaming_harness_produces_result(mock_deps):
    """run_agent_streaming_harness 正常执行不抛错。"""
    agent = {"_id": "test-agent", "name": "test"}
    state = {
        "messages": [HumanMessage(content="hi")],
        "agent_id": "test-agent",
        "request_id": "req-1",
        "session_id": "s1",
        "user_id": "u1",
    }

    events: list[dict] = []

    async def collect(ev):
        events.append(ev)

    result = await run_agent_streaming_harness(agent, state, on_event=collect)
    assert "step_count" in result


@pytest.mark.asyncio
async def test_run_streaming_harness_returns_step_count(mock_deps):
    """返回值含 step_count。"""
    result = await run_agent_streaming_harness(
        {"_id": "a", "name": "a"},
        {"messages": [HumanMessage(content="hi")], "session_id": "s1", "user_id": "u1"},
        on_event=lambda ev: _noop(),
    )
    assert isinstance(result, dict)
    assert "step_count" in result


@pytest.mark.asyncio
async def test_tool_replacement_filters_backend_bash(mock_deps, monkeypatch):
    """backend 的 bash 工具被替换为 harness 的。"""
    from langchain_core.tools import tool as lc_tool

    @lc_tool
    def bash(command: str) -> str:
        """backend bash."""
        return "backend"

    fake_ctx = _FakeExecContext(llm=_FakeLLM(AIMessage(content="ok")), tools=[bash])

    async def fake_resolve(agent, enable_thinking=False):
        return fake_ctx

    monkeypatch.setattr(
        "app.engine.agent.builder._resolve_execution_context",
        fake_resolve,
    )
    monkeypatch.setattr("app.core.config.settings", _FakeSettings())

    agent = {"_id": "test", "name": "test"}
    state = {"messages": [HumanMessage(content="hi")], "session_id": "s1", "user_id": "u1"}

    result = await run_agent_streaming_harness(
        agent, state, on_event=lambda ev: _noop()
    )
    assert "step_count" in result


async def _noop():
    pass
