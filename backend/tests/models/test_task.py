"""Tests for Task model — Checkpoint, TRANSITION_MAP retry."""
from __future__ import annotations

from app.models.task import (
    TRANSITION_MAP,
    Checkpoint,
    Task,
    TaskStatus,
    is_valid_transition,
    utc_now,
)


class TestCheckpoint:
    """Test Checkpoint model serialization."""

    def test_checkpoint_basic(self) -> None:
        """Checkpoint can be created with minimal fields."""
        cp = Checkpoint(paused_at_node="human_1")
        assert cp.paused_at_node == "human_1"
        assert cp.completed_nodes == []
        assert cp.variable_snapshot == {}
        assert cp.human_context == {}
        assert cp.timeout_deadline is None
        assert cp.timeout_action == "fail"

    def test_checkpoint_full(self) -> None:
        """Checkpoint with all fields serializes correctly."""
        now = utc_now()
        deadline = now + __import__("datetime").timedelta(minutes=5)
        cp = Checkpoint(
            paused_at_node="human_abc",
            completed_nodes=["start_1", "agent_1"],
            variable_snapshot={"input": {"q": "test"}, "agent_1": {"result": "ok"}},
            paused_at=now,
            human_context={
                "node_id": "human_abc",
                "title": "审批报告",
                "description": "请审核",
                "options": ["approve", "reject"],
                "timeout_ms": 300000,
                "timeout_action": "auto_skip",
            },
            timeout_deadline=deadline,
            timeout_action="auto_skip",
        )
        assert cp.paused_at_node == "human_abc"
        assert cp.completed_nodes == ["start_1", "agent_1"]
        assert cp.variable_snapshot["agent_1"]["result"] == "ok"
        assert cp.timeout_action == "auto_skip"

        # Test serialization
        data = cp.model_dump(mode="json")
        assert data["paused_at_node"] == "human_abc"
        assert isinstance(data["paused_at"], str)
        assert isinstance(data["timeout_deadline"], str)

    def test_checkpoint_deserialization(self) -> None:
        """Checkpoint can be deserialized from dict."""
        data = {
            "paused_at_node": "human_1",
            "completed_nodes": ["start_1"],
            "variable_snapshot": {"input": {}},
            "paused_at": "2026-01-01T00:00:00Z",
            "human_context": {"title": "test"},
            "timeout_deadline": None,
            "timeout_action": "fail",
        }
        cp = Checkpoint.model_validate(data)
        assert cp.paused_at_node == "human_1"
        assert cp.completed_nodes == ["start_1"]
        assert cp.timeout_action == "fail"


class TestTransitionMapRetry:
    """Test that FAILED → PENDING is allowed (for retry)."""

    def test_failed_to_pending_is_valid(self) -> None:
        """FAILED tasks can transition to PENDING for retry."""
        assert is_valid_transition(TaskStatus.FAILED, TaskStatus.PENDING) is True

    def test_failed_to_running_is_invalid(self) -> None:
        """FAILED tasks cannot directly transition to RUNNING."""
        assert is_valid_transition(TaskStatus.FAILED, TaskStatus.RUNNING) is False

    def test_failed_to_completed_is_invalid(self) -> None:
        """FAILED tasks cannot transition to COMPLETED."""
        assert is_valid_transition(TaskStatus.FAILED, TaskStatus.COMPLETED) is False

    def test_failed_in_transition_map(self) -> None:
        """TRANSITION_MAP contains FAILED → [PENDING]."""
        assert TaskStatus.FAILED in TRANSITION_MAP
        assert TaskStatus.PENDING in TRANSITION_MAP[TaskStatus.FAILED]


class TestTaskCheckpoint:
    """Test Task model with checkpoint field."""

    def test_task_without_checkpoint(self) -> None:
        """Task can be created without checkpoint."""
        task = Task(workflow_id="wf_1")
        assert task.checkpoint is None

    def test_task_with_checkpoint(self) -> None:
        """Task can hold a Checkpoint."""
        cp = Checkpoint(paused_at_node="human_1")
        task = Task(workflow_id="wf_1", checkpoint=cp)
        assert task.checkpoint is not None
        assert task.checkpoint.paused_at_node == "human_1"

    def test_task_serialization_with_checkpoint(self) -> None:
        """Task serializes checkpoint correctly."""
        cp = Checkpoint(
            paused_at_node="human_1",
            completed_nodes=["start_1"],
            human_context={"title": "审批"},
        )
        task = Task(workflow_id="wf_1", checkpoint=cp)
        data = task.model_dump(by_alias=True)
        assert "checkpoint" in data
        assert data["checkpoint"]["paused_at_node"] == "human_1"
