"""Interaction 模块 — 第一层能力型内建工具 (v0.2-x 三层工具模型第一层)。

ask_clarification: HITL 追问，工具直调 langgraph interrupt() 挂起执行，
  宿主 resume 时传用户答案，工具返回答案给 LLM。
request_app_authorization: HITL 按需授权——MCP 工具报「用户尚未授权
  应用」后，LLM 调它挂起执行请求用户完成授权（同 interrupt 机制）。
tool_search: 按关键词检索可用工具，读 TOOL_REGISTRY 单例。

设计见 docs/implementation-artifacts/v0-2-x-tool-registry-enhancement.md。
"""
from agent_flow_harness.interaction.app_authorization import (
    request_app_authorization,
)
from agent_flow_harness.interaction.clarification import (
    ClarificationField,
    ask_clarification,
)
from agent_flow_harness.interaction.tool_search import tool_search

__all__ = [
    "ask_clarification",
    "ClarificationField",
    "request_app_authorization",
    "tool_search",
]
