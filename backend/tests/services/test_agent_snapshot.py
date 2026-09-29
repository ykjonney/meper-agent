"""AgentSnapshotService 测试 — 版本化快照的创建/列表/回滚。

update 自动快照 + version 递增 + restore 永不复用版本号——
自优化循环"严格提升门控"的物理前提。
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _mock_agent_col(monkeypatch, docs: dict):
    """Mock agents 集合：find_one 按 _id 返回，update_one/replace_one 记录。"""
    col = MagicMock()
    def _find_one(q, **k):
        # {_id: x} → 直接返回；name-conflict 查询 {_id: {$ne}} → None（不冲突）
        key = q.get("_id")
        return docs.get(key) if isinstance(key, str) else None

    col.find_one = AsyncMock(side_effect=_find_one)
    col.update_one = AsyncMock()
    col.replace_one = AsyncMock()
    db = MagicMock()
    db.__getitem__.side_effect = lambda key: col if key == "agents" else MagicMock()
    monkeypatch.setattr("app.services.agent_service.get_database", lambda: db)
    return col


def _mock_snap_col(monkeypatch, snaps: list[dict]):
    col = MagicMock()
    col.insert_one = AsyncMock()
    col.find_one = AsyncMock(side_effect=lambda q, **k: next(
        (s for s in snaps if s.get("agent_id") == q.get("agent_id")
         and s.get("snapshot_of_version") == q.get("snapshot_of_version")), None,
    ))
    col.find = MagicMock()
    col.create_index = AsyncMock()
    db = MagicMock()
    db.__getitem__.side_effect = lambda key: col if key == "agent_snapshots" else MagicMock()
    monkeypatch.setattr("app.services.agent_snapshot_service.get_database", lambda: db)
    return col


async def test_update_takes_snapshot_and_bumps_version(monkeypatch):
    """update_agent：自动快照当前 + version 递增。"""
    from app.services.agent_service import AgentService

    docs = {"agent_1": {"_id": "agent_1", "name": "旧名", "version": 3, "status": "draft"}}
    agent_col = _mock_agent_col(monkeypatch, docs)
    snap_col = _mock_snap_col(monkeypatch, [])

    with patch("app.services.agent_service._resolve_custom_tools", new=AsyncMock(return_value=[])):
        await AgentService.update_agent(
            "agent_1", name="新名", prompt_slots={"role": "r"}, can_spawn_agents=False,
        )
    # 快照被写入（v3）
    inserted = snap_col.insert_one.await_args.args[0]
    assert inserted["snapshot_of_version"] == 3
    assert inserted["doc"]["name"] == "旧名"
    # version 递增到 4
    set_op = agent_col.update_one.await_args.args[1]["$set"]
    assert set_op["version"] == 4


async def test_restore_never_reuses_version(monkeypatch):
    """回滚：版本号永不复用——恢复 v3 后新版本 = max(3, 当前) + 1。"""
    from app.services.agent_snapshot_service import AgentSnapshotService

    # Agent 当前 v5，快照有 v3（旧状态）和 v5（pre-update 状态）
    docs = {"agent_1": {"_id": "agent_1", "name": "当前", "version": 5, "status": "draft",
                        "prompt_slots": {"role": "v5 内容"}}}
    agent_col = _mock_agent_col(monkeypatch, docs)
    snaps = [
        {"_id": "s1", "agent_id": "agent_1", "snapshot_of_version": 3,
         "doc": {"_id": "agent_1", "name": "旧名", "version": 3,
                  "prompt_slots": {"role": "v3 内容"}, "status": "draft"}},
        {"_id": "s2", "agent_id": "agent_1", "snapshot_of_version": 5,
         "doc": {"_id": "agent_1", "name": "当前", "version": 5, "status": "draft"}},
    ]
    snap_col = _mock_snap_col(monkeypatch, snaps)

    # get_agent mock（restore 内部调用）
    from app.services.agent_service import AgentService

    with (
        patch("app.services.agent_service.AgentService.get_agent",
              new=AsyncMock(side_effect=lambda aid: docs.get(aid))),
        patch.object(AgentService, '_collection', staticmethod(lambda: agent_col)),
    ):
        await AgentSnapshotService.restore("agent_1", 3)

    # 快照被调用了两次：restore 前的 pre-restore 快照
    assert snap_col.insert_one.await_count >= 1
    # replace_one 恢复的是 v3 内容
    restored_doc = agent_col.replace_one.await_args.args[1]
    assert restored_doc["prompt_slots"]["role"] == "v3 内容"
    assert restored_doc["version"] == 6  # max(3,5)+1 = 6，不是 3


async def test_restore_published_rejected(monkeypatch):
    """Published Agent 不可回滚（AGENT_PUBLISHED_IMMUTABLE 语义保持）。"""
    from app.core.errors import ConflictError
    from app.services.agent_snapshot_service import AgentSnapshotService

    docs = {"agent_1": {"_id": "agent_1", "name": "x", "version": 2, "status": "published"}}
    _mock_agent_col(monkeypatch, docs)
    _mock_snap_col(monkeypatch, [])
    with (
        patch("app.services.agent_service.AgentService.get_agent",
              new=AsyncMock(return_value=docs["agent_1"])),
        pytest.raises(ConflictError),
    ):
        await AgentSnapshotService.restore("agent_1", 1)


async def test_snapshot_idempotent_same_version(monkeypatch):
    """同版本号重复快照 → 幂等跳过（DuplicateKeyError 吞掉）。"""
    from app.services.agent_snapshot_service import AgentSnapshotService
    from pymongo.errors import DuplicateKeyError

    snap_col = _mock_snap_col(monkeypatch, [])
    snap_col.insert_one = AsyncMock(side_effect=DuplicateKeyError("dup"))

    result = await AgentSnapshotService.take_snapshot(
        {"_id": "a", "version": 1, "name": "x"}, label="update",
    )
    assert result is None  # 幂等，不炸
