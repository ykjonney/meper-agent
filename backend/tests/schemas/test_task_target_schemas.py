"""Task 双目标 schema 契约：workflow_id / agent_id 恰好其一 + 字段透传。"""
from __future__ import annotations

import pytest
from app.schemas.execution import ExecutionResponse
from app.schemas.task import TaskCreate, TaskSummary
from pydantic import ValidationError


class TestTaskCreateTargetValidation:
    """TaskCreate：workflow_id 与 agent_id 必须恰好提供其一。"""

    def test_both_empty_raises(self) -> None:
        with pytest.raises(ValidationError):
            TaskCreate(workflow_id="", agent_id="", input={})

    def test_both_set_raises(self) -> None:
        with pytest.raises(ValidationError):
            TaskCreate(workflow_id="wf_1", agent_id="agent_1", input={})

    def test_agent_only_ok(self) -> None:
        body = TaskCreate(agent_id="agent_1", input={"instruction": "做调研"})
        assert body.agent_id == "agent_1"
        assert body.workflow_id == ""

    def test_workflow_only_ok(self) -> None:
        body = TaskCreate(workflow_id="wf_1", input={})
        assert body.agent_id == ""


class TestSummaryAndResponseFields:
    """TaskSummary / ExecutionResponse 新字段。"""

    def test_summary_accepts_agent_id(self) -> None:
        from datetime import UTC, datetime
        s = TaskSummary(
            id="task_1", workflow_id="", agent_id="agent_1",
            workflow_version="", status="running", input={},
            created_by="u1", created_by_type="user", version=1,
            total_tokens=0, created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
        )
        assert s.agent_id == "agent_1"

    def test_execution_response_total_tokens(self) -> None:
        r = ExecutionResponse(
            output="done", execution_path="react", request_id="r1",
            agent_id="agent_1", session_id="s1", total_tokens=123,
        )
        assert r.total_tokens == 123
