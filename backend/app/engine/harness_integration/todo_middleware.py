"""TodoSalienceMiddleware — 每次调用 LLM 前临时重注入当前任务清单。

Manus "todo.md 每步重读" 的等价实现：清单事实源在 state["todos"]（压缩
免疫），但模型只能看见 messages——本中间件在 before_llm 把最新清单作为
一条临时消息追加到**本次调用输入**（llm_node 使用 before_llm 返回值、
不落 history），无论压缩与否模型永远看得见清单。

不落 history 的两个原因：① 清单会随进度反复变化，逐条落盘会在 messages
里堆砌历史版本噪音；② 事实源已在 state.todos，消息里只保留 todo_write
的调用/确认（timeline 展示 + 模型即时反馈用）。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from langchain_core.messages import HumanMessage

if TYPE_CHECKING:
    from agent_flow_harness.state import AgentState

from app.engine.agent.todo_tool import _render_items


class TodoSalienceMiddleware:
    """每次 LLM 调用前临时注入「当前任务清单」（不落 history）。"""

    name = "todo_salience"
    order = 70  # 在 usage(50)/app_recorder(60) 之后——改写型钩子靠后

    async def before_llm(self, state: AgentState) -> AgentState:
        todos = state.get("todos") or []
        if not todos:
            return state
        content = (
            "[系统注入·当前任务清单]\n"
            f"{_render_items([t for t in todos if isinstance(t, dict)])}\n"
            "（继续按清单推进：完成一项标 completed，不再需要一项就移除，"
            "全部完成后调用 todo_write 传空列表清空）"
        )
        # 浅拷贝追加：只影响本次 LLM 调用输入，state 本体与 messages 不变。
        patched: AgentState = {**state}
        patched["messages"] = [*(state.get("messages") or []), HumanMessage(content=content)]
        return patched

    async def after_llm(self, state: AgentState, response: Any) -> AgentState:
        return state

    async def before_tool(
        self, state: AgentState, tool_call: dict[str, Any]
    ) -> dict[str, Any]:
        return tool_call

    async def after_tool(
        self, state: AgentState, tool_call: dict[str, Any], result: str
    ) -> AgentState:
        return state


__all__ = ["TodoSalienceMiddleware"]
