"""Task data model for MongoDB — runtime workflow instance with state machine."""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from app.models.base import generate_id, utc_now


class TaskStatus(StrEnum):
    """Task runtime state — 6 states, no foreground/background mode."""

    PENDING = "pending"
    RUNNING = "running"
    WAITING_HUMAN = "waiting_human"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# Map: current_status -> list of allowed next statuses
TRANSITION_MAP: dict[TaskStatus, list[TaskStatus]] = {
    TaskStatus.PENDING: [TaskStatus.RUNNING, TaskStatus.CANCELLED],
    TaskStatus.RUNNING: [
        TaskStatus.WAITING_HUMAN,
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,  # 运行中可取消（优雅挂起，可恢复）
    ],
    TaskStatus.WAITING_HUMAN: [TaskStatus.RUNNING, TaskStatus.FAILED, TaskStatus.CANCELLED],
    TaskStatus.COMPLETED: [],  # terminal
    TaskStatus.FAILED: [TaskStatus.RUNNING],  # 允许 retry（直接重新执行）
    TaskStatus.CANCELLED: [TaskStatus.RUNNING],  # 可恢复（CANCELLED 即暂停）
}

TERMINAL_STATUSES = {TaskStatus.COMPLETED, TaskStatus.FAILED}


def is_valid_transition(from_status: TaskStatus, to_status: TaskStatus) -> bool:
    """Check whether *to_status* is reachable from *from_status*."""
    return to_status in TRANSITION_MAP.get(from_status, [])


class TimelineEvent(BaseModel):
    """A single event in the Task execution timeline."""

    timestamp: datetime = Field(default_factory=utc_now)
    event_type: str  # created, started, node_start, node_complete, waiting_human, human_action, completed, failed, cancelled, intervened
    data: dict[str, Any] = Field(default_factory=dict)
    actor: str = "system"


class TaskError(BaseModel):
    """Structured error information for failed Tasks."""

    node_id: str | None = None
    node_type: str | None = None
    error_message: str = ""
    error_code: str = ""
    timestamp: datetime = Field(default_factory=utc_now)


class Checkpoint(BaseModel):
    """Workflow execution checkpoint for resume after human pause.

    Persisted when a workflow pauses at a Human node, so that on resume
    the engine can restore variable pool state and continue from downstream
    nodes without re-executing the entire workflow.
    """

    paused_at_node: str                                          # Human 节点 ID
    completed_nodes: list[str] = Field(default_factory=list)     # 已完成节点列表
    variable_snapshot: dict[str, Any] = Field(default_factory=dict)  # VariablePool.snapshot()
    paused_at: datetime = Field(default_factory=utc_now)
    human_context: dict[str, Any] = Field(default_factory=dict)  # {node_id, title, description, options, timeout_ms, timeout_action}
    timeout_deadline: datetime | None = None                     # 超时截止时间
    timeout_action: str = "fail"
    # 取消（暂停）时被中断的 Agent 节点的 LangGraph thread_id。
    # 恢复时用 Command(resume) 续接该 thread，保持 REACT 循环上下文连贯。
    agent_thread_id: str = ""


class Task(BaseModel):
    """MongoDB Task document — runtime workflow instance.

    Follows the same pattern as ``Agent`` — raw Pydantic model,
    serialized to dict for MongoDB insertion/update.
    """

    id: str = Field(default_factory=lambda: generate_id("task"), alias="_id")
    workflow_id: str = Field(..., max_length=100)
    workflow_version: str = Field(default="", max_length=20)
    status: TaskStatus = TaskStatus.PENDING
    input: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] | None = None
    variables: dict[str, Any] = Field(default_factory=dict)
    variable_snapshots: list[dict[str, Any]] = Field(default_factory=list)
    call_chain: list[str] = Field(default_factory=list)
    parent_task_id: str | None = None
    created_by: str = Field(default="", max_length=100)
    created_by_type: str = Field(default="user", pattern=r"^(user|agent|system|api_key)$")
    version: int = Field(default=1, ge=1)
    timeline: list[TimelineEvent] = Field(default_factory=list)
    error: TaskError | None = None
    checkpoint: Checkpoint | None = None
    source: str = Field(default="manual", pattern=r"^(manual|trigger|trigger_scheduled)$")
    trigger_id: str | None = None
    scheduled_at: datetime | None = None
    # Celery AsyncResult ID，用于取消时 revoke 正在运行的 worker（兜底 SIGTERM）
    celery_task_id: str = ""
    # 本次 task 所有 agent 节点累计 token 用量（engine 完成时写回）
    total_tokens: int = Field(default=0, ge=0)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    model_config = {"populate_by_name": True}
