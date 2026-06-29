"""ask_clarification 工具 — HITL 追问，直调 langgraph interrupt()。

三层工具模型第一层。工具函数内部调 interrupt(payload) 挂起 graph；
宿主收到 interrupt 事件，收集用户答案后 resume(Command(resume=answer))；
interrupt() 返回 answer，工具把它返回给 LLM。

依赖 react_node 放行 GraphInterrupt（v0.2-x 前提修正），否则 interrupt
会被工具执行的 except Exception 吞掉。
"""
from __future__ import annotations

from typing import Literal

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field


ClarificationType = Literal[
    "missing_info",
    "ambiguous_requirement",
    "approach_choice",
    "risk_confirmation",
    "suggestion",
]


class _ClarificationArgs(BaseModel):
    """ask_clarification 的 LLM 可见参数。"""

    question: str = Field(..., description="要问用户的澄清问题，要具体清晰")
    clarification_type: ClarificationType = Field(
        default="missing_info",
        description="澄清类型: missing_info/ambiguous_requirement/approach_choice/risk_confirmation/suggestion",
    )
    context: str | None = Field(
        default=None, description="为什么需要澄清的背景说明，帮助用户理解"
    )
    options: list[str] | None = Field(
        default=None, description="可选项列表（approach_choice/suggestion 时提供）"
    )


async def _ask_clarification(
    question: str,
    clarification_type: ClarificationType = "missing_info",
    context: str | None = None,
    options: list[str] | None = None,
) -> str:
    """向用户提问以获取澄清信息。执行会中断，等待用户回答后继续。

    工具直调 langgraph.interrupt() 挂起 graph。宿主 resume 时传入的值
    （用户答案）作为本函数返回值，交给 LLM 继续推理。
    """
    from langgraph.types import interrupt

    payload = {
        "question": question,
        "type": clarification_type,
        "context": context,
        "options": options,
    }
    # interrupt 挂起 graph；resume(Command(resume=answer)) 后返回 answer。
    # 答案类型由宿主决定（通常是 str）。
    answer = interrupt(payload)
    return answer if isinstance(answer, str) else str(answer)


ask_clarification = StructuredTool.from_function(
    _ask_clarification,
    name="ask_clarification",
    description=(
        "向用户提问以获取澄清信息。当你缺少必要信息、需求有歧义、有多种方案"
        "需要用户选择、或要进行有风险操作需要确认时使用。调用后执行会中断，"
        "等待用户回答后继续。"
    ),
    args_schema=_ClarificationArgs,
    coroutine=_ask_clarification,
)


__all__ = ["ask_clarification", "ClarificationType"]
