"""Trigger — independent scheduled trigger document.

MongoDB collection: ``triggers``

Each trigger binds ``user_id`` + ``workflow_id``. A compound unique index
ensures one trigger per (user, workflow) pair. ``schedule_version`` is
incremented on every config change so stale Celery tasks can detect and
skip themselves.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.base import generate_id, utc_now


class Trigger(BaseModel):
    """Independent scheduled trigger document."""

    id: str = Field(default_factory=lambda: generate_id("trig"), alias="_id")
    # 双目标：workflow_id / agent_id 恰好其一非空（schema 层校验）。
    workflow_id: str = ""
    agent_id: str = ""
    # agent 目标的执行指令（每期到期以 {"instruction": ...} fork 任务）
    instruction: str = ""
    user_id: str  # creator, also used as created_by at execution time
    type: str  # "cron" | "once"
    enabled: bool = False
    cron_expression: str | None = None
    execute_at: datetime | None = None
    default_input: dict[str, Any] = Field(default_factory=dict)
    schedule_version: int = 0  # incremented on every config update
    last_triggered_at: datetime | None = None
    next_trigger_at: datetime | None = None
    celery_task_id: str | None = None  # pending Celery task ID (for revocation)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    model_config = {"populate_by_name": True}
