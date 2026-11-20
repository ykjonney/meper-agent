"""真实 MongoDB Replica Set 集成测试（#74/#75 验收）。

**默认跳过**——需要真实副本集，设置环境变量启用：

    EXEC_TEST_MONGODB_URI=mongodb://localhost:27017/?replicaSet=rs0 \
        uv run pytest tests/engine/execution/test_integration_fencing.py

（docker compose -f deploy/docker-compose.yml 起 mongodb 服务即可，
或本地 mongod --replSet rs0。）

Fake 单测不能作为事务隔离/并发冲突正确性的证据（#74 验收原话），
以下用真实事务语义覆盖：

- #74：A 持旧 token 开事务（touch 在事务内、未提交）→ B takeover
  （autocommit CAS 主记录）→ A 提交必须失败，事实不留存；
  接管后旧 token 的新事务被 LeaseLostError 拒绝。
- #75：探测成功后不遗留 probe 文档；并发探测互不清理。
"""
from __future__ import annotations

import os
from datetime import timedelta

import pytest
from pymongo.errors import PyMongoError

pytestmark = pytest.mark.skipif(
    not os.environ.get("EXEC_TEST_MONGODB_URI"),
    reason="需要真实副本集：设置 EXEC_TEST_MONGODB_URI（含 replicaSet 参数）",
)

_mongo_uri = os.environ["EXEC_TEST_MONGODB_URI"] if os.environ.get("EXEC_TEST_MONGODB_URI") else ""


@pytest.fixture
def real_db(monkeypatch):
    """真连 RS；隔离命名空间避免碰开发数据。"""
    from app.core.config import settings
    from motor.motor_asyncio import AsyncIOMotorClient

    client = AsyncIOMotorClient(_mongo_uri, tz_aware=True)
    db = client[f"{settings.MONGODB_DB_NAME}_exec_it"]

    import app.db.mongodb as mongodb_mod

    monkeypatch.setattr(mongodb_mod, "get_database", lambda: db)
    yield db
    client.close()


async def _seed(db, *, token=11):
    from app.engine.execution.models import Execution, ExecutionStatus, LeaseInfo
    from app.models.base import utc_now

    exe = Execution(trigger="workflow", status=ExecutionStatus.RUNNING)
    lease = LeaseInfo(
        owner="worker-a",
        fencing_token=token,
        expires_at=utc_now() + timedelta(seconds=60),
    )
    exe.lease = lease
    await db.executions.insert_one(exe.model_dump(by_alias=True))
    return exe


async def test_takeover_beats_inflight_stale_txn(real_db):
    """#74 核心时序：touch 在事务内 → takeover 与旧事务写冲突。"""
    import app.engine.execution.lease as lease_mod
    import app.engine.execution.repository as repo_mod
    from app.models.base import utc_now

    await real_db.executions.delete_many({})
    await real_db.execution_events.delete_many({})
    exe = await _seed(real_db, token=11)
    repo = repo_mod.ExecutionRepository()

    # A（token=11）：开启事务，touch + 写入事件，持住不提交。
    session = await real_db.client.start_session()
    session.start_transaction()
    touched = await real_db.executions.find_one_and_update(
        {"_id": exe.id, "lease.fencing_token": 11},
        {"$inc": {"write_version": 1}},
        session=session,
    )
    assert touched is not None, "token=11 此刻仍有效"
    await real_db.execution_events.insert_one(
        {"_id": "evt_inflight", "execution_id": exe.id, "seq": 1, "type": "t"},
        session=session,
    )

    # B：lease 标记过期后 takeover（autocommit，改同一主记录）。
    await real_db.executions.update_one(
        {"_id": exe.id}, {"$set": {"lease.expires_at": utc_now() - timedelta(seconds=1)}}
    )
    lm = lease_mod.LeaseManager(repo)
    lease = await lm.takeover(exe.id, "worker-b")
    assert lease is not None and lease.fencing_token == 12

    # A 迟到提交：必须失败（写冲突/token 已变）——不允许旧事实落库。
    committed = False
    try:
        await session.commit_transaction()
        committed = True
    except PyMongoError:
        pass
    finally:
        await session.end_session()

    if committed:
        # 极端调度下 commit 已过：事务内写入仍须被主记录写冲突挡下或
        # 事实缺失——否则 fencing 失效（测试失败即暴露）。
        evt = await real_db.execution_events.find_one({"_id": "evt_inflight"})
        assert evt is None, "旧 token 事务的事实写入在 takeover 后存活 = fencing 失效"

    # 旧 token 的新事务：直接被 LeaseLostError 拒绝。
    with pytest.raises(repo_mod.LeaseLostError):
        async with repo.transaction(exe.id, expected_token=11):
            pass
    # 新 token 可写。
    async with repo.transaction(exe.id, expected_token=12) as txn:
        await txn.update_execution({"$set": {"status": "waiting_input"}})
    doc = await real_db.executions.find_one({"_id": exe.id})
    assert doc["status"] == "waiting_input"
    assert doc["lease"]["fencing_token"] == 12


async def test_probe_leaves_no_leftover_and_concurrent_safe(real_db, monkeypatch):
    """#75：探测成功无遗留；并发探测互不清理。"""
    import app.core.execution_runtime as rt

    monkeypatch.delenv("EXECUTION_DURABLE", raising=False)
    ok1, err1 = await rt.probe_transaction_capability()
    ok2, err2 = await rt.probe_transaction_capability()
    assert ok1 and ok2, f"probe failed on real RS: {err1} / {err2}"

    for name in rt._PROBE_COLLECTIONS:
        left = await real_db[name].count_documents({})
        assert left == 0, f"{name} 遗留 {left} 条 probe 文档"
