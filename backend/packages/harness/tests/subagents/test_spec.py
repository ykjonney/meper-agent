"""AC2 cover: SubAgentSpec 字段与校验。"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent_flow_harness.subagents.spec import SubAgentSpec


def _valid_kwargs(**overrides):
    base = {
        "name": "researcher",
        "description": "信息检索子 agent",
        "system_prompt": "你是一个专业研究员",
        "tools": ["bash", "read"],
    }
    base.update(overrides)
    return base


def test_spec_required_fields():
    spec = SubAgentSpec(**_valid_kwargs())
    assert spec.name == "researcher"
    assert spec.description == "信息检索子 agent"
    assert spec.system_prompt == "你是一个专业研究员"
    assert spec.tools == ["bash", "read"]


def test_spec_default_llm_config_empty():
    spec = SubAgentSpec(**_valid_kwargs())
    assert spec.llm_config == {}


def test_spec_default_max_turns_25():
    spec = SubAgentSpec(**_valid_kwargs())
    assert spec.max_turns == 25


def test_spec_inherit_model():
    spec = SubAgentSpec(**_valid_kwargs(llm_config={"model": "inherit"}))
    assert spec.llm_config == {"model": "inherit"}


def test_spec_name_cannot_be_empty():
    with pytest.raises(ValidationError):
        SubAgentSpec(**_valid_kwargs(name=""))


def test_spec_name_cannot_be_whitespace():
    with pytest.raises(ValidationError):
        SubAgentSpec(**_valid_kwargs(name="   "))


def test_spec_tools_can_be_empty_list():
    """子 agent 可以没有任何工具（纯推理）。"""
    spec = SubAgentSpec(**_valid_kwargs(tools=[]))
    assert spec.tools == []


def test_spec_timeout_upper_bound_10min():
    """timeout_ms 上限 600s：超时阻塞在父 REACT 一轮里，过长配置会卡死
    父 agent（SSE 已断而 token 持续燃烧），必须封顶。"""
    assert SubAgentSpec(**_valid_kwargs(timeout_ms=600_000)).timeout_ms == 600_000
    with pytest.raises(ValidationError):
        SubAgentSpec(**_valid_kwargs(timeout_ms=600_001))
