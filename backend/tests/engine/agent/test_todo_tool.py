"""todo_write 工具测试 — 协程接线 / Command 写 state / 校验 / 门控 / 重注入。

回归要点：
- StructuredTool.from_function 必须显式 coroutine=（同 plan_tool 的坑）；
- 工具返回 Command（非 str）——todos 写 state channel、ToolMessage 进
  messages，两条更新一次完成；
- tool_call_id 是 InjectedToolArg：LLM 可见 schema 只含 todos；
- todo_final_gate 只认 state.todos（压缩免疫），全终态/空清单放行；
- TodoSalienceMiddleware 注入临时清单消息但不落持久化 state。
"""
from __future__ import annotations

import pytest
from app.engine.agent.todo_tool import (
    _render_confirmation,
    todo_final_gate,
    todo_write,
)
from app.engine.harness_integration.context import _resolve_builtin_tools
from app.engine.harness_integration.todo_middleware import TodoSalienceMiddleware
from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.types import Command
from pydantic import ValidationError

#: 基础清单（三态各一）。
_TODOS = [
    {"content": "分析代码", "status": "completed"},
    {"content": "编写测试", "status": "in_progress"},
    {"content": "更新文档", "status": "pending"},
]


async def _invoke(todos: list[dict], call_id: str = "c1"):
    """以完整 ToolCall 形式调用（InjectedToolCallId 的调用契约——
    ToolNode 运行时即按此形态构造）。"""
    return await todo_write.ainvoke({
        "name": "todo_write", "type": "tool_call", "id": call_id,
        "tool_call_id": call_id, "args": {"todos": todos},
    })


# ---------------------------------------------------------------------------
# 工具本体
# ---------------------------------------------------------------------------


def test_coroutine_wired() -> None:
    """协程接线：coroutine 已显式挂载（缺省 = 同步调用返回协程对象）。"""
    assert todo_write.coroutine is not None


def test_schema_hides_injected_arg() -> None:
    """InjectedToolArg：LLM 可见 schema 只含 todos，不含 tool_call_id。"""
    props = todo_write.tool_call_schema.model_json_schema()["properties"]
    assert "todos" in props
    assert "tool_call_id" not in props


async def test_ainvoke_returns_command_writing_state() -> None:
    """ainvoke → Command：todos 全量写入 + 确认 ToolMessage 配对。"""
    result = await _invoke(_TODOS, "call_1")
    assert isinstance(result, Command)
    update = result.update
    assert update["todos"] == _TODOS
    (msg,) = update["messages"]
    assert isinstance(msg, ToolMessage)
    assert msg.tool_call_id == "call_1"
    assert "清单已更新" in msg.content
    for content in ("分析代码", "编写测试", "更新文档"):
        assert content in msg.content


async def test_ainvoke_empty_list_clears() -> None:
    """空列表 = 清空清单（诚实出口：任务闭环）。"""
    result = await _invoke([], "call_2")
    assert result.update["todos"] == []
    assert "清单已清空" in result.update["messages"][0].content


async def test_ainvoke_rejects_invalid_status() -> None:
    """非法 status 被 pydantic 拒（不静默落库脏数据）。"""
    with pytest.raises(ValidationError):
        await _invoke([{"content": "x", "status": "cancelled"}])


async def test_ainvoke_rejects_blank_content() -> None:
    """空 content 被拒。"""
    with pytest.raises(ValidationError):
        await _invoke([{"content": ""}])


async def test_ainvoke_rejects_oversized() -> None:
    """>50 项 / 超 200 字符 content 被拒。"""
    with pytest.raises(ValidationError):
        await _invoke([{"content": f"任务{i}"} for i in range(51)])
    with pytest.raises(ValidationError):
        await _invoke([{"content": "长" * 201}])


def test_render_confirmation_summary() -> None:
    """确认文案自包含：统计行 + 逐项（recall_tool_result 可恢复）。"""
    text = _render_confirmation(_TODOS)
    assert "3 项" in text
    assert "1已完成" in text and "1进行中" in text and "1待办" in text


# ---------------------------------------------------------------------------
# todo_final_gate — 回合结束门控（读 state，压缩免疫）
# ---------------------------------------------------------------------------


async def test_gate_fires_on_pending() -> None:
    """有 pending / in_progress → 返回提醒文案。"""
    reminder = await todo_final_gate({"todos": _TODOS}, response=None)
    assert reminder is not None
    assert "未完成" in reminder
    assert "编写测试" in reminder and "更新文档" in reminder
    assert "分析代码" not in reminder  # 已完成项不进提醒


async def test_gate_passes_when_all_done() -> None:
    """全终态 → 放行（None）。"""
    assert await todo_final_gate(
        {"todos": [{"content": "a", "status": "completed"}]}, response=None
    ) is None


async def test_gate_passes_when_empty_or_missing() -> None:
    """空清单 / 无 todos 字段（旧 thread 向后兼容）→ 放行。"""
    assert await todo_final_gate({"todos": []}, response=None) is None
    assert await todo_final_gate({}, response=None) is None


async def test_gate_tolerates_dirty_items() -> None:
    """非 dict 脏数据跳过，不炸。"""
    reminder = await todo_final_gate(
        {"todos": ["garbage", {"content": "a", "status": "pending"}]},
        response=None,
    )
    assert reminder is not None


# ---------------------------------------------------------------------------
# TodoSalienceMiddleware — 每次调用 LLM 前的临时重注入
# ---------------------------------------------------------------------------


async def test_middleware_injects_when_todos_present() -> None:
    """todos 非空 → 追加临时清单消息；原 messages 不被修改（不落 history）。"""
    mw = TodoSalienceMiddleware()
    original = [HumanMessage(content="hi", id="u1")]
    state = {"messages": original, "todos": _TODOS}
    patched = await mw.before_llm(state)  # type: ignore[arg-type]
    assert len(patched["messages"]) == 2
    injected = patched["messages"][-1]
    assert "当前任务清单" in injected.content
    assert "编写测试" in injected.content
    # 原列表不动（浅拷贝追加，state 本体无副作用）
    assert len(original) == 1
    assert state["messages"] is original


async def test_middleware_noop_when_empty() -> None:
    """todos 空 → 原样返回（首步未建清单时不注入）。"""
    mw = TodoSalienceMiddleware()
    state = {"messages": [HumanMessage(content="hi")], "todos": []}
    patched = await mw.before_llm(state)  # type: ignore[arg-type]
    assert patched is state


# ---------------------------------------------------------------------------
# 注入与声明（防漂移：运行时工具集 ↔ /tools/builtin ↔ system prompt）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("context", ["chat", "workflow", "plan"])
def test_injected_in_all_contexts(context: str) -> None:
    """三上下文均注入 todo_write（始终开启型，不进剥离名单）。"""
    tools = _resolve_builtin_tools({"builtin_config": []}, context)
    assert "todo_write" in [t.name for t in tools]


async def test_declaration_has_no_task_tracking_section() -> None:
    """todo_write 用法规则单一事实源=工具 description,prompt 不再重复表达。

    「### Task Tracking」段已移除——防回归:若有人把 usage 规则加回 prompt
    （与 description 重复,每轮多注入 ~600 字符）,此测试失败。
    """
    from app.engine.agent.builder import build_tool_declaration

    agent = {"builtin_config": ["bash"], "agent_id": "a1"}
    for context in ("chat", "workflow"):
        decl = await build_tool_declaration(agent, execution_context=context)
        assert "### Task Tracking" not in decl
