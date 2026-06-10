"""Tests for the workflow tools (search_workflow, create_task, task_query)."""
import pytest

from app.engine.agent.workflow_executor import (
    _WORKFLOW_TOOLS,
    create_task,
    search_workflow,
    task_query,
)


class TestWorkflowTools:
    """Workflow tools — search_workflow, create_task, task_query."""

    def test_search_workflow_returns_results(self):
        """Should return matching workflows for a query."""
        result = search_workflow.invoke({"query": "quality report"})
        assert "wf_quality_report" in result
        assert "质检报告生成" in result

    def test_create_task_returns_task_id(self):
        """Should create a task and return its ID."""
        result = create_task.invoke(
            {
                "workflow_id": "wf_quality_report",
                "params": '{"product_name": "Widget-A"}',
            }
        )
        assert "task_id" in result
        assert "running" in result

    def test_task_query_returns_status(self):
        """Should return task status."""
        result = task_query.invoke({"task_id": "task_20260609_120000"})
        assert "completed" in result
        assert "task_id" in result

    def test_workflow_tools_list_contains_three_tools(self):
        """_WORKFLOW_TOOLS should export all three tools."""
        assert len(_WORKFLOW_TOOLS) == 3
        names = {t.name for t in _WORKFLOW_TOOLS}
        assert names == {"search_workflow", "create_task", "task_query"}
