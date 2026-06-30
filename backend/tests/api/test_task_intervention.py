"""Tests for Task intervention variable-write behavior (spec-human-node-approval).

Adapted to the harness-era intervention contract:
- the decision is written under the *raw* ``paused_at_node`` key (no sanitization);
- the body field is ``reason`` (not ``comment``);
- the decision payload is ``{decision, reason, approved_by}``;
- on reject, ``error_message`` reflects the given reason (not "无原因").
"""
from unittest.mock import AsyncMock, patch

import pytest
from app.core.security import get_current_user
from app.main import app
from app.schemas.user import UserResponse, UserStatus
from fastapi.testclient import TestClient

TASK_ID = "task_01HAPPROVAL"
HUMAN_NODE_ID = "node_approval_1"
USER_ID = "user_01HAPPROVER"
WORKFLOW_ID = "wf_01HWF"


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

    app.dependency_overrides[get_current_user] = _override_auth(current_user)
    return TestClient(app), app, tasks_module


def _post_intervene(client: TestClient, body: dict) -> tuple[int, dict]:
    resp = client.post(f"/api/v1/tasks/{TASK_ID}/intervene", json=body)
    return resp.status_code, resp.json()


def test_intervene_approve_writes_human_decision_to_variables(current_user: UserResponse) -> None:
    """Approve writes {decision, reason, approved_by} under the raw paused_at_node key."""
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
                {"action": "approve", "reason": "数据已确认", "version": task_doc["version"]},
            )

        assert status_code == 200, payload
        assert update_variables_mock.await_count == 1
        call_kwargs = update_variables_mock.await_args.kwargs
        variables = call_kwargs["variables"]
        # Decision keyed by the RAW node id (no sanitization in the new contract).
        assert HUMAN_NODE_ID in variables, f"Missing key {HUMAN_NODE_ID!r} in {variables}"
        decision = variables[HUMAN_NODE_ID]
        assert decision["decision"] == "approve"
        assert decision["reason"] == "数据已确认"
        assert decision["approved_by"] == USER_ID
    finally:
        app.dependency_overrides.clear()


def test_intervene_approve_default_reason_is_empty_string(current_user: UserResponse) -> None:
    """Without reason, decision['reason'] == '' (not None)."""
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
        decision = variables[HUMAN_NODE_ID]
        assert decision["reason"] == ""
        assert decision["reason"] is not None
    finally:
        app.dependency_overrides.clear()


def test_intervene_reject_uses_reason_in_error_message(current_user: UserResponse) -> None:
    """reject path: error_message must carry the given reason, not the '无原因' default."""
    client, app, tasks_module = _build_client(current_user)
    try:
        task_doc = _make_task_doc()
        updated_doc = {**task_doc, "status": "failed", "version": task_doc["version"] + 1}

        transition_mock = AsyncMock(return_value=updated_doc)
        with (
            patch.object(tasks_module.TaskService, "get_task_or_404", AsyncMock(return_value=task_doc)),
            patch.object(tasks_module.TaskService, "transition_task", transition_mock),
        ):
            status_code, payload = _post_intervene(
                client,
                {"action": "reject", "reason": "数据不达标", "version": task_doc["version"]},
            )

        assert status_code == 200, payload
        transition_kwargs = transition_mock.await_args.kwargs
        error_info = transition_kwargs.get("error_info", {})
        assert "数据不达标" in error_info.get("error_message", ""), (
            f"error_message should contain reason, got: {error_info}"
        )
        assert "无原因" not in error_info.get("error_message", ""), (
            f"error_message should not default to '无原因' when reason is given: {error_info}"
        )
    finally:
        app.dependency_overrides.clear()
