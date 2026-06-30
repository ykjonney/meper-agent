"""ToolMessage 配对保护测试。"""
from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from agent_flow_harness.context_engineering.pairing import ensure_tool_pairing


def test_keeps_paired_messages():
    """完整的 tool_call + tool_result 配对都保留。"""
    msgs = [
        HumanMessage(content="hi"),
        AIMessage(content="", tool_calls=[{"name": "bash", "args": {}, "id": "c1"}]),
        ToolMessage(content="result", tool_call_id="c1"),
        AIMessage(content="done"),
    ]
    result = ensure_tool_pairing(msgs)
    assert len(result) == 4


def test_drops_orphan_tool_call():
    """有 tool_call 但无 tool_result → 丢弃该 AIMessage。"""
    msgs = [
        AIMessage(content="", tool_calls=[{"name": "bash", "args": {}, "id": "c1"}]),
        AIMessage(content="done"),
    ]
    result = ensure_tool_pairing(msgs)
    assert len(result) == 1
    assert result[0].content == "done"


def test_drops_orphan_tool_result():
    """有 tool_result 但无对应 tool_call → 丢弃。"""
    msgs = [
        ToolMessage(content="result", tool_call_id="orphan"),
        AIMessage(content="done"),
    ]
    result = ensure_tool_pairing(msgs)
    assert len(result) == 1
    assert result[0].content == "done"


def test_preserves_multiple_pairs():
    """多个连续配对都保留。"""
    msgs = [
        AIMessage(content="", tool_calls=[{"name": "t", "args": {}, "id": "a"}]),
        ToolMessage(content="ra", tool_call_id="a"),
        AIMessage(content="", tool_calls=[{"name": "t", "args": {}, "id": "b"}]),
        ToolMessage(content="rb", tool_call_id="b"),
        AIMessage(content="final"),
    ]
    result = ensure_tool_pairing(msgs)
    assert len(result) == 5


def test_keeps_ai_with_content_and_invalid_calls():
    """AIMessage 有 content + 无效 tool_calls → 保留（content 有值）。"""
    msgs = [
        AIMessage(content="hello", tool_calls=[{"name": "t", "args": {}, "id": "x"}]),
        AIMessage(content="done"),
    ]
    result = ensure_tool_pairing(msgs)
    assert len(result) == 2  # 两条都保留（第一条有 content）


def test_empty_messages():
    assert ensure_tool_pairing([]) == []
