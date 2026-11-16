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
            "agent_1", name="新名", system_prompt="role text", can_spawn_agents=False,
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


# ── 草稿层（draft overlay）：published 编辑写草稿、publish 合并、archive 回落 ──


async def test_update_published_writes_draft_overlay(monkeypatch):
    """published update：写入 draft 子文档（clone 顶层+变更），顶层与 version 不动、不快照。"""
    from app.services.agent_service import AgentService

    docs = {"agent_1": {
        "_id": "agent_1", "name": "线上名", "system_prompt": "线上版", "version": 5,
        "status": "published", "skill_ids": ["s1"],
        "spawned_by_agent_id": "parent_9", "created_at": "t0", "updated_at": "t0",
    }}
    agent_col = _mock_agent_col(monkeypatch, docs)
    snap_col = _mock_snap_col(monkeypatch, [])

    with patch("app.services.agent_service._resolve_custom_tools", new=AsyncMock(return_value=[])):
        await AgentService.update_agent(
            "agent_1", name="草稿名", system_prompt="草稿版", can_spawn_agents=False,
        )

    # 不快照、version 不递增
    snap_col.insert_one.assert_not_awaited()
    set_op = agent_col.update_one.await_args.args[1]["$set"]
    assert "version" not in set_op
    assert "name" not in set_op  # 顶层 name 不变
    # draft = clone 顶层（排除身份/生命周期/审计字段）+ merge 变更
    draft = set_op["draft"]
    assert draft["name"] == "草稿名"
    assert draft["system_prompt"] == "草稿版"
    assert draft["skill_ids"] == ["s1"]  # 未变更字段从顶层带过来
    for excluded in ("_id", "status", "version", "created_at", "spawned_by_agent_id"):
        assert excluded not in draft


async def test_update_draft_state_still_bumps_version(monkeypatch):
    """draft/archived 状态 update：现状不变——快照 + version 递增 + 直写顶层。"""
    from app.services.agent_service import AgentService

    docs = {"agent_1": {"_id": "agent_1", "name": "旧名", "version": 2, "status": "draft"}}
    agent_col = _mock_agent_col(monkeypatch, docs)
    snap_col = _mock_snap_col(monkeypatch, [])

    with patch("app.services.agent_service._resolve_custom_tools", new=AsyncMock(return_value=[])):
        await AgentService.update_agent("agent_1", name="新名", can_spawn_agents=False)

    snap_col.insert_one.assert_awaited_once()
    set_op = agent_col.update_one.await_args.args[1]["$set"]
    assert set_op["version"] == 3
    assert set_op["name"] == "新名"
    assert "draft" not in set_op


async def test_publish_merges_draft_and_bumps_version(monkeypatch):
    """publish 有草稿：发布前快照（label=publish）→ 草稿合并顶层 + version+1 → 清 draft。"""
    from app.services.agent_service import AgentService

    docs = {"agent_1": {
        "_id": "agent_1", "name": "线上名", "system_prompt": "线上版", "version": 5,
        "status": "published",
        "draft": {"name": "草稿名", "system_prompt": "草稿版"},
    }}
    agent_col = _mock_agent_col(monkeypatch, docs)
    snap_col = _mock_snap_col(monkeypatch, [])

    await AgentService.publish_agent("agent_1")

    # 发布前线上版进快照
    inserted = snap_col.insert_one.await_args.args[0]
    assert inserted["label"] == "publish"
    assert inserted["snapshot_of_version"] == 5
    assert inserted["doc"]["system_prompt"] == "线上版"
    # 合并：草稿字段写顶层、version+1、status=published、清 draft
    op = agent_col.update_one.await_args.args[1]
    assert op["$set"]["status"] == "published"
    assert op["$set"]["name"] == "草稿名"
    assert op["$set"]["system_prompt"] == "草稿版"
    assert op["$set"]["version"] == 6
    assert op["$unset"] == {"draft": ""}


