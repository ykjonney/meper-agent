"""Tests for trigger API permission integration + schedule hygiene.

权限对接（PERMISSIONS.md：判权限不判角色）：
- 准入：路由级 trigger:read；写端点 trigger:write（无权限 403）
- 归属正交：trigger:manage 持有者可跨用户访问 + ?all=true 全库列表；
  非持有者访问他人 trigger 404（不泄露存在性），传他人 user_id / all=true
  得到明确 403（旧实现的静默降级正是隐形 trigger 事故的帮凶）
- 卫生：PUT 切换 type 清理另一类残留字段；非法 cron 422 TRIGGER_INVALID_CRON

所有持久层均 mock，不触达真实 MongoDB；get_role_permissions 双引用点
（security 模块与 triggers 模块）统一 patch，避免 Redis/Mongo 环境依赖。
"""
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.api.v1 import triggers as triggers_module
from app.core.security import get_current_user
from app.schemas.user import UserResponse, UserStatus
from fastapi.testclient import TestClient

USER_A = "user_01TRIGAA"
USER_B = "user_01TRIGBB"
WORKFLOW_ID = "wf_01TRIG"
TRIGGER_ID = "trig_01TRIG"

# 权限集常量（patch get_role_permissions 返回值）
PERMS_OWN = {"trigger:read", "trigger:write"}  # developer 默认
PERMS_MANAGE = PERMS_OWN | {"trigger:manage"}  # admin 默认
PERMS_NONE = set()  # 自定义角色未授予任何 trigger 权限


def _user(user_id: str, role: str) -> UserResponse:
    return UserResponse(
        id=user_id,
        username=f"user-{user_id[-6:]}",
        email=f"{user_id}@example.com",
        role=role,
        status=UserStatus.ACTIVE,
        created_at="2026-06-01T00:00:00",
        updated_at="2026-06-01T00:00:00",
    )


def _trigger_doc(owner: str = USER_A, **overrides) -> dict:
    """Build a trigger document as stored in MongoDB."""
    from app.models.trigger import Trigger

    t = Trigger(
        _id=TRIGGER_ID,
        workflow_id=WORKFLOW_ID,
        user_id=owner,
        type="cron",
        enabled=True,
        cron_expression="0 16 * * 4",
        default_input={},
        schedule_version=3,
    )
    doc = t.model_dump(by_alias=True)
    doc.update(overrides)
    return doc


class _ClientCtx:
    """TestClient with auth + permission patches; clears overrides on exit."""

    def __init__(self, user: UserResponse, perms: set[str]) -> None:
        from app.main import app

        async def _fake_user():
            return user

        async def _fake_perms(role_name: str):
            return perms

        app.dependency_overrides[get_current_user] = _fake_user
        self._perms_patchers = [
            patch("app.core.security.get_role_permissions", new=_fake_perms),
            patch("app.api.v1.triggers.get_role_permissions", new=_fake_perms),
        ]
        for p in self._perms_patchers:
            p.start()
        self.client = TestClient(app)
        self.app = app

    def __enter__(self) -> TestClient:
        return self.client

    def __exit__(self, *exc) -> None:
        for p in self._perms_patchers:
            p.stop()
        self.app.dependency_overrides.clear()


def _mock_repo(trigger_doc: dict | None = None) -> MagicMock:
    """Mock trigger repo; find_by_id returns trigger_doc (or None)."""
    repo = MagicMock()
    trigger = None
    if trigger_doc is not None:
        from app.models.trigger import Trigger

        trigger = Trigger(**trigger_doc)
    repo.find_by_id = AsyncMock(return_value=trigger)
    repo.insert = AsyncMock()
    repo.update = AsyncMock()
    repo.delete = AsyncMock(return_value=True)
    return repo


def _patch_repo(repo: MagicMock):
    return patch.object(triggers_module, "_get_repo", return_value=repo)


def _patch_next_at():
    """Stub _compute_next_trigger_at (avoids scheduler singleton + real clock)."""
    fixed = datetime(2026, 9, 10, 8, 0, tzinfo=UTC)
    return patch.object(triggers_module, "_compute_next_trigger_at", return_value=fixed)


# ── 准入：权限键 ──


def test_read_denied_without_trigger_read() -> None:
    """无 trigger:read 的角色：GET /triggers 403（路由级依赖）。"""
    with _ClientCtx(_user(USER_A, "custom"), PERMS_NONE) as client:
        resp = client.get("/api/v1/triggers")
    assert resp.status_code == 403, resp.text


