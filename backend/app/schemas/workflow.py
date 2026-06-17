"""Pydantic schemas for Workflow template CRUD operations."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.workflow import WorkflowNode, WorkflowStatus


class WorkflowCreate(BaseModel):
    """Request body for creating a new Workflow template."""

    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="", max_length=1000)
    tags: list[str] = Field(default_factory=list)


class WorkflowUpdate(BaseModel):
    """Request body for updating a Workflow template."""

    name: str | None = None
    description: str | None = None
    nodes: list[WorkflowNode] | None = None
    edges: list[dict[str, Any]] | None = None
    tags: list[str] | None = None


class WorkflowNodeResponse(BaseModel):
    """A single node in API responses."""

    node_id: str
    type: str
    label: str
    config: dict[str, Any] = Field(default_factory=dict)
    position: dict[str, float] = Field(default_factory=lambda: {"x": 0, "y": 0})


class WorkflowEdgeResponse(BaseModel):
    """DEPRECATED: kept for backward-compat read. New data uses node.config.next_nodes."""

    edge_id: str
    source: str
    target: str
    label: str = ""
    condition: str | None = None


class WorkflowResponse(BaseModel):
    """Full Workflow template response."""

    id: str
    name: str
    description: str = ""
    status: WorkflowStatus
    version: int = 1
    nodes: list[WorkflowNodeResponse] = Field(default_factory=list)
    edges: list[WorkflowEdgeResponse] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    created_by: str = ""
    created_at: datetime
    updated_at: datetime


class WorkflowSummary(BaseModel):
    """Compact Workflow response for list queries."""

    id: str
    name: str
    description: str = ""
    status: WorkflowStatus
    version: int = 1
    node_count: int = 0
    tags: list[str] = Field(default_factory=list)
    created_by: str = ""
    created_at: datetime
    updated_at: datetime


class WorkflowListResponse(BaseModel):
    """Paginated Workflow list response."""

    total: int = 0
    page: int = 1
    page_size: int = 20
    items: list[WorkflowSummary] = Field(default_factory=list)
