"""Tests for Task intervention variables write behavior (spec-human-node-approval)."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.api.v1.tasks import _sanitize_node_id
from app.core.security import create_access_token
from app.schemas.user import UserResponse, UserStatus
from fastapi.testclient import TestClient


TASK_ID = "task_01HAPPROVAL"
HUMAN_NODE_ID = "node_approval_1"
USER_ID = "user_01HAPPROVER"
WORKFLOW_ID = "wf_01HWF"
HUMAN_NODE_ID_SPECIAL = "审批-质检.5"


@pytest.fixture
def auth_token() -> str:
    return create_access_token(subject=USER_ID, claims={"role": "developer"})


@pytest.fixture
def current_user() -> UserResponse:
    return UserResponse(
        id=USER_ID,
        username="approver",
        email="approver@example.com",
        role="developer",
        status=UserStatus.ACTIVE,
        created_at="2026-06-01T00:00:00",
        updated_at="2026-06-01T00:00:00",
    )


def _override_auth(user: UserResponse):
    from app.core.security import get_current_user

    async def _fake():
        return user

    return _fake


def _make_task_doc(*, node_id: str = HUMAN_NODE_ID, version: int = 3, status: str = "waiting_human"):
    return {
        "_id": TASK_ID,
        "workflow_id": WORKFLOW_ID,
        "status": status,
        "version": version,
        "variables": {},
        "checkpoint": {"paused_at_node": node_id},
        "created_at": "2026-06-01T00:00:00",
        "updated_at": "2026-06-01T00:00:00",
    }


def _build_client(current_user: UserResponse):
    from app.api.v1 import tasks as tasks_module
    from app.core.security import get_current_user
    from app.main import app

    app.dependency_overrides[get_current_user] = _override_auth(current_user)
    return TestClient(app), app, tasks_module


def _post_intervene(client: TestClient, body: dict) -> tuple[int, dict]:
    resp = client.post(f"/api/v1/tasks/{TASK_ID}/intervene", json=body)
    return resp.status_code, resp.json()


def test_intervene_approve_writes_human_decision_to_variables(auth_token: str, current_user: UserResponse) -> None:
    """Approve writes {decision, comment, approver, decided_at} to human_decision_<sanitized_id>."""
    client, app, tasks_module = _build_client(current_user)
    try:
        task_doc = _make_task_doc()
        updated_doc = {**task_doc, "status": "running", "version": task_doc["version"] + 1}

        update_variables_mock = AsyncMock(return_value=updated_doc)
        with (
            patch.object(tasks_module.TaskService, "get_task_or_404", AsyncMock(return_value=task_doc)),
            patch.object(tasks_module.TaskService, "transition_task", AsyncMock(return_value=updated_doc)),
            patch.object(tasks_module.TaskService, "update_variables", update_variables_mock),
            patch.object(tasks_module.TaskService, "resume_task_execution"),
        ):
            status_code, payload = _post_intervene(
                client,
                {"action": "approve", "comment": "数据已确认", "version": task_doc["version"]},
            )

        assert status_code == 200, payload
        assert update_variables_mock.await_count == 1
        call_kwargs = update_variables_mock.await_args.kwargs
        variables = call_kwargs["variables"]
        expected_key = f"human_decision_{_sanitize_node_id(HUMAN_NODE_ID)}"
        assert expected_key in variables, f"Missing key {expected_key} in {variables}"
        decision = variables[expected_key]
        assert decision["decision"] == "approve"
        assert decision["comment"] == "数据已确认"
        assert decision["approver"] == USER_ID
        assert "decided_at" in decision and decision["decided_at"]
    finally:
        app.dependency_overrides.clear()


def test_intervene_reject_writes_comment_to_variables(auth_token: str, current_user: UserResponse) -> None:
    """Reject writes same structure with decision == 'reject'."""
    client, app, tasks_module = _build_client(current_user)
    try:
        task_doc = _make_task_doc()
        updated_doc = {**task_doc, "status": "failed", "version": task_doc["version"] + 1}

        update_variables_mock = AsyncMock(return_value=updated_doc)
        with (
            patch.object(tasks_module.TaskService, "get_task_or_404", AsyncMock(return_value=task_doc)),
            patch.object(tasks_module.TaskService, "transition_task", AsyncMock(return_value=updated_doc)),
            patch.object(tasks_module.TaskService, "update_variables", update_variables_mock),
        ):
            status_code, payload = _post_intervene(
                client,
                {"action": "reject", "comment": "质检不通过", "version": task_doc["version"]},
            )

        assert status_code == 200, payload
        assert update_variables_mock.await_count == 1
        variables = update_variables_mock.await_args.kwargs["variables"]
        expected_key = f"human_decision_{_sanitize_node_id(HUMAN_NODE_ID)}"
        decision = variables[expected_key]
        assert decision["decision"] == "reject"
        assert decision["comment"] == "质检不通过"
        assert decision["approver"] == USER_ID
        assert "decided_at" in decision and decision["decided_at"]
    finally:
        app.dependency_overrides.clear()


def test_intervene_with_empty_comment_writes_empty_string(auth_token: str, current_user: UserResponse) -> None:
    """Without comment, variables['comment'] == '' (not None)."""
    client, app, tasks_module = _build_client(current_user)
    try:
        task_doc = _make_task_doc()
        updated_doc = {**task_doc, "status": "running", "version": task_doc["version"] + 1}

        update_variables_mock = AsyncMock(return_value=updated_doc)
        with (
            patch.object(tasks_module.TaskService, "get_task_or_404", AsyncMock(return_value=task_doc)),
            patch.object(tasks_module.TaskService, "transition_task", AsyncMock(return_value=updated_doc)),
            patch.object(tasks_module.TaskService, "update_variables", update_variables_mock),
            patch.object(tasks_module.TaskService, "resume_task_execution"),
        ):
            status_code, payload = _post_intervene(
                client,
                {"action": "approve", "version": task_doc["version"]},
            )

        assert status_code == 200, payload
        variables = update_variables_mock.await_args.kwargs["variables"]
        decision = variables[f"human_decision_{_sanitize_node_id(HUMAN_NODE_ID)}"]
        assert decision["comment"] == ""
        assert decision["comment"] is not None
    finally:
        app.dependency_overrides.clear()


def test_intervene_rejects_when_task_not_waiting_human(auth_token: str, current_user: UserResponse) -> None:
    """Patch from review: 状态前置校验。Task 不在 WAITING_HUMAN 时拒绝审批。"""
    client, app, tasks_module = _build_client(current_user)
    try:
        task_doc = _make_task_doc(status="running")  # 已非 waiting_human
        update_variables_mock = AsyncMock()
        with (
            patch.object(tasks_module.TaskService, "get_task_or_404", AsyncMock(return_value=task_doc)),
            patch.object(tasks_module.TaskService, "transition_task", AsyncMock()),
            patch.object(tasks_module.TaskService, "update_variables", update_variables_mock),
        ):
            status_code, payload = _post_intervene(
                client,
                {"action": "approve", "comment": "test", "version": task_doc["version"]},
            )

        # 4xx 拒绝 + 不写 variables
        assert status_code in (400, 409, 422), payload
        assert update_variables_mock.await_count == 0
    finally:
        app.dependency_overrides.clear()


def test_sanitize_node_id_is_collision_resistant() -> None:
    """Patch from review: 不同 node_id sanitize 后必须不同，避免决策数据静默覆盖。"""
    # 这些原版 sanitize 后都是同一个 key '__5'，新实现必须产生不同 key
    candidates = ["审批-质检.5", "审批_质检_5", "审批.质检.5", "审批/质检@5", "审批!质检#5"]
    keys = [_sanitize_node_id(c) for c in candidates]
    assert len(set(keys)) == len(candidates), f"Collision detected: {dict(zip(candidates, keys))}"
    # 同时保留原 node_id 的人类可读部分
    for key in keys:
        assert "5" in key, f"sanitize lost content: {key}"


def test_intervene_reject_uses_comment_in_error_message(auth_token: str, current_user: UserResponse) -> None:
    """Patch from review: reject 路径的 error_message 必须用 comment 而非 reason 字段。"""
    client, app, tasks_module = _build_client(current_user)
    try:
        task_doc = _make_task_doc()
        updated_doc = {**task_doc, "status": "failed", "version": task_doc["version"] + 1}

        transition_mock = AsyncMock(return_value=updated_doc)
        with (
            patch.object(tasks_module.TaskService, "get_task_or_404", AsyncMock(return_value=task_doc)),
            patch.object(tasks_module.TaskService, "transition_task", transition_mock),
            patch.object(tasks_module.TaskService, "update_variables", AsyncMock(return_value=updated_doc)),
        ):
            status_code, payload = _post_intervene(
                client,
                {"action": "reject", "comment": "数据不达标", "version": task_doc["version"]},
            )

        assert status_code == 200, payload
        # 检查 transition_task 收到的 error_info 包含 comment 而非 "无原因"
        transition_kwargs = transition_mock.await_args.kwargs
        error_info = transition_kwargs.get("error_info", {})
        assert "数据不达标" in error_info.get("error_message", ""), (
            f"error_message should contain comment, got: {error_info}"
        )
        assert "无原因" not in error_info.get("error_message", ""), (
            f"error_message should not default to '无原因' when comment is given: {error_info}"
        )
    finally:
        app.dependency_overrides.clear()
