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
    """Test that FAILED → RUNNING is allowed (for retry, direct re-execution)."""

    def test_failed_to_running_is_valid(self) -> None:
        """FAILED tasks can transition to RUNNING for retry."""
        assert is_valid_transition(TaskStatus.FAILED, TaskStatus.RUNNING) is True

    def test_failed_to_pending_is_invalid(self) -> None:
        """FAILED tasks no longer go through PENDING (retry re-executes directly)."""
        assert is_valid_transition(TaskStatus.FAILED, TaskStatus.PENDING) is False

    def test_failed_to_completed_is_invalid(self) -> None:
        """FAILED tasks cannot transition to COMPLETED."""
        assert is_valid_transition(TaskStatus.FAILED, TaskStatus.COMPLETED) is False

    def test_failed_in_transition_map(self) -> None:
        """TRANSITION_MAP contains FAILED → [RUNNING]."""
        assert TaskStatus.FAILED in TRANSITION_MAP
        assert TaskStatus.RUNNING in TRANSITION_MAP[TaskStatus.FAILED]


class TestTransitionMapCancelResume:
    """Test RUNNING→CANCELLED and CANCELLED→RUNNING (cancel + resume)."""

    def test_running_to_cancelled_is_valid(self) -> None:
        """RUNNING tasks can be cancelled (graceful suspend)."""
        assert is_valid_transition(TaskStatus.RUNNING, TaskStatus.CANCELLED) is True

    def test_cancelled_to_running_is_valid(self) -> None:
        """CANCELLED tasks can be resumed (CANCELLED is recoverable)."""
        assert is_valid_transition(TaskStatus.CANCELLED, TaskStatus.RUNNING) is True

    def test_cancelled_not_terminal(self) -> None:
        """CANCELLED is NOT a terminal status — it can be resumed."""
        from app.models.task import TERMINAL_STATUSES

        assert TaskStatus.CANCELLED not in TERMINAL_STATUSES

    def test_cancelled_to_completed_is_invalid(self) -> None:
        """CANCELLED cannot go directly to COMPLETED."""
        assert is_valid_transition(TaskStatus.CANCELLED, TaskStatus.COMPLETED) is False


class TestCheckpointAgentThreadId:
    """Test Checkpoint.agent_thread_id for cancel/resume continuity."""

    def test_checkpoint_has_agent_thread_id(self) -> None:
        """Checkpoint stores agent_thread_id for LangGraph resume."""
        cp = Checkpoint(paused_at_node="agent_1", agent_thread_id="task_x_agent_1")
        assert cp.agent_thread_id == "task_x_agent_1"

    def test_checkpoint_default_agent_thread_id(self) -> None:
        """Default agent_thread_id is empty string."""
        cp = Checkpoint(paused_at_node="agent_1")
        assert cp.agent_thread_id == ""


class TestTaskCeleryTaskId:
    """Test Task.celery_task_id field."""

    def test_task_has_celery_task_id(self) -> None:
        """Task stores celery_task_id for revoke."""
        task = Task(workflow_id="wf_1")
        assert task.celery_task_id == ""


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
