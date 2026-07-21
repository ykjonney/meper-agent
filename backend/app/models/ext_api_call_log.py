"""External API call log data model.

Each document records a single external API call (one row per HTTP request
to ``/api/v1/ext/*``). Used for:
1. Audit / debugging — full call trail per API Key / user / session
2. Token statistics — per-user and per-API-Key token consumption
3. Aggregations — by endpoint / by user / by time window

Workflow path note: tasks triggered by an agent carry their own
``total_tokens`` on the task document and a ``source_session_id`` linking
back to the originating session. They are NOT logged here (workflow
completion happens in a Celery worker, cross-process). To compute the
full session consumption, join ``ext_api_call_logs`` with ``tasks`` via
``session_id`` / ``source_session_id``.

TTL: documents auto-expire after 90 days (see service ensure_indexes).
The ``timestamp`` field MUST be stored as a BSON date for TTL to work.
"""
from typing import Any

from pydantic import BaseModel, Field
from pydantic.config import ConfigDict

from app.models.base import generate_id, utc_now


class ExtApiCallLog(BaseModel):
    """One external API call (event-stream entry, append-only)."""

    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(default_factory=lambda: generate_id("elog"), alias="_id")

    # ── Caller identity ──
    api_key_id: str
    owner_user_id: str
    user_sub: str = Field(default="", description="终端用户 sub (回调验证模式)")
    visitor_id: str = Field(default="", description="visitor_id (兼容模式)")
    auth_mode: str = Field(default="legacy", description="callback | legacy")

    # ── Call context ──
    endpoint: str = Field(default="", description="逻辑端点,如 agents:invoke:stream")
    agent_id: str = Field(default="")
    workflow_id: str = Field(default="")
    session_id: str = Field(default="")
    task_id: str = Field(default="")
    request_id: str = Field(default="")

    # ── Result ──
    status: str = Field(default="success", description="success | error")
    status_code: int = Field(default=0)
    error_code: str = Field(default="")
    latency_ms: int = Field(default=0)

    # ── Token consumption (backfilled in phase 2; 0 if not an agent call) ──
    total_tokens: int = Field(default=0)
    input_tokens: int = Field(default=0)
    output_tokens: int = Field(default=0)
    llm_calls: int = Field(default=0)

    # ── BSON date for TTL index — MUST be datetime, not ISO string ──
    timestamp: Any = Field(default_factory=lambda: utc_now())
