"""E4 测试：CheckpointCoordinator——两阶段提交 / 影子执行 / 对账。"""
from __future__ import annotations

from datetime import timedelta

import app.engine.execution.repository as repo_mod
import pytest
import tests.engine.execution.test_repository_lease as _base
from app.engine.execution.checkpoint import CheckpointCoordinator
from app.models.base import utc_now


@pytest.fixture
def fake_db(monkeypatch):
    db = _base.FakeDB()
    monkeypatch.setattr(repo_mod, "get_database", lambda: db)
    import app.db.mongodb as app_db_mod
    import app.engine.execution.checkpoint as ckpt_mod

    monkeypatch.setattr(app_db_mod, "get_database", lambda: db)
    # checkpoint.py 的影子路径直接 import get_database——同样 patch
    monkeypatch.setattr(ckpt_mod, "get_database", lambda: db, raising=False)
    return db


async def test_commit_boundary_allocates_seq_and_writes_manifest(fake_db):
    exe = _base._seed_execution(fake_db, token=11)
    coord = CheckpointCoordinator(repo_mod.ExecutionRepository())

    seq1 = await coord.commit_boundary(
        exe.id, 11, kind="progress", step_id="loop_a",
        committed_step_ids=["n1", "n2"],
    )
    seq2 = await coord.commit_boundary(
        exe.id, 11, kind="pause", step_id="human_b",
        committed_step_ids=["n1", "n2", "loop_a"],
        graph_thread_id=None,
    )
    assert (seq1, seq2) == (1, 2)

    manifests = fake_db.collections["execution_checkpoints"]
    assert [m["checkpoint_seq"] for m in manifests.values()] == [1, 2]
    assert all(m["fencing_token"] == 11 for m in manifests.values())
    # 事件同事务落库
    events = [e for e in fake_db.collections["execution_events"].values()
              if e["execution_id"] == exe.id]
    assert {e["type"] for e in events} == {"checkpoint.committed"}


async def test_commit_boundary_fenced(fake_db):
    """旧 token → LeaseLostError，不产 Manifest。"""
    exe = _base._seed_execution(fake_db, token=12)
    coord = CheckpointCoordinator(repo_mod.ExecutionRepository())

    with pytest.raises(repo_mod.LeaseLostError):
        await coord.commit_boundary(exe.id, 11, kind="pause")
    assert "execution_checkpoints" not in fake_db.collections


async def test_shadow_commit_creates_execution_and_boundary(fake_db):
    """影子入口：find-or-create 影子执行（长期 lease）+ 边界提交。"""
    coord = CheckpointCoordinator(repo_mod.ExecutionRepository())

    seq = await coord.shadow_commit_workflow_boundary(
        "task_1", kind="progress", step_id="loop_a", committed_step_ids=["n1"],
    )
    assert seq == 1

    # 找到影子执行（遍历一次即可——单测数据量小）
    shadow = next(
        e for e in fake_db.collections["executions"].values()
        if e.get("task_id") == "task_1" and e.get("trigger") == "workflow"
    )
    assert shadow["lease"]["owner"] == "workflow-shadow"
    # 远期过期（≥ 300 天）
    from datetime import datetime

    expires = shadow["lease"]["expires_at"]
    assert isinstance(expires, datetime)
    assert expires > utc_now() + timedelta(days=300)

    # 第二次：复用同一影子执行，seq 递增
    seq2 = await coord.shadow_commit_workflow_boundary(
        "task_1", kind="complete", committed_step_ids=["n1", "n2"],
    )
    assert seq2 == 2
    shadows = [e for e in fake_db.collections["executions"].values()
               if e.get("task_id") == "task_1"]
    assert len(shadows) == 1
    assert shadows[0]["status"] == "succeeded"
    assert shadows[0]["completed_at"] is not None
    assert shadows[0]["lease"] is None
    assert shadows[0]["dispatch"]["state"] == "done"
    assert shadows[0]["shadow_active"] is False
    shadow_events = [
        event for event in fake_db.collections["execution_events"].values()
        if event["execution_id"] == shadow["_id"]
    ]
    assert {event["type"] for event in shadow_events} == {
        "checkpoint.committed", "execution.succeeded"
    }

    # A later workflow run for the same Task gets a new Execution identity.
    seq3 = await coord.shadow_commit_workflow_boundary(
        "task_1", kind="progress", step_id="new_run",
    )
    assert seq3 == 1
    shadows = [e for e in fake_db.collections["executions"].values()
               if e.get("task_id") == "task_1"]
    assert len(shadows) == 2
    assert len({e["_id"] for e in shadows}) == 2


