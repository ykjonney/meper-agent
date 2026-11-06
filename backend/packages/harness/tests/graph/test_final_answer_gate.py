"""final_answer_gate — 回合结束门控测试。

机制（harness 侧，不含 todo 语义）：llm_node 在最终回复（无 tool_call，
tools_condition 将判 END）时回调宿主注入的 gate；返回文案则追加带
``final_gate_reminder_`` id 前缀的 HumanMessage，builder 路由见前缀回
compress 续跑；每用户轮预算 2 次防死循环。

回归要点：
- 未配 gate（None）时行为与现状完全一致（零开销直通）；
- 有 tool_call 的中间迭代不触发 gate；
- 预算按「当前用户轮」计数，跨用户轮重置；id 全局递增不重号
  （add_messages 按 id upsert，重号会覆盖旧消息）；
- gate 抛异常不阻断收尾；
- 图级：提醒后路由回 compress 续跑（LLM 收到提醒作为最新输入）；
  Command 返回的工具可写 todos channel 并随 checkpointer 持久化。
"""

from __future__ import annotations

from typing import Annotated, Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import InjectedToolCallId, StructuredTool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command
from pydantic import BaseModel

from agent_flow_harness.graph import build_agent_graph, build_config
from agent_flow_harness.graph.nodes.llm_nodes import (
    FINAL_GATE_REMINDER_PREFIX,
    llm_node,
)


class _ScriptedLLM:
    """按脚本顺序返回 AIMessage，并记录每次 ainvoke 收到的消息列表。"""

    def __init__(self, responses: list[AIMessage]) -> None:
        self._responses = list(responses)
        self.calls: list[list] = []

    @property
    def model_name(self) -> str:
        return "test-model"

    def bind_tools(self, _tools):  # noqa: ANN001, ANN202
        return self

    async def ainvoke(self, messages, _config=None):  # noqa: ANN001
        self.calls.append(list(messages))
        if not self._responses:
            msg = "ScriptedLLM exhausted: no more responses."
            raise RuntimeError(msg)
        return self._responses.pop(0)


def _final(text: str = "最终回答") -> AIMessage:
    return AIMessage(content=text)


def _reminder(msg_id: str, text: str = "还有未完成项") -> HumanMessage:
    return HumanMessage(content=text, id=msg_id)


async def _always(state: Any, resp: Any) -> str:
    return "继续做完"


async def _never(state: Any, resp: Any) -> None:
    return None


def _reminders_in(messages: list) -> list:
    return [
        m for m in messages
        if str(getattr(m, "id", "") or "").startswith(FINAL_GATE_REMINDER_PREFIX)
    ]


# ---------------------------------------------------------------------------
# llm_node 单元级
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gate_appends_reminder_on_final_answer(base_state) -> None:
    """最终回复 + gate 返回文案 → patch 追加 reminder（id 前缀正确）。"""
    llm = _ScriptedLLM([_final()])
    config = {
        "configurable": {"llm": llm, "final_answer_gate": _always},
    }
    patch = await llm_node(base_state, config)

    messages = patch["messages"]
    assert len(messages) == 2
    reminder = messages[-1]
    assert isinstance(reminder, HumanMessage)
    assert reminder.content == "继续做完"
    assert str(reminder.id).startswith(FINAL_GATE_REMINDER_PREFIX)


@pytest.mark.asyncio
async def test_gate_ignored_when_tool_calls_present(base_state) -> None:
    """带 tool_call 的迭代不触发 gate（中间迭代零开销）。"""
    called: list[int] = []

    async def gate(state, resp):
        called.append(1)
        return "不应触发"

    llm = _ScriptedLLM([
        AIMessage(content="", tool_calls=[{"name": "t", "args": {}, "id": "c1"}]),
    ])
    config = {"configurable": {"llm": llm, "final_answer_gate": gate}}
    patch = await llm_node(base_state, config)
    assert called == []
    assert len(patch["messages"]) == 1  # 只有 AI 响应，无提醒


