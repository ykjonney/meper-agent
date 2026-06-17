"""WorkflowRegistry — published workflow template metadata.

Each document represents a published workflow template that Agents
can search and instantiate as Tasks.

MongoDB collection: ``workflow_registry``
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.base import generate_id, utc_now


class WorkflowRegistryEntry(BaseModel):
    """A published workflow template entry in the registry."""

    id: str = Field(default_factory=lambda: generate_id("wfr"), alias="_id")
    workflow_id: str = ""  # Reference to the original workflow template
    name: str = ""
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)
    has_human_node: bool = False
    version: str = "1.0"
    tags: list[str] = Field(default_factory=list)
    published: bool = True
    published_at: datetime = Field(default_factory=utc_now)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    model_config = {
        "populate_by_name": True,
        "json_encoders": {datetime: lambda v: v.isoformat()},
    }