async def test_publish_without_draft_only_flips_status(monkeypatch):
    """publish 无草稿（draft/archived 首次上架）：仅状态翻转，不快照不动 version。"""
    from app.services.agent_service import AgentService

    docs = {"agent_1": {"_id": "agent_1", "name": "x", "version": 2, "status": "draft"}}
    agent_col = _mock_agent_col(monkeypatch, docs)
    snap_col = _mock_snap_col(monkeypatch, [])

    await AgentService.publish_agent("agent_1")

    snap_col.insert_one.assert_not_awaited()
    op = agent_col.update_one.await_args.args[1]
    assert op["$set"]["status"] == "published"
    assert "version" not in op["$set"]
    assert "$unset" not in op


async def test_publish_draft_name_conflict_rejected(monkeypatch):
    """草稿里的名字在发布时才真正占用——冲突则发布失败。"""
    from app.core.errors import ConflictError
    from app.services.agent_service import AgentService

    docs = {"agent_1": {
        "_id": "agent_1", "name": "线上名", "version": 1, "status": "published",
        "draft": {"name": "别人占用的名"},
    }}
    agent_col = _mock_agent_col(monkeypatch, docs)

    # name-conflict 查询（_id: {$ne}）返回占用者
    async def _find_one(q, **k):
        if "_id" in q and isinstance(q["_id"], str):
            return docs.get(q["_id"])
        if "$ne" in q.get("_id", {}):
            return {"_id": "other", "name": q["name"]}
        return None

    agent_col.find_one = AsyncMock(side_effect=_find_one)

    with pytest.raises(ConflictError):
        await AgentService.publish_agent("agent_1")
    agent_col.update_one.assert_not_awaited()  # 校验失败不落库


async def test_archive_merges_draft_back(monkeypatch):
    """归档：草稿修改合并回顶层（archived 顶层即可编辑层），清 draft，工作不丢。"""
    from app.services.agent_service import AgentService

    docs = {"agent_1": {
        "_id": "agent_1", "name": "线上名", "system_prompt": "线上版", "version": 3,
        "status": "published",
        "draft": {"name": "草稿名", "system_prompt": "草稿版"},
    }}
    agent_col = _mock_agent_col(monkeypatch, docs)
    _mock_snap_col(monkeypatch, [])

    await AgentService.archive_agent("agent_1")

    op = agent_col.update_one.await_args.args[1]
    assert op["$set"]["status"] == "archived"
    assert op["$set"]["name"] == "草稿名"
    assert op["$set"]["system_prompt"] == "草稿版"
    assert "version" not in op["$set"]  # 归档不是版本事件
    assert op["$unset"] == {"draft": ""}


async def test_restore_discards_stale_draft(monkeypatch):
    """回滚：快照 doc 意外携带 draft 时丢弃（旧草稿基于回滚前内容，会脱节）。"""
    from app.services.agent_snapshot_service import AgentSnapshotService

    docs = {"agent_1": {"_id": "agent_1", "name": "当前", "version": 5, "status": "draft"}}
    agent_col = _mock_agent_col(monkeypatch, docs)
    snaps = [
        {"_id": "s1", "agent_id": "agent_1", "snapshot_of_version": 3,
         "doc": {"_id": "agent_1", "name": "旧名", "version": 3, "status": "draft",
                  "draft": {"name": "陈年草稿"}},
         },
    ]
    _mock_snap_col(monkeypatch, snaps)

    from app.services.agent_service import AgentService

    with (
        patch("app.services.agent_service.AgentService.get_agent",
              new=AsyncMock(side_effect=lambda aid: docs.get(aid))),
        patch.object(AgentService, '_collection', staticmethod(lambda: agent_col)),
    ):
        await AgentSnapshotService.restore("agent_1", 3)

    restored_doc = agent_col.replace_one.await_args.args[1]
    assert "draft" not in restored_doc
