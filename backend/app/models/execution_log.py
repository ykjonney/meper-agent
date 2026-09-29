"""Execution log model — unified per-call agent execution records.

Each document records a single agent invocation (invoke / stream / resume)
across all access channels. This collection is independent of ``sessions``
and ``messages``: deleting a session does not remove its execution history
here, so statistics remain accurate.

Channels are distinguished by ``source``:
- ``internal`` — platform users (JWT auth, frontend login)
- ``api_key``  — third-party widget / ext API callers
- ``im``       — IM channel users (Lark / DingTalk)

TTL: documents auto-expire after 365 days (see service ensure_indexes).
The ``timestamp`` field MUST be stored as a BSON date for TTL to work.
"""
from typing import Any

from pydantic import BaseModel, Field
from pydantic.config import ConfigDict

from app.models.base import generate_id, utc_now


class ExecutionLog(BaseModel):
    """One agent execution call (append-only, channel-agnostic)."""

    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(default_factory=lambda: generate_id("xlog"), alias="_id")

    # ── Source / channel ──
    source: str = Field(..., description="internal | api_key | im")
    user_id: str = Field(default="", description="调用者 user_id（含通道前缀）")

    # ── Call context ──
    agent_id: str = Field(default="")
    session_id: str = Field(default="", description="关联 session（session 删除后变孤儿但不影响统计）")
    request_id: str = Field(default="")

    # ── External-specific (source=api_key) ──
    api_key_id: str = Field(default="")
    endpoint: str = Field(default="", description="逻辑端点，如 agents:invoke:stream")

    # ── IM-specific (source=im) ──
    channel_id: str = Field(default="", description="IM 渠道 ID")

    # ── Result ──
    status: str = Field(default="success", description="success | error")
    status_code: int = Field(default=0)
    latency_ms: int = Field(default=0, description="调用耗时（毫秒）")
    llm_duration_ms: int = Field(default=0, description="LLM 调用总耗时（毫秒）")
    tool_duration_ms: int = Field(default=0, description="工具执行总耗时（毫秒）")
    other_duration_ms: int = Field(default=0, description="其他耗时（代码/框架延迟，= latency - llm - tool）")
    ttft_ms: int = Field(default=0, description="首 token 延迟（毫秒，仅流式）")

    # ── Token consumption ──
    total_tokens: int = Field(default=0)
    input_tokens: int = Field(default=0)
    output_tokens: int = Field(default=0)
    llm_calls: int = Field(default=0)

    # ── Process events（过程事件，ExecutionRecorder 产出）──
    # 一次执行的过程流水账：request 边界/工具调用元数据/压缩/中断/错误。
    # 与 messages 的分工：正文归 messages（这里只有 size/预览），过程归这里
    # （messages 放不下时刻/耗时/请求边界）。IM 渠道与工作流节点没有
    # messages 明细，events 是那里唯一的执行记录；会话删除后审计过程
    # 仍存续（与本 collection "统计独立于会话" 的定位一致）。
    # 上限由 recorder 保证（≤500 条 / 序列化 ≤16KB，超限丢中段工具事件
    # 并自声明 events_truncated）。
    events: list[dict[str, Any]] = Field(default_factory=list)

    # ── BSON date for TTL index ──
    timestamp: Any = Field(default_factory=utc_now)