@pytest.mark.asyncio
async def test_gate_passes_when_none(base_state) -> None:
    """gate 返回 None（清单全终态）→ 正常收尾，无提醒。"""
    llm = _ScriptedLLM([_final()])
    config = {"configurable": {"llm": llm, "final_answer_gate": _never}}
    patch = await llm_node(base_state, config)
    assert len(patch["messages"]) == 1


@pytest.mark.asyncio
async def test_no_gate_configured_behavior_unchanged(base_state) -> None:
    """未配 gate：与现状完全一致（回归保障）。"""
    llm = _ScriptedLLM([_final()])
    config = {"configurable": {"llm": llm}}
    patch = await llm_node(base_state, config)
    assert len(patch["messages"]) == 1
    assert patch["step_count"] == 1


@pytest.mark.asyncio
async def test_budget_exhausted_stops_reminders(base_state) -> None:
    """当前用户轮已注入 2 条提醒 → 第三次最终回复放行 END。"""
    base_state["messages"] = [
        HumanMessage(content="用户请求", id="u1"),
        _reminder(f"{FINAL_GATE_REMINDER_PREFIX}1"),
        _final("回答1"),
        _reminder(f"{FINAL_GATE_REMINDER_PREFIX}2"),
        _final("回答2"),
    ]
    llm = _ScriptedLLM([_final("回答3")])
    config = {"configurable": {"llm": llm, "final_answer_gate": _always}}
    patch = await llm_node(base_state, config)
    assert len(patch["messages"]) == 1  # 预算尽，不注入


@pytest.mark.asyncio
async def test_budget_resets_on_new_user_message(base_state) -> None:
    """新用户消息重置预算；id 全局递增不与旧提醒重号。"""
    base_state["messages"] = [
        HumanMessage(content="用户请求1", id="u1"),
        _reminder(f"{FINAL_GATE_REMINDER_PREFIX}1"),
        _final("回答1"),
        _reminder(f"{FINAL_GATE_REMINDER_PREFIX}2"),
        _final("回答2"),
        HumanMessage(content="用户请求2", id="u2"),
    ]
    llm = _ScriptedLLM([_final("回答3")])
    config = {"configurable": {"llm": llm, "final_answer_gate": _always}}
    patch = await llm_node(base_state, config)
    reminder = patch["messages"][-1]
    assert str(reminder.id) == f"{FINAL_GATE_REMINDER_PREFIX}3"  # 全局第 3 条


@pytest.mark.asyncio
async def test_gate_exception_swallowed(base_state) -> None:
    """gate 抛异常 → 按无提醒放行，不阻断收尾。"""
    llm = _ScriptedLLM([_final()])

    async def broken_gate(state, resp):
        raise RuntimeError("gate bug")

    config = {"configurable": {"llm": llm, "final_answer_gate": broken_gate}}
    patch = await llm_node(base_state, config)
    assert len(patch["messages"]) == 1


# ---------------------------------------------------------------------------
# 图级 — 提醒续跑路由 + Command 工具写 todos 端到端
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_graph_loops_back_until_budget_exhausted(base_state, agent_doc) -> None:
    """提醒 → 回 compress → LLM 带提醒续跑；预算 2 次后正常 END。"""
    gate_calls: list[int] = []

    async def always_remind(state, resp):
        gate_calls.append(1)
        return "还有未完成待办，继续"

    llm = _ScriptedLLM([_final("v1"), _final("v2"), _final("v3")])
    graph = build_agent_graph(agent_doc, middleware=[])
    config = build_config(
        agent_doc, llm, tools=[], middlewares=[], recursion_limit=30,
        final_answer_gate=always_remind,
    )
    config["configurable"]["thread_id"] = "gate-1"

    result = await graph.ainvoke(base_state, config=config)

    assert len(llm.calls) == 3          # 两次被提醒续跑，第三次预算尽放行
    assert len(gate_calls) == 2         # 第三次预算检查在 gate 调用之前短路
    # 第二次 LLM 调用的输入以提醒消息收尾（续跑 = 模型看得见提醒）
    second_input = llm.calls[1]
    assert str(getattr(second_input[-1], "id", "") or "").startswith(
        FINAL_GATE_REMINDER_PREFIX
    )
    # 终态：两条提醒都在 history，末消息是 AI（tools_condition 判 END）
    assert len(_reminders_in(result["messages"])) == 2
    assert isinstance(result["messages"][-1], AIMessage)


