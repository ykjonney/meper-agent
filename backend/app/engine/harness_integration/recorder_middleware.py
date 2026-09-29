"""RecorderMiddleware — app 层观察钩子,把 LLM/工具过程喂给 ExecutionRecorder。

与 harness 的 UsageMiddleware 观察同一组钩子（before/after_llm、
before/after_tool）,在 graph 内部运行——因此 **stream 和 invoke 两种执行
路径都被覆盖**（AppEvent 管线只覆盖 stream）。token 提取复用
UsageMiddleware 的静态方法,保证与顶层指标同源同口径。

只观察不改写：所有钩子原样返回入参。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agent_flow_harness.state import AgentState
    from langchain_core.messages import BaseMessage

from agent_flow_harness.middleware.builtin.usage import UsageMiddleware

from app.services.execution_recorder import ExecutionRecorder


class RecorderMiddleware:
    """把 request/tool 过程事件喂给 recorder（execution_log.events 事实源）。"""

    name = "app_recorder"
    order = 60  # 在 usage(50) 之后——不竞争,纯旁路观察

    def __init__(self, recorder: ExecutionRecorder) -> None:
        self._recorder = recorder

    async def before_llm(self, state: AgentState) -> AgentState:
        self._recorder.request_begin()
        return state

    async def after_llm(self, state: AgentState, response: BaseMessage) -> AgentState:
        # 与 UsageMiddleware 同源提取：优先 usage_metadata,兼容
        # response_metadata 的 OpenAI/Anthropic 格式。
        usage = UsageMiddleware._extract_usage_metadata(response)
        if usage.get("total", 0) == 0:
            meta = getattr(response, "response_metadata", None) or {}
            usage = UsageMiddleware._extract_usage(meta)
        self._recorder.request_end(usage.get("input", 0), usage.get("output", 0))
        return state

    async def before_tool(
        self, state: AgentState, tool_call: dict[str, Any]
    ) -> dict[str, Any]:
        tc = tool_call or {}
        self._recorder.tool_call(tc.get("id", ""), tc.get("name", ""), tc.get("args"))
        return tool_call

    async def after_tool(
        self, state: AgentState, tool_call: dict[str, Any], result: str
    ) -> AgentState:
        tc = tool_call or {}
        content = result if isinstance(result, str) else str(result)
        self._recorder.tool_result(tc.get("id", ""), tc.get("name", ""), content)
        return state


__all__ = ["RecorderMiddleware"]
