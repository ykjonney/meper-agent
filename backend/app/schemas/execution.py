"""Execution-related Pydantic schemas for invoke/stream API."""
from __future__ import annotations

from pydantic import BaseModel, Field


class ExecutionRequest(BaseModel):
    """Request body for agent invoke/stream endpoints."""

    input: str = Field(..., min_length=1, max_length=50000, description="User input text")
    session_id: str | None = Field(default=None, description="Optional session ID for context continuity")
    enable_thinking: bool = Field(
        default=False,
        description="启用 LLM 原生推理（Claude extended thinking / OpenAI o-series reasoning_effort）。"
        "不支持的模型会静默降级到普通模式。",
    )


class ExecutionResponse(BaseModel):
    """Response from a synchronous agent invocation."""

    output: str = Field(..., description="Agent response text")
    execution_path: str = Field(..., description="Selected execution path")
    request_id: str = Field(..., description="Trace ID for this execution")
    agent_id: str = Field(..., description="Agent ID")
    session_id: str = Field(..., description="Associated session ID for this conversation")
    step_count: int = Field(default=0, description="Number of execution steps taken")
