"""Subagents 模块 — 多 Agent 协作调度 (v0.2-1)。

主 Agent 通过 delegate_to_subagent 工具委派子任务给预注册的子 Agent。
子 Agent 完全隔离 stateless 执行，返回最终文本。设计见
docs/implementation-artifacts/v0-2-1-subagents.md。
"""
from agent_flow_harness.subagents.context import (
    SubAgentContext,
    get_subagent_context,
    reset_subagent_context,
    set_subagent_context,
)
from agent_flow_harness.subagents.delegate import delegate_to_subagent, extract_final_text
from agent_flow_harness.subagents.registry import SubAgentRegistry
from agent_flow_harness.subagents.spec import SubAgentSpec

__all__ = [
    "SubAgentContext",
    "SubAgentRegistry",
    "SubAgentSpec",
    "delegate_to_subagent",
    "extract_final_text",
    "get_subagent_context",
    "reset_subagent_context",
    "set_subagent_context",
]
