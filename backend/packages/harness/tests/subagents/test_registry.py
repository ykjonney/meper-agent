"""AC3 cover: SubAgentRegistry register/get/list_names。"""
from __future__ import annotations

import pytest

from agent_flow_harness.subagents.registry import SubAgentRegistry
from agent_flow_harness.subagents.spec import SubAgentSpec


def _spec(name: str) -> SubAgentSpec:
    return SubAgentSpec(
        name=name,
        description=f"{name} subagent",
        system_prompt=f"prompt for {name}",
        tools=["bash"],
    )


def test_register_and_get():
    reg = SubAgentRegistry()
    spec = _spec("researcher")
    reg.register(spec)
    assert reg.get("researcher") is spec


def test_get_unknown_raises_key_error():
    reg = SubAgentRegistry()
    with pytest.raises(KeyError):
        reg.get("nonexistent")


def test_register_duplicate_name_raises_value_error():
    reg = SubAgentRegistry()
    reg.register(_spec("coder"))
    with pytest.raises(ValueError, match="coder"):
        reg.register(_spec("coder"))


def test_list_names():
    reg = SubAgentRegistry()
    reg.register(_spec("coder"))
    reg.register(_spec("researcher"))
    assert sorted(reg.list_names()) == ["coder", "researcher"]


def test_list_names_empty():
    reg = SubAgentRegistry()
    assert reg.list_names() == []


def test_register_multiple_distinct():
    reg = SubAgentRegistry()
    reg.register(_spec("a"))
    reg.register(_spec("b"))
    reg.register(_spec("c"))
    assert len(reg.list_names()) == 3
