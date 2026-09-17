"""用户工具编辑/删除/详情权限 API 集成测试（owner | admin 双口径）。

回归背景：PUT/DELETE 曾误挂 ``Depends(require_any_role("admin"))``——该
依赖对非 admin 直接抛 403，owner 本人也被拦在 handler 外（原代码
``is_admin = admin_check is not None`` 假设它会返回 None，实际不会）。
另外 can_view 曾漏掉 admin 分支——admin 拉他人未发布工具详情 404。
"""
from unittest.mock import AsyncMock, patch

import pytest
from app.core.security import create_access_token
from app.services.user_tool_service import UserToolService
from fastapi.testclient import TestClient


def _user(uid: str, role: str) -> dict:
    return {
        "_id": uid,
        "username": f"{role}_{uid}",
        "email": f"{uid}@x.io",
        "password_hash": "x",
        "role": role,
        "status": "active",
        "created_at": "2026-01-01T00:00:00",
        "updated_at": "2026-01-01T00:00:00",
        "last_login_at": None,
    }


@pytest.fixture
def dev_token() -> str:
    """owner：developer（tool:write）。"""
    return create_access_token(subject="user_dev1", claims={"role": "developer"})


@pytest.fixture
def dev2_token() -> str:
    return create_access_token(subject="user_dev2", claims={"role": "developer"})


@pytest.fixture
def admin_token() -> str:
    return create_access_token(subject="user_adm1", claims={"role": "admin"})


TOOL_DOC = {
    "_id": "uto_1",
    "name": "echo",
    "source": "code",
    "code": "def run(): return 1",
    "owner_user_id": "user_dev1",
    "status": "private",
    "enabled": False,
}


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _patch_user(uid: str, role: str):
    return patch(
        "app.services.user_service.UserService.get_user_by_id",
        AsyncMock(return_value=_user(uid, role)),
    )


def test_owner_can_edit_own_tool(client: TestClient, dev_token: str) -> None:
    """owner（developer）编辑自己的工具——不被 admin 角色依赖拦 403。"""
    with (
        _patch_user("user_dev1", "developer"),
        patch.object(UserToolService, "update_tool", AsyncMock(return_value=dict(TOOL_DOC))) as mock_update,
    ):
        resp = client.put(
            "/api/v1/user-tools/uto_1",
            json={"name": "echo"},
            headers=_auth(dev_token),
        )
    assert resp.status_code == 200, resp.text
    mock_update.assert_awaited_once()
    assert mock_update.await_args.kwargs["is_admin"] is False


def test_admin_can_edit_others_tool(client: TestClient, admin_token: str) -> None:
    """admin 编辑他人工具——is_admin=True 透传（热修复语义）。"""
    with (
        _patch_user("user_adm1", "admin"),
        patch.object(UserToolService, "update_tool", AsyncMock(return_value=dict(TOOL_DOC))) as mock_update,
    ):
        resp = client.put(
            "/api/v1/user-tools/uto_1",
            json={"name": "echo"},
            headers=_auth(admin_token),
        )
    assert resp.status_code == 200, resp.text
    assert mock_update.await_args.kwargs["is_admin"] is True


def test_non_owner_dev_edit_rejected(client: TestClient, dev2_token: str) -> None:
    """非 owner 开发者编辑他人工具 → UserToolError → 400。"""
    from app.services.user_tool_service import UserToolError

    with (
        _patch_user("user_dev2", "developer"),
        patch.object(
            UserToolService,
            "update_tool",
            AsyncMock(side_effect=UserToolError("Tool 'uto_1' not found or not yours.")),
        ),
    ):
        resp = client.put(
            "/api/v1/user-tools/uto_1",
            json={"name": "echo"},
            headers=_auth(dev2_token),
        )
    assert resp.status_code == 422  # ValidationError → 422（USER_TOOL_INVALID）


def test_owner_can_delete_own_tool(client: TestClient, dev_token: str) -> None:
    with (
        _patch_user("user_dev1", "developer"),
        patch.object(UserToolService, "delete_tool", AsyncMock(return_value=None)) as mock_delete,
    ):
        resp = client.delete("/api/v1/user-tools/uto_1", headers=_auth(dev_token))
    assert resp.status_code == 200, resp.text
    assert mock_delete.await_args.kwargs["is_admin"] is False