@pytest.mark.asyncio
async def test_no_gate_graph_ends_immediately(base_state, agent_doc) -> None:
    """未配 gate 的图：一次最终回复即 END（回归）。"""
    llm = _ScriptedLLM([_final("done")])
    graph = build_agent_graph(agent_doc, middleware=[])
    config = build_config(agent_doc, llm, tools=[], middlewares=[], recursion_limit=10)
    config["configurable"]["thread_id"] = "gate-2"

    result = await graph.ainvoke(base_state, config=config)
    assert len(llm.calls) == 1
    assert _reminders_in(result["messages"]) == []


# ---------------------------------------------------------------------------
# Command 工具端到端：todos channel 写入 + checkpointer 持久化
# （本地复刻 app 层 todo_write 的机制形态——harness 测试不 import app.*）
# ---------------------------------------------------------------------------


class _Item(BaseModel):
    content: str
    status: str = "pending"


class _Args(BaseModel):
    todos: list[_Item]
    tool_call_id: Annotated[str, InjectedToolCallId]


async def _todo_write(
    todos: list[_Item], tool_call_id: Annotated[str, InjectedToolCallId]
) -> Command:
    items = [t.model_dump() for t in todos]
    return Command(
        update={
            "todos": items,
            "messages": [
                ToolMessage(
                    content="清单已更新",
                    name="todo_write",
                    tool_call_id=tool_call_id,
                )
            ],
        }
    )


_todo_tool = StructuredTool.from_function(
    _todo_write, name="todo_write", args_schema=_Args,
    description="test todo_write", coroutine=_todo_write,
)


def _todo_call(call_id: str = "tc1") -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{
            "name": "todo_write",
            "args": {"todos": [{"content": "任务A", "status": "pending"}]},
            "id": call_id,
        }],
    )


def _has_pending(state: Any) -> bool:
    todos = state.get("todos") or []
    return any(
        isinstance(t, dict) and t.get("status") == "pending" for t in todos
    )


@pytest.mark.asyncio
async def test_command_tool_writes_todos_and_gate_closes_loop(
    base_state, agent_doc
) -> None:
    """端到端：工具 Command 写 todos → 最终回复触发 gate → 提醒续跑收尾。"""
    reminded: list[bool] = []

    async def once_gate(state: Any, resp: Any) -> str | None:
        if _has_pending(state) and not reminded:
            reminded.append(True)
            return "还有 pending 待办"
        return None

    llm = _ScriptedLLM([_todo_call(), _final("先这样"), _final("全部完成")])
    checkpointer = MemorySaver()
    graph = build_agent_graph(
        agent_doc, checkpointer=checkpointer, tools=[_todo_tool], middleware=[],
    )
    config = build_config(
        agent_doc, llm, tools=[_todo_tool], middlewares=[], recursion_limit=30,
        final_answer_gate=once_gate,
    )
    config["configurable"]["thread_id"] = "gate-3"

    result = await graph.ainvoke(base_state, config=config)

    # Command 生效：todos channel 已写入工具的完整数据
    assert result["todos"] == [{"content": "任务A", "status": "pending"}]
    # 提醒注入过一次、第二次最终回复放行 END
    assert len(llm.calls) == 3
    assert reminded == [True]
    assert isinstance(result["messages"][-1], AIMessage)

    # todos 随 checkpointer 持久化：同 thread 第二次 invoke（新用户请求）仍可见
    llm2 = _ScriptedLLM([_final("新请求回答")])
    config2 = build_config(
        agent_doc, llm2, tools=[_todo_tool], middlewares=[], recursion_limit=10,
        final_answer_gate=_never,
    )
    config2["configurable"]["thread_id"] = "gate-3"
    state2 = {**base_state, "messages": [HumanMessage(content="新请求", id="u2")]}
    result2 = await graph.ainvoke(state2, config=config2)
    assert result2["todos"] == [{"content": "任务A", "status": "pending"}]
