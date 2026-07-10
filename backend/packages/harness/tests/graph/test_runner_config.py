"""Cover: build_config resolves tools via the registry into a react_node config."""

from __future__ import annotations

import pytest

from agent_flow_harness.engine.react import react_node
from agent_flow_harness.graph import build_config
from agent_flow_harness.tools.registry import ToolRegistry


def _stub_llm(responses):
    class _LLM:
        model_name = "test"

        def __init__(self, resp):
            self._resp = resp

        def bind_tools(self, _tools):
            return self

        async def ainvoke(self, _messages, _config=None):
            return self._resp.pop(0)

    return _LLM(responses)


@pytest.mark.asyncio
async def test_build_config_resolves_tools_from_registry(
    base_state, make_test_tool
) -> None:
    """build_config reads agent_doc['tools'] through the registry."""
    registry = ToolRegistry()
    echo = make_test_tool("echo", return_value="echoed")
    registry.register(echo)

    from langchain_core.messages import AIMessage as _AI

    llm = _stub_llm([
        _AI(content="", tool_calls=[{"name": "echo", "args": {}, "id": "c1"}]),
        _AI(content="done"),
    ])
    agent_doc = {"tools": [{"name": "echo", "enabled": True}]}
    config = build_config(agent_doc, llm, registry=registry)

    result = await react_node(base_state, config)

    assert result["step_count"] == 2
    tool_msgs = [m for m in result["messages"] if m.type == "tool"]
    assert tool_msgs[0].content == "echoed"


def test_build_config_explicit_tools_bypass_registry() -> None:
    """Passing tools= skips registry resolution."""
    llm = _stub_llm([])
    config = build_config({}, llm, tools=["raw-tool"])
    assert config["configurable"]["tools"] == ["raw-tool"]
    assert config["configurable"]["llm"] is llm
    assert config["recursion_limit"] == 75


def test_build_config_includes_optional_keys() -> None:
    llm = _stub_llm([])
    config = build_config(
        {"tools": []},
        llm,
        thread_id="t1",
        context_window=8000,
        workspace="ws",
        recursion_limit=10,
    )
    cfg = config["configurable"]
    assert cfg["thread_id"] == "t1"
    assert cfg["context_window"] == 8000
    assert cfg["workspace"] == "ws"
    assert config["recursion_limit"] == 10


def test_build_config_passes_cancel_checker() -> None:
    """build_config should include cancel_checker in configurable when provided."""
    llm = _stub_llm([])

    async def _checker() -> bool:
        return False

    config = build_config({"tools": []}, llm, cancel_checker=_checker)
    cfg = config["configurable"]
    assert cfg["cancel_checker"] is _checker


def test_build_config_omits_cancel_checker_when_none() -> None:
    """cancel_checker should not be in configurable when not provided."""
    llm = _stub_llm([])
    config = build_config({"tools": []}, llm)
    cfg = config["configurable"]
    assert "cancel_checker" not in cfg