def test_write_denied_without_trigger_write() -> None:
    """有 read 无 write：POST/PUT/PATCH/DELETE 全部 403。"""
    user = _user(USER_A, "viewer_like")
    with _ClientCtx(user, {"trigger:read"}) as client:
        assert client.post("/api/v1/triggers", json={}).status_code == 403
        assert client.put(f"/api/v1/triggers/{TRIGGER_ID}", json={}).status_code == 403
        assert (
            client.patch(f"/api/v1/triggers/{TRIGGER_ID}/toggle", json={"enabled": False}).status_code
            == 403
        )
        assert client.delete(f"/api/v1/triggers/{TRIGGER_ID}").status_code == 403


# ── 归属正交（own/all）──


def test_get_others_trigger_404_without_manage() -> None:
    """非 manage 持有者访问他人 trigger：404（不泄露存在性）。"""
    repo = _mock_repo(_trigger_doc(owner=USER_B))
    with _ClientCtx(_user(USER_A, "developer"), PERMS_OWN) as client, _patch_repo(repo):
        resp = client.get(f"/api/v1/triggers/{TRIGGER_ID}")
    assert resp.status_code == 404, resp.text


def test_get_others_trigger_ok_with_manage() -> None:
    """manage 持有者可访问他人 trigger。"""
    repo = _mock_repo(_trigger_doc(owner=USER_B))
    with _ClientCtx(_user(USER_A, "admin"), PERMS_MANAGE) as client, _patch_repo(repo):
        resp = client.get(f"/api/v1/triggers/{TRIGGER_ID}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["user_id"] == USER_B


def test_list_all_true_requires_manage() -> None:
    """非 manage 持有者传 all=true：明确 403（不静默降级）。"""
    mock_find = MagicMock()

    def _find(query):
        mock_find(query)
        cursor = MagicMock()
        cursor.sort = MagicMock(return_value=cursor)

        async def _to_list(*_a, **_kw):
            return []

        cursor.to_list = AsyncMock(side_effect=_to_list)
        return cursor

    db = MagicMock()
    db.__getitem__ = MagicMock(return_value=MagicMock(find=MagicMock(side_effect=_find)))
    with (
        _ClientCtx(_user(USER_A, "developer"), PERMS_OWN) as client,
        patch("app.db.mongodb.get_database", return_value=db),
    ):
        resp = client.get("/api/v1/triggers", params={"all": True})
    assert resp.status_code == 403, resp.text


def test_list_all_true_returns_full_collection_with_manage() -> None:
    """manage 持有者 all=true：查询无 user_id 过滤（全库）。"""
    captured: dict = {}
    cursor = MagicMock()
    cursor.sort = MagicMock(return_value=cursor)
    cursor.to_list = AsyncMock(return_value=[])

    def _find(query):
        captured.update(query)
        return cursor

    db = MagicMock()
    db.__getitem__ = MagicMock(return_value=MagicMock(find=MagicMock(side_effect=_find)))
    with (
        _ClientCtx(_user(USER_A, "admin"), PERMS_MANAGE) as client,
        patch("app.db.mongodb.get_database", return_value=db),
    ):
        resp = client.get("/api/v1/triggers", params={"all": True})
    assert resp.status_code == 200, resp.text
    assert "user_id" not in captured  # 全库，不按用户过滤


def test_list_defaults_to_own() -> None:
    """默认（不传参数）：仅查自己的。"""
    captured: dict = {}
    cursor = MagicMock()
    cursor.sort = MagicMock(return_value=cursor)
    cursor.to_list = AsyncMock(return_value=[])

    def _find(query):
        captured.update(query)
        return cursor

    db = MagicMock()
    db.__getitem__ = MagicMock(return_value=MagicMock(find=MagicMock(side_effect=_find)))
    with (
        _ClientCtx(_user(USER_A, "developer"), PERMS_OWN) as client,
        patch("app.db.mongodb.get_database", return_value=db),
    ):
        resp = client.get("/api/v1/triggers")
    assert resp.status_code == 200, resp.text
    assert captured["user_id"] == USER_A


# ── 卫生：cron 校验 + PUT 残留清理 ──


@pytest.mark.parametrize("bad_cron", ["", "not a cron", "NaN * * * *", "61 * * * *"])
def test_create_rejects_invalid_cron(bad_cron: str) -> None:
    """非法 cron 创建 → 422 TRIGGER_INVALID_CRON。"""
    repo = _mock_repo()
    body = {
        "workflow_id": WORKFLOW_ID,
        "type": "cron",
        "enabled": False,
        "cron_expression": bad_cron,
        "default_input": {},
    }
    with _ClientCtx(_user(USER_A, "developer"), PERMS_OWN) as client, _patch_repo(repo):
        resp = client.post("/api/v1/triggers", json=body)
    assert resp.status_code == 422, resp.text
    assert resp.json()["error"]["code"] == "TRIGGER_INVALID_CRON"
    repo.insert.assert_not_awaited()


def test_update_switching_to_once_clears_cron_expression() -> None:
    """cron → once：cron_expression 被置 None（清残留）。"""
    repo = _mock_repo(_trigger_doc(owner=USER_A))
    with (
        _ClientCtx(_user(USER_A, "developer"), PERMS_OWN) as client,
        _patch_repo(repo),
        _patch_next_at(),
    ):
        resp = client.put(
            f"/api/v1/triggers/{TRIGGER_ID}",
            json={"type": "once", "execute_at": "2026-09-10T08:00:00Z"},
        )
    assert resp.status_code == 200, resp.text
    # repo.update 被多次调用（字段更新 + next 刷新），找含 cron_expression=None 的那次
    all_kwargs = [c.kwargs for c in repo.update.await_args_list]
    field_update = next(k for k in all_kwargs if "cron_expression" in k)
    assert field_update["cron_expression"] is None
    assert field_update["type"] == "once"


def test_update_switching_to_cron_clears_execute_at() -> None:
    """once → cron：execute_at 被置 None（清残留）。"""
    doc = _trigger_doc(owner=USER_A)
    doc["type"] = "once"
    doc["cron_expression"] = None
    doc["execute_at"] = datetime(2026, 9, 10, 8, tzinfo=UTC)
    repo = _mock_repo(doc)
    with (
        _ClientCtx(_user(USER_A, "developer"), PERMS_OWN) as client,
        _patch_repo(repo),
        _patch_next_at(),
    ):
        resp = client.put(
            f"/api/v1/triggers/{TRIGGER_ID}",
            json={"type": "cron", "cron_expression": "0 16 * * 4"},
        )
    assert resp.status_code == 200, resp.text
    all_kwargs = [c.kwargs for c in repo.update.await_args_list]
    field_update = next(k for k in all_kwargs if "execute_at" in k)
    assert field_update["execute_at"] is None
    assert field_update["cron_expression"] == "0 16 * * 4"


def test_update_rejects_invalid_cron() -> None:
    """PUT 传非法 cron → 422。"""
    repo = _mock_repo(_trigger_doc(owner=USER_A))
    with _ClientCtx(_user(USER_A, "developer"), PERMS_OWN) as client, _patch_repo(repo):
        resp = client.put(
            f"/api/v1/triggers/{TRIGGER_ID}",
            json={"cron_expression": "bad"},
        )
    assert resp.status_code == 422, resp.text
    repo.update.assert_not_awaited()


def test_create_rejects_unknown_type() -> None:
    """type 是 Literal['cron','once']：任意其他字符串 422（此前裸 str 会
    静默入库，调度器 _compute_next 两分支都不匹配 → 永不触发）。"""
    repo = _mock_repo()
    body = {
        "workflow_id": WORKFLOW_ID,
        "type": "weird",
        "enabled": False,
        "default_input": {},
    }
    with _ClientCtx(_user(USER_A, "developer"), PERMS_OWN) as client, _patch_repo(repo):
        resp = client.post("/api/v1/triggers", json=body)
    assert resp.status_code == 422, resp.text
    repo.insert.assert_not_awaited()


def test_list_all_with_own_user_id_returns_own() -> None:
    """all=true + user_id=自己：语义一致——按显式 user_id 过滤（自己的），
    而非旧分支误落入"默认只看自己"路径。"""
    captured: dict = {}
    cursor = MagicMock()
    cursor.sort = MagicMock(return_value=cursor)
    cursor.to_list = AsyncMock(return_value=[])

    def _find(query):
        captured.update(query)
        return cursor

    db = MagicMock()
    db.__getitem__ = MagicMock(return_value=MagicMock(find=MagicMock(side_effect=_find)))
    with (
        _ClientCtx(_user(USER_A, "admin"), PERMS_MANAGE) as client,
        patch("app.db.mongodb.get_database", return_value=db),
    ):
        resp = client.get("/api/v1/triggers", params={"all": True, "user_id": USER_A})
    assert resp.status_code == 200, resp.text
    assert captured["user_id"] == USER_A
