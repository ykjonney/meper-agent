"""Workflow tools — Agent invokes workflows via Task tools.

These tools are injected into every Agent's REACT loop as system-level
tools so the LLM can autonomously decide to search for workflow
templates, create Task instances, and query execution progress.

MVP stub implementations return realistic-looking data so the agent
can function end-to-end in development.  Real implementations that
connect to the Workflow Engine and Task Manager will be added in
Epics 4 and 9.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

from langchain_core.tools import BaseTool, tool
from loguru import logger


# ---------------------------------------------------------------------------
# Workflow tools (MVP stubs)
# ---------------------------------------------------------------------------


@tool
def search_workflow(query: str) -> str:
    """Search for published workflow templates matching *query*.

    Returns a JSON list of matching workflows with their IDs,
    descriptions, and input schemas.

    Args:
        query: Natural-language search terms describing the
            desired workflow (e.g. "quality report", "device
            inspection").
    """
    results = _match_workflows(query)
    return _format_workflow_results(results)


@tool
def create_task(workflow_id: str, params: str) -> str:
    """Create a Task instance from a published workflow template.

    Args:
        workflow_id: ID of the workflow template to instantiate
            (must be a published workflow).
        params: JSON string of input parameters matching the
            workflow's ``input_schema``.
    """
    task_id = f"task_{datetime.now(timezone.utc):%Y%m%d_%H%M%S}"
    logger.info("workflow_task_created", workflow_id=workflow_id, task_id=task_id)
    return (
        f'{{"task_id": "{task_id}", '
        f'"workflow_id": "{workflow_id}", '
        f'"status": "running", '
        f'"created_at": "{datetime.now(timezone.utc).isoformat()}"}}'
    )


@tool
def task_query(task_id: str) -> str:
    """Query the current execution status of a Task.

    Args:
        task_id: ID of the task to query (returned by ``create_task``).
    """
    logger.info("workflow_task_queried", task_id=task_id)
    return (
        f'{{"task_id": "{task_id}", '
        f'"status": "completed", '
        f'"progress": 100, '
        f'"result": "Task completed successfully.", '
        f'"completed_at": "{datetime.now(timezone.utc).isoformat()}"}}'
    )


_WORKFLOW_TOOLS: list[BaseTool] = [search_workflow, create_task, task_query]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _match_workflows(query: str) -> list[dict]:
    """Mock workflow search — returns canned results based on keywords.

    Real implementation will query the Workflow Registry (Epic 4).
    """
    _ = query  # MVP ignores the query and returns canned data
    return [
        {
            "id": "wf_quality_report",
            "name": "质检报告生成",
            "description": "根据检测数据生成标准质检报告，包含数据汇总、异常标记和结论建议。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "product_name": {"type": "string"},
                    "test_data": {"type": "string"},
                },
            },
        },
        {
            "id": "wf_device_inspection",
            "name": "设备巡检流程",
            "description": "按标准流程完成设备巡检，记录检查项结果并生成巡检报告。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "device_id": {"type": "string"},
                    "inspector": {"type": "string"},
                },
            },
        },
    ]


def _format_workflow_results(workflows: list[dict]) -> str:
    """Format workflow list as a JSON string for the LLM to consume."""
    import json

    return json.dumps(workflows, ensure_ascii=False)
