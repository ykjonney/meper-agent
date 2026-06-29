"""ContextStrategy ABC + token_estimator 测试。"""
from __future__ import annotations

import pytest
from langchain_core.messages import HumanMessage

from agent_flow_harness.context_engineering.base import ContextStrategy
from agent_flow_harness.context_engineering.token_estimator import count_tokens


def test_count_tokens_string():
    assert count_tokens("hello world") > 0


def test_count_tokens_messages():
    msgs = [HumanMessage(content="hi"), HumanMessage(content="there")]
    assert count_tokens(msgs) > count_tokens([msgs[0]])


def test_count_tokens_empty_string():
    assert count_tokens("") == 1  # max(1, 0)


def test_strategy_is_abstract():
    with pytest.raises(TypeError):
        ContextStrategy()  # type: ignore[abstract]
