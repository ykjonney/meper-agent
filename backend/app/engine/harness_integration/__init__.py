"""应用层 ↔ harness Integration Adapter。

本模块是 session→thread 迁移的接线层,确立"应用层如何调用 harness"的模式。

三层架构:
    ① API 层 (FastAPI)         app/api/v1/*          只懂 HTTP + 业务语义
    ② Integration Adapter 层   app/engine/harness_integration  本模块
    ③ harness                  agent_flow_harness    纯净,不认 app.*

核心函数:
    - get_checkpointer:        返回 harness checkpointer 单例
    - resolve_harness_context: 装配 LLM/工具/sandbox/workspace 为 harness 注入物
    - release_harness_context: 释放 contextvar token
    - stream / invoke:         流式/非流式执行 harness graph
    - resume:                  恢复被 interrupt 挂起的 graph
"""
from __future__ import annotations

from app.engine.harness_integration.context import (
    get_checkpointer,
    release_harness_context,
    resolve_harness_context,
)
from app.engine.harness_integration.execution import (
    invoke,
    resume,
    resume_agent,
    stream,
)

__all__ = [
    "get_checkpointer",
    "invoke",
    "release_harness_context",
    "resolve_harness_context",
    "resume",
    "resume_agent",
    "stream",
]
