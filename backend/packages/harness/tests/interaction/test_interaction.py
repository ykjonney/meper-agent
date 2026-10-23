"""AC1/AC3 cover: ask_clarification(interrupt)。"""
from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from agent_flow_harness.graph import build_agent_graph, build_config
from agent_flow_harness.interaction import ask_clarification


def _ai_tool_call(name, args=None, call_id="c1"):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args or {}, "id": call_id}])


# ---------------------------------------------------------------------------
# ask_clarification (compiled graph HITL — interrupt 需要 graph 上下文)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ask_clarification_interrupts_graph(
    base_state, fake_llm_factory, agent_doc
):
    """AC1/AC3: ask_clarification 在 compiled graph 内挂起（__interrupt__）。"""
    llm = fake_llm_factory([
        _ai_tool_call("ask_clarification", {
            "question": "用哪个版本?",
            "clarification_type": "approach_choice",
            "options": ["v1", "v2"],
        }),
    ])
    checkpointer = MemorySaver()
    graph = build_agent_graph(
        agent_doc, checkpointer=checkpointer,
        tools=[ask_clarification], middleware=[],
    )
    config = build_config(agent_doc, llm, tools=[ask_clarification], recursion_limit=10)
    config["configurable"]["thread_id"] = "hitl-1"

    result = await graph.ainvoke(base_state, config=config)
    # interrupt 时 graph 返回 __interrupt__ 条目
    assert "__interrupt__" in result
    interrupt_tuple = result["__interrupt__"][0]
    payload = interrupt_tuple.value
    assert payload["question"] == "用哪个版本?"
    assert payload["type"] == "approach_choice"
    assert payload["options"] == ["v1", "v2"]


@pytest.mark.asyncio
async def test_ask_clarification_resume_returns_answer(
    base_state, fake_llm_factory, agent_doc
):
    """resume(Command(resume=answer)) 后, interrupt 返回答案给 LLM 继续。"""
    # 第一轮: 调 ask_clarification (挂起); resume 后 LLM 给最终答案
    llm = fake_llm_factory([
        _ai_tool_call("ask_clarification", {"question": "颜色?"}),
        AIMessage(content="用户选择了红色"),
    ])
    checkpointer = MemorySaver()
    graph = build_agent_graph(
        agent_doc, checkpointer=checkpointer,
        tools=[ask_clarification], middleware=[],
    )
    config = build_config(agent_doc, llm, tools=[ask_clarification], recursion_limit=10)
    config["configurable"]["thread_id"] = "hitl-2"

    # 第一轮触发 interrupt
    result1 = await graph.ainvoke(base_state, config=config)
    assert "__interrupt__" in result1

    # resume 传答案
    result2 = await graph.ainvoke(Command(resume="红色"), config=config)
    # LLM 应已收到答案并给出最终文本
    contents = [m.content for m in result2["messages"] if isinstance(m, AIMessage)]
    assert any("红色" in c for c in contents)


def test_ask_clarification_is_tool():
    from langchain_core.tools import BaseTool
    assert isinstance(ask_clarification, BaseTool)
    assert ask_clarification.name == "ask_clarification"


# ---------------------------------------------------------------------------
# ask_clarification 向导模式（fields 多字段，一次 interrupt，前端逐题作答）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ask_clarification_fields_interrupts_graph(
    base_state, fake_llm_factory, agent_doc
):
    """向导模式：fields 非空时 interrupt payload 携带按序字段定义。"""
    llm = fake_llm_factory([
        _ai_tool_call("ask_clarification", {
            "question": "请补充报告参数",
            "clarification_type": "missing_info",
            "fields": [
                {
                    "name": "audience",
                    "label": "目标受众是谁？",
                    "field_type": "select",
                    "options": ["技术人员", "管理层", "客户", "通用读者"],
                    "required": True,
                },
                {
                    "name": "api_key",
                    "label": "API Key",
                    "field_type": "text",
                    "required": True,
                },
                {
                    "name": "length",
                    "label": "篇幅(字)",
                    "field_type": "number",
                    "default": 500,
                },
            ],
        }),
    ])
    checkpointer = MemorySaver()
    graph = build_agent_graph(
        agent_doc, checkpointer=checkpointer,
        tools=[ask_clarification], middleware=[],
    )
    config = build_config(agent_doc, llm, tools=[ask_clarification], recursion_limit=10)
    config["configurable"]["thread_id"] = "hitl-fields-1"

    result = await graph.ainvoke(base_state, config=config)
    assert "__interrupt__" in result
    payload = result["__interrupt__"][0].value
    assert payload["question"] == "请补充报告参数"
    fields = payload["fields"]
    assert isinstance(fields, list) and len(fields) == 3
    # 有 options 的字段（推荐选项）
    assert fields[0]["name"] == "audience"
    assert fields[0]["options"] == ["技术人员", "管理层", "客户", "通用读者"]
    assert "allow_other" not in fields[0]  # 该字段已移除
    # 无 options 的字段（如密码/密钥，纯输入）
    assert fields[1]["name"] == "api_key"
    assert fields[1]["options"] is None
    # number 字段带默认值
    assert fields[2]["field_type"] == "number"
    assert fields[2]["default"] == 500


@pytest.mark.asyncio
async def test_ask_clarification_fields_resume_returns_answer(
    base_state, fake_llm_factory, agent_doc
):
    """向导模式 resume：前端逐题作答后序列化的 JSON 字符串经 interrupt 返回给 LLM。"""
    llm = fake_llm_factory([
        _ai_tool_call("ask_clarification", {
            "question": "请补充报告参数",
            "fields": [
                {"name": "audience", "label": "目标受众", "field_type": "select", "options": ["技术人员", "管理层"]},
                {"name": "format", "label": "格式", "field_type": "select", "options": ["Markdown", "PDF"]},
            ],
        }),
        AIMessage(content="已收到参数，开始生成"),
    ])
    checkpointer = MemorySaver()
    graph = build_agent_graph(
        agent_doc, checkpointer=checkpointer,
        tools=[ask_clarification], middleware=[],
    )
    config = build_config(agent_doc, llm, tools=[ask_clarification], recursion_limit=10)
    config["configurable"]["thread_id"] = "hitl-fields-2"

    # 第一轮触发 interrupt
    result1 = await graph.ainvoke(base_state, config=config)
    assert "__interrupt__" in result1

    # resume 传 JSON 字符串答案（用户在向导中逐题作答后序列化的结果）
    answer_json = '{"audience":"管理层","format":"PDF"}'
    result2 = await graph.ainvoke(Command(resume=answer_json), config=config)
    contents = [m.content for m in result2["messages"] if isinstance(m, AIMessage)]
    assert any("已收到参数" in c for c in contents)


