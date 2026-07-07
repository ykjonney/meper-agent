"""Workflow template — the DAG definition for a workflow.

Each workflow template contains a list of nodes and edges that
define the DAG structure, along with metadata like name, description,
model configuration, and version info.

MongoDB collection: ``workflows``
"""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from app.models.base import generate_id, utc_now


class WorkflowStatus(StrEnum):
    """Workflow template lifecycle status."""

    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class WorkflowNode(BaseModel):
    """A single node in the workflow DAG."""

    node_id: str = ""
    type: str = "start"  # start | end | agent | tool | gateway | parallel | human | subflow
    label: str = ""
    config: dict[str, Any] = Field(default_factory=dict)
    position: dict[str, float] = Field(default_factory=lambda: {"x": 0, "y": 0})


class WorkflowEdge(BaseModel):
    """DEPRECATED: kept for backward-compat read. New data uses node.config.next_nodes.

    Legacy routing: independent edge objects (source/target/condition).
    """

    edge_id: str = ""
    source: str = ""
    target: str = ""
    label: str = ""
    condition: str | None = None  # expression for conditional edges


class TriggerConfig(BaseModel):
    """Workflow 定时触发配置"""

    type: str  # "cron" | "once"
    enabled: bool = False
    cron_expression: str | None = None
    execute_at: datetime | None = None
    default_input: dict[str, Any] = Field(default_factory=dict)
    last_triggered_at: datetime | None = None
    next_trigger_at: datetime | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class Workflow(BaseModel):
    """MongoDB workflow template document."""

    id: str = Field(default_factory=lambda: generate_id("wf"), alias="_id")
    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="", max_length=1000)
    status: WorkflowStatus = WorkflowStatus.DRAFT
    version: int = 1
    nodes: list[WorkflowNode] = Field(default_factory=list)
    edges: list[WorkflowEdge] = Field(
        default_factory=list,
        description="DEPRECATED: kept for backward-compat. New workflows store routing in node.config.next_nodes.",
    )
    tags: list[str] = Field(default_factory=list)
    created_by: str = ""
    trigger_config: TriggerConfig | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    model_config = {
        "populate_by_name": True,
        "json_encoders": {datetime: lambda v: v.isoformat()},
    }