async def test_shadow_commit_never_raises(fake_db, monkeypatch):
    """影子失败只告警不反噬权威路径（双写期铁则）。"""
    coord = CheckpointCoordinator(repo_mod.ExecutionRepository())

    async def _boom(*_a, **_k):
        raise ConnectionError("db down")

    monkeypatch.setattr(coord, "ensure_workflow_execution", _boom)
    assert await coord.shadow_commit_workflow_boundary("task_x", kind="pause") is None


# ── 对账 ──────────────────────────────────────────────────────────────


async def test_reconcile_detects_drift_and_dangling(fake_db, monkeypatch):
    import app.engine.execution.reconcile as rec_mod

    monkeypatch.setattr(rec_mod, "get_database", lambda: fake_db)
    from app.engine.execution.reconcile import reconcile

    coord = CheckpointCoordinator(repo_mod.ExecutionRepository())
    db = fake_db

    # 场景 1：权威有 checkpoint、影子 complete → drift
    await coord.shadow_commit_workflow_boundary("task_d", kind="complete")
    db.collections.setdefault("tasks", {})["task_d"] = {
        "_id": "task_d", "status": "waiting_human",
        "checkpoint": {"kind": "pause", "paused_at_node": "h1"},
    }

    # 场景 2：权威完成无 checkpoint、影子最新非 complete → dangling
    await coord.shadow_commit_workflow_boundary("task_g", kind="progress")
    db.collections.setdefault("tasks", {})["task_g"] = {
        "_id": "task_g", "status": "completed", "checkpoint": None,
    }

    # 场景 3：一致——权威完成 + 影子 complete（不应计入）
    await coord.shadow_commit_workflow_boundary("task_ok", kind="progress")
    await coord.shadow_commit_workflow_boundary("task_ok", kind="complete")
    db.collections.setdefault("tasks", {})["task_ok"] = {
        "_id": "task_ok", "status": "completed", "checkpoint": None,
    }

    report = await reconcile()
    assert report["drifted"] == 1
    assert report["dangling"] == 1
    assert report["missing_shadow"] == 0

    # --fix-status must not manufacture success from Task.status alone.
    report2 = await reconcile(fix_status=True)
    assert report2["fixed"] == 0
    assert report2["manual_repair_required"] == 1


async def test_reconcile_detects_task_without_any_shadow(fake_db, monkeypatch):
    import app.engine.execution.reconcile as rec_mod

    monkeypatch.setattr(rec_mod, "get_database", lambda: fake_db)
    fake_db.collections.setdefault("tasks", {})["task_missing"] = {
        "_id": "task_missing",
        "status": "completed",
        "checkpoint": None,
    }

    report = await rec_mod.reconcile()
    assert report["missing_shadow"] == 1


async def test_commit_boundary_rejects_incomplete_graph_identity(fake_db):
    exe = _base._seed_execution(fake_db, token=11)
    coord = CheckpointCoordinator(repo_mod.ExecutionRepository())

    with pytest.raises(ValueError, match="both thread_id and checkpoint_id"):
        await coord.commit_boundary(
            exe.id,
            11,
            kind="pause",
            graph_thread_id="thread-1",
            graph_checkpoint_id=None,
        )


async def test_shadow_lookup_does_not_reuse_regular_workflow_execution(fake_db):
    from app.engine.execution.models import Execution, ExecutionStatus, LeaseInfo

    regular = Execution(
        task_id="task_regular",
        trigger="workflow",
        status=ExecutionStatus.RUNNING,
    )
    regular.lease = LeaseInfo(
        owner="worker-ordinary",
        fencing_token=4,
        expires_at=utc_now() + timedelta(days=1),
    )
    fake_db.collections.setdefault("executions", {})[regular.id] = (
        regular.model_dump(by_alias=True)
    )

    coord = CheckpointCoordinator(repo_mod.ExecutionRepository())
    ensured = await coord.ensure_workflow_execution("task_regular")

    assert ensured is not None
    assert ensured[0] != regular.id
    created = fake_db.collections["executions"][ensured[0]]
    assert created["shadow_active"] is True
    assert created["lease"]["owner"] == "workflow-shadow"
