"""todo_write 工具 — agent 自用任务清单（Claude Code TodoWrite 同构）+ 完成度门控。

三层机制：
1. 状态源：清单全量写入 LangGraph state 的 ``todos`` channel（工具返回
   ``Command(update=...)``）。checkpointer 按 thread_id 持久化整个 state，
   上下文压缩只重写 messages channel——清单不会因上下文过长丢失。
   生命周期绑定会话/任务：``SessionService.delete_session`` 按
   ``thread_id == session_id`` 清理 checkpoints、``TaskService.delete_task``
   按 ``^{task_id}_`` 前缀清理，todos 随之删除（若未来把存储挪出
   checkpointer，须在两处删除入口补级联）。
2. 显著性：TodoSalienceMiddleware（harness_integration/todo_middleware.py）
   每次调用 LLM 前临时注入最新清单，模型永远看得见。
3. 强制：``todo_final_gate`` 经 harness 的 final_answer_gate 机制在最终
   回复落定前检查未完成项，注入提醒续跑（每用户轮 ≤2 次，harness 侧限次）。

语义：全量替换——每次调用传完整清单；不再相关的项直接移除（诚实出口），
全部完成后传空列表清空（清空后重注入与门控随之停摆 = 任务闭环）。
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool, InjectedToolCallId, StructuredTool
from langgraph.types import Command
from pydantic import BaseModel, Field

# 三态（同 Claude Code TodoWrite）：pending / in_progress / completed。
# 「做不了」的诚实出口是移除该项（全量替换语义），不引入 cancelled 态。
_TODO_STATUSES: tuple[str, ...] = ("pending", "in_progress", "completed")

_STATUS_LABELS: dict[str, str] = {
    "pending": "待办",
    "in_progress": "进行中",
    "completed": "已完成",
}


class _TodoItem(BaseModel):
    """单条待办。content 粗粒度、可演化（一步能说清做什么即可）。"""

    content: str = Field(min_length=1, max_length=200)
    status: Literal["pending", "in_progress", "completed"] = "pending"


class _TodoWriteArgs(BaseModel):
    """todo_write 参数。tool_call_id 由 ToolNode 注入（模型不可见）。"""

    todos: list[_TodoItem] = Field(
        max_length=50, description="完整清单（全量替换），空列表 = 清空"
    )
    # InjectedToolCallId（非泛型 InjectedToolArg）——langchain 专用于
    # tool_call_id 的注入注解：schema 过滤 + 调用时自动注入。
    tool_call_id: Annotated[str, InjectedToolCallId]


def _render_items(items: list[dict[str, Any]]) -> str:
    """逐项渲染状态行（工具确认文案与门控提醒共用）。"""
    lines = []
    for item in items:
        label = _STATUS_LABELS.get(item.get("status", ""), item.get("status", "?"))
        lines.append(f"- [{label}] {item.get('content', '')}")
    return "\n".join(lines)


def _render_confirmation(items: list[dict[str, Any]]) -> str:
    """工具确认文案：自包含（统计 + 逐项），压缩后可被 recall_tool_result 恢复。"""
    if not items:
        return "清单已清空。"
    counts = dict.fromkeys(_TODO_STATUSES, 0)
    for item in items:
        status = item.get("status")
        if status in counts:
            counts[status] += 1
    summary = " / ".join(
        f"{counts[s]}{_STATUS_LABELS[s]}" for s in _TODO_STATUSES if counts[s]
    )
    return f"清单已更新（{len(items)} 项：{summary}）：\n{_render_items(items)}"


async def _todo_write(
    todos: list[_TodoItem],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command[Any]:
    """写入任务清单（全量替换 state.todos），返回确认 ToolMessage。"""
    items = [t.model_dump() for t in todos]
    return Command(
        update={
            "todos": items,
            "messages": [
                ToolMessage(
                    content=_render_confirmation(items),
                    name="todo_write",
                    tool_call_id=tool_call_id,
                )
            ],
        }
    )


todo_write = StructuredTool.from_function(
    _todo_write,
    name="todo_write",
    args_schema=_TodoWriteArgs,
    description=(
        "管理当前任务清单，跟踪多步任务进度。开工前建立清单，随进度更新："
        "每次调用传完整清单（全量替换语义）；同时只保留一项 in_progress；"
        "完成一项立即标 completed；不再相关的项直接移除；全部完成后传空列表"
        "清空。清单会在你每次思考前向你展示；还有未完成项时结束回合会被系统"
        "提醒并要求继续。仅对 3 步及以上的多步任务使用，简单问答/单步任务"
        "不要建清单。"
    ),
    # 异步函数必须显式挂 coroutine——from_function 不做协程自动识别,
    # 缺省会把 async 函数当同步 func 调用,返回未 await 的协程对象。
    # 与 ask_clarification / propose_plan 的构造方式一致。
    coroutine=_todo_write,
)

# ---------------------------------------------------------------------------
# Tool list — 始终开启的能力型工具（同 view_image / recall_tool_result 模式，
# 进 _INJECTED_BUILTIN_TOOL_NAMES 但不进 _CONFIGURABLE_BUILTIN_TOOL_NAMES）
# ---------------------------------------------------------------------------

_TODO_TOOLS: list[BaseTool] = [todo_write]

#: name → tool 实例查找表（context.py 注入与 /tools/builtin 端点共用）。
TODO_TOOL_BY_NAME: dict[str, BaseTool] = {t.name: t for t in _TODO_TOOLS}


# ---------------------------------------------------------------------------
# Final-answer gate — 未完成待办的回合结束门控（app 层语义）
# ---------------------------------------------------------------------------


def _pending_items(todos: list[Any]) -> list[dict[str, Any]]:
    """筛出未完成项（pending / in_progress）；容忍非 dict 的脏数据。"""
    return [
        item
        for item in todos
        if isinstance(item, dict)
        and item.get("status") in ("pending", "in_progress")
    ]


async def todo_final_gate(state: Any, response: Any) -> str | None:
    """harness final_answer_gate 的 todo 语义实现。

    最终回复（无 tool_call）落定前调用：state["todos"] 存在未完成项则返回
    提醒文案（harness 注入为 HumanMessage 并续跑）；清单为空/全部完成返回
    None 放行。读 state channel 而非扫 messages——压缩免疫。
    """
    todos = (state.get("todos") if isinstance(state, dict) else None) or []
    pending = _pending_items(todos)
    if not pending:
        return None
    n_doing = sum(1 for i in pending if i.get("status") == "in_progress")
    n_todo = len(pending) - n_doing
    parts = []
    if n_doing:
        parts.append(f"{n_doing} 项进行中")
    if n_todo:
        parts.append(f"{n_todo} 项待办")
    return (
        f"系统提醒：任务清单还有未完成项（{'、'.join(parts)}），不能就此结束：\n"
        f"{_render_items(pending)}\n"
        "请继续完成这些任务；已不再需要的项调用 todo_write 从清单中移除；"
        "全部完成后调用 todo_write 传空列表清空清单，再给出最终回复。"
    )


__all__ = [
    "TODO_TOOL_BY_NAME",
    "_TODO_TOOLS",
    "todo_final_gate",
    "todo_write",
]