def test_admin_can_delete_others_tool(client: TestClient, admin_token: str) -> None:
    """admin 删除他人工具——is_admin=True（治理兜底）。"""
    with (
        _patch_user("user_adm1", "admin"),
        patch.object(UserToolService, "delete_tool", AsyncMock(return_value=None)) as mock_delete,
    ):
        resp = client.delete("/api/v1/user-tools/uto_1", headers=_auth(admin_token))
    assert resp.status_code == 200, resp.text
    assert mock_delete.await_args.kwargs["is_admin"] is True


def test_admin_views_others_private_tool(client: TestClient, admin_token: str) -> None:
    """admin 拉他人 private 工具详情——can_view 的 admin 分支。"""
    with (
        _patch_user("user_adm1", "admin"),
        patch.object(UserToolService, "get_tool", AsyncMock(return_value=dict(TOOL_DOC))),
    ):
        resp = client.get("/api/v1/user-tools/uto_1", headers=_auth(admin_token))
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "echo"


def test_other_dev_cannot_view_private_tool(client: TestClient, dev2_token: str) -> None:
    """非 owner 开发者看他人 private 工具 → 404（可见性不变）。"""
    with (
        _patch_user("user_dev2", "developer"),
        patch.object(UserToolService, "get_tool", AsyncMock(return_value=dict(TOOL_DOC))),
    ):
        resp = client.get("/api/v1/user-tools/uto_1", headers=_auth(dev2_token))
    assert resp.status_code == 404


def test_owner_can_save_org_args(client: TestClient, dev_token: str) -> None:
    """owner 配置自己工具的统一凭证（不再 admin-only）。"""
    with (
        _patch_user("user_dev1", "developer"),
        patch.object(UserToolService, "save_org_args", AsyncMock(return_value=None)) as mock_save,
    ):
        resp = client.put(
            "/api/v1/user-tools/uto_1/args",
            json={"user_args": {"token": "tk"}},
            headers=_auth(dev_token),
        )
    assert resp.status_code == 200, resp.text
    assert mock_save.await_args.kwargs["is_admin"] is False


def test_other_dev_cannot_save_org_args(client: TestClient, dev2_token: str) -> None:
    """非 owner 开发者配置他人工具凭证 → UserToolError → 422。"""
    from app.services.user_tool_service import UserToolError

    with (
        _patch_user("user_dev2", "developer"),
        patch.object(
            UserToolService,
            "save_org_args",
            AsyncMock(side_effect=UserToolError("Tool 'uto_1' not found or not yours.")),
        ),
    ):
        resp = client.put(
            "/api/v1/user-tools/uto_1/args",
            json={"user_args": {"token": "tk"}},
            headers=_auth(dev2_token),
        )
    assert resp.status_code == 422


def test_owner_detail_echoes_org_args(client: TestClient, dev_token: str) -> None:
    """owner 拉自己工具详情回显凭证（敏感值为 enc: 密文，弹窗非敏感回显用）。"""
    doc = {**TOOL_DOC, "org_user_args": {"token": "enc:x"}}
    with (
        _patch_user("user_dev1", "developer"),
        patch.object(UserToolService, "get_tool", AsyncMock(return_value=doc)),
    ):
        resp = client.get("/api/v1/user-tools/uto_1", headers=_auth(dev_token))
    assert resp.status_code == 200, resp.text
    assert resp.json()["org_user_args"] == {"token": "enc:x"}


def test_admin_create_auto_publishes(client: TestClient, admin_token: str) -> None:
    """admin 创建免审——is_admin 透传 service（创建即 published）。"""
    with (
        _patch_user("user_adm1", "admin"),
        patch.object(UserToolService, "create_tool", AsyncMock(return_value=dict(TOOL_DOC))) as mock_create,
    ):
        resp = client.post(
            "/api/v1/user-tools",
            json={"name": "echo", "source": "code", "code": "def run(): return 1"},
            headers=_auth(admin_token),
        )
    assert resp.status_code == 200, resp.text
    assert mock_create.await_args.kwargs["is_admin"] is True
