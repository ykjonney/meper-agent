"""Shared pytest fixtures for the harness test suite."""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import StructuredTool
from langgraph.checkpoint.memory import MemorySaver

from agent_flow_harness.state import AgentState


class FakeLLM:
    """Deterministic chat model for react_node tests.

    Yields the pre-programmed :class:`AIMessage` responses in order, one per
    ``ainvoke`` call. ``bind_tools`` is a no-op that returns ``self`` so the
    REACT loop does not actually bind anything (the responses are scripted).
    """

    def __init__(self, responses: list[AIMessage], model_name: str = "test-model"):
        self._responses = list(responses)
        self._model_name = model_name
        self.calls: list[Any] = []  # message-list snapshots per ainvoke

    @property
    def model_name(self) -> str:
        return self._model_name

    def bind_tools(self, _tools):  # noqa: ANN001, ANN202 - mimic LangChain API
        return self

    async def ainvoke(self, messages, _config=None):  # noqa: ANN001
        self.calls.append(list(messages))
        if not self._responses:
            msg = "FakeLLM exhausted: no more scripted responses."
            raise RuntimeError(msg)
        return self._responses.pop(0)


def make_tool(name: str, *, return_value: str = "ok") -> StructuredTool:
    """Build a named :class:`StructuredTool` returning a fixed string."""

    def _fn(**_kwargs: Any) -> str:  # noqa: ANN202
        return return_value

    _fn.__name__ = name
    return StructuredTool.from_function(_fn, name=name, description=f"test {name}")


@pytest.fixture
def fake_llm_factory():
    """Return a factory that builds :class:`FakeLLM` instances."""
    return FakeLLM


@pytest.fixture
def make_test_tool():
    """Return the :func:`make_tool` helper."""
    return make_tool


@pytest.fixture
def in_memory_checkpointer() -> MemorySaver:
    """A no-op in-memory checkpointer for tests that need a saver wired up."""
    return MemorySaver()


@pytest.fixture
def base_state() -> AgentState:
    """A minimal valid :class:`AgentState` for graph / node tests."""
    return AgentState(
        messages=[HumanMessage(content="hello")],
        agent_id="agent-1",
        execution_path="react",
        request_id="req-1",
        tool_results={},
        step_count=0,
        error=None,
        call_chain=[],
        current_depth=0,
        session_id="session-1",
        user_id="user-1",
    )


@pytest.fixture
def agent_doc() -> dict:
    """A minimal agent configuration document."""
    return {"_id": "agent-1", "name": "test-agent"}


def make_config(llm: Any, *, tools=None, context_window=None, workspace=None) -> dict:
    """Build a ``RunnableConfig`` dict for ``react_node``."""
    configurable: dict[str, Any] = {"llm": llm}
    if tools is not None:
        configurable["tools"] = tools
    if context_window is not None:
        configurable["context_window"] = context_window
    if workspace is not None:
        configurable["workspace"] = workspace
    return {"configurable": configurable}


@pytest.fixture
def make_run_config():
    """Return the :func:`make_config` helper."""
    return make_config
