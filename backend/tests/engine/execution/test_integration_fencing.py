"""真实 MongoDB Replica Set 集成测试（#74/#75 + PR #73 Conversation 审查）。

**默认跳过**——需要真实副本集，设置环境变量启用：

    EXEC_TEST_MONGODB_URI=mongodb://localhost:27018/?replicaSet=rs0 \
        uv run pytest tests/engine/execution/test_integration_fencing.py

（本地临时实例：`mongod --dbpath <tmp> --port 27018 --replSet rs0` 后
`mongosh --port 27018 --eval 'rs.initiate(...)'`。）

Fake 单测不能作为事务隔离/并发冲突正确性的证据（#74 验收原话）。
本文件用**真实 Repository/LeaseManager 入口** + 真实事务语义覆盖：

- #74/审查§1：两种**合法串行结果**（真交叠的并发时序本身不确定，
  MongoDB 事务对此的裁决就是"二者只活一个"——分别验证两个方向）：
  1. A 先提交：事实落库成功，此后 B 才能 takeover；接管后旧 token
     的续约与写入均被拒。
  2. B 先接管：旧 token 立即失去写入资格，事实零落库。
- #75/审查§2：``asyncio.gather`` 两个探测真交叠，各自只清理自己的
  probe_id，均正确报告能力，最终零遗留。
"""
from __future__ import annotations

import asyncio
import os
from datetime import timedelta

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("EXEC_TEST_MONGODB_URI"),
    reason="需要真实副本集：设置 EXEC_TEST_MONGODB_URI（含 replicaSet 参数）",
)

_mongo_uri = os.environ["EXEC_TEST_MONGODB_URI"] if os.environ.get("EXEC_TEST_MONGODB_URI") else ""


@pytest.fixture
async def real_db(monkeypatch):
    """真连 RS；隔离命名空间（独立 db）避免碰开发数据。

    async fixture：client 在测试自己的 event loop 内创建/关闭——
    sync fixture 建 client 会绑到 loop 外的默认 loop，跨用例污染
    （"Event loop is closed"）。
    """
    import app.db.mongodb as mongodb_mod
    from app.core.config import settings
    from app.engine.execution import repository as repo_mod
    from motor.motor_asyncio import AsyncIOMotorClient

    client = AsyncIOMotorClient(_mongo_uri, tz_aware=True)
    db = client[f"{settings.MONGODB_DB_NAME}_exec_it"]

    # repository.py 顶层 from-import 已绑定原函数——两处都要 patch，
    # 否则执行域写入会漏到 app 单例 client（连到开发库）。
    monkeypatch.setattr(mongodb_mod, "get_database", lambda: db)
    monkeypatch.setattr(repo_mod, "get_database", lambda: db)
    yield db
    client.close()


async def _seed(db, *, token=11, expired=False):
    from app.engine.execution.models import Execution, ExecutionStatus, LeaseInfo
    from app.models.base import utc_now

    exe = Execution(trigger="workflow", status=ExecutionStatus.RUNNING)
    lease = LeaseInfo(
        owner="worker-a",
        fencing_token=token,
        expires_at=utc_now()
        + (-timedelta(seconds=1) if expired else timedelta(seconds=120)),
    )
    exe.lease = lease
    await db.executions.insert_one(exe.model_dump(by_alias=True))
    return exe


async def _events_of(db, execution_id: str) -> int:
    return await db.execution_events.count_documents({"execution_id": execution_id})


async def test_serialized_outcome_a_commits_first(real_db):
    """合法结果一：A 的事务先提交——事实落库，之后 B 才能接管。

    A 的事实写入走**真实** ``ExecutionRepository.transaction()`` 入口
    （审查 §1：不得绕过实现手工模拟 touch）。
    """
    import app.engine.execution.lease as lease_mod
    import app.engine.execution.repository as repo_mod
    from app.engine.execution.models import ExecutionEvent
    from app.models.base import utc_now

    await real_db.executions.delete_many({})
    await real_db.execution_events.delete_many({})
    exe = await _seed(real_db, token=11)
    repo = repo_mod.ExecutionRepository()

    # A（token=11，lease 有效）：完整走真实入口提交一条事实。
    async with repo.transaction(exe.id, expected_token=11) as txn:
        await txn.append_event(
            ExecutionEvent(
                execution_id=exe.id, seq=0, type="step.started", producer="it-test"
            )
        )
    assert await _events_of(real_db, exe.id) == 1

    # lease 过期后 B takeover 成功（token 11 → 12）。
    await real_db.executions.update_one(
        {"_id": exe.id},
        {"$set": {"lease.expires_at": utc_now() - timedelta(seconds=1)}},
    )
    lm = lease_mod.LeaseManager(repo)
    lease = await lm.takeover(exe.id, "worker-b")
    assert lease is not None and lease.fencing_token == 12

    # 接管后：旧 token 的续约与事实写入均被拒（含过期语义）。
    with pytest.raises(repo_mod.LeaseLostError):
        await lm.heartbeat(exe.id, "worker-a", 11)
    with pytest.raises(repo_mod.LeaseLostError):
        async with repo.transaction(exe.id, expected_token=11):
            pass
    assert await _events_of(real_db, exe.id) == 1  # 旧 token 零新增事实

    # 新 token 可写，主记录 token/事实一致。
    async with repo.transaction(exe.id, expected_token=12) as txn:
        await txn.append_event(
            ExecutionEvent(
                execution_id=exe.id, seq=0, type="step.completed", producer="it-test"
            )
        )
    doc = await real_db.executions.find_one({"_id": exe.id})
    assert doc["lease"]["fencing_token"] == 12
    assert await _events_of(real_db, exe.id) == 2


async def test_serialized_outcome_b_takes_over_first(real_db):
    """合法结果二：B 先接管——旧 token 立即失去资格，事实零落库。"""
    import app.engine.execution.lease as lease_mod
    import app.engine.execution.repository as repo_mod
    from app.engine.execution.models import ExecutionEvent

    await real_db.executions.delete_many({})
    await real_db.execution_events.delete_many({})
    exe = await _seed(real_db, token=11, expired=True)
    repo = repo_mod.ExecutionRepository()
    lm = lease_mod.LeaseManager(repo)

    lease = await lm.takeover(exe.id, "worker-b")
    assert lease is not None and lease.fencing_token == 12

    # A（旧 token）：事务被 LeaseLostError 拒绝（token 已被接管 + lease 也已过期）。
    with pytest.raises(repo_mod.LeaseLostError):
        async with repo.transaction(exe.id, expected_token=11) as txn:
            await txn.append_event(
                ExecutionEvent(
                    execution_id=exe.id, seq=0, type="step.started", producer="it-test"
                )
            )
    assert await _events_of(real_db, exe.id) == 0  # 零事实落库
    doc = await real_db.executions.find_one({"_id": exe.id})
    assert doc["lease"]["fencing_token"] == 12


async def test_expired_lease_rejects_heartbeat_and_write_before_takeover(real_db):
    """审查§4：到期即失去所有权——未接管窗口内，过期 Worker 也不能续约/写入。"""
    import app.engine.execution.lease as lease_mod
    import app.engine.execution.repository as repo_mod

    await real_db.executions.delete_many({})
    await real_db.execution_events.delete_many({})
    exe = await _seed(real_db, token=11, expired=True)  # 过期但尚未 takeover
    repo = repo_mod.ExecutionRepository()
    lm = lease_mod.LeaseManager(repo)

    with pytest.raises(repo_mod.LeaseLostError):
        await lm.heartbeat(exe.id, "worker-a", 11)  # 不能"复活"自己的所有权
    with pytest.raises(repo_mod.LeaseLostError):
        async with repo.transaction(exe.id, expected_token=11):
            pass
    # takeover 仍可进行（接管者视角不受影响）。
    lease = await lm.takeover(exe.id, "worker-b")
    assert lease is not None and lease.fencing_token == 12


async def test_probe_truly_concurrent(real_db, monkeypatch):
    """#75/审查§2：gather 真交叠的两个探测——互不清理、能力结论各自正确、零遗留。"""
    import app.core.execution_runtime as rt

    monkeypatch.delenv("EXECUTION_DURABLE", raising=False)
    (ok1, err1), (ok2, err2) = await asyncio.gather(
        rt.probe_transaction_capability(),
        rt.probe_transaction_capability(),
    )
    assert ok1 and ok2, f"probe failed on real RS: {err1} / {err2}"

    for name in rt._PROBE_COLLECTIONS:
        left = await real_db[name].count_documents({})
        assert left == 0, f"{name} 遗留 {left} 条 probe 文档"


async def test_release_reacquire_and_diagnostic_seq_atomicity(real_db):
    """第三轮审查验收 1+2（真实 RS）：

    - release → reacquire：token 从持久 counter 严格递增，旧 token 被拒；
    - record_fenced_diagnostic：seq 分配与事件插入同事务——事件序号连续、
      无永久缺口（游标消费不丢事件）。
    """
    import app.engine.execution.lease as lease_mod
    import app.engine.execution.repository as repo_mod

    await real_db.executions.delete_many({})
    await real_db.execution_events.delete_many({})
    exe = await _seed(real_db, token=11)
    repo = repo_mod.ExecutionRepository()
    lm = lease_mod.LeaseManager(repo)

    # 先提交两条普通事件（token=11）
    from app.engine.execution.models import ExecutionEvent

    async with repo.transaction(exe.id, expected_token=11) as txn:
        await txn.append_event(
            ExecutionEvent(execution_id=exe.id, seq=0, type="step.started", producer="it")
        )
    await lm.release(exe.id, 11)

    # reacquire：token 必须 > 11（持久 counter），旧 token=11 事务被拒
    lease_b = await lm.acquire(exe.id, "worker-b")
    assert lease_b.fencing_token > 11
    with pytest.raises(repo_mod.LeaseLostError):
        async with repo.transaction(exe.id, expected_token=11):
            pass
    async with repo.transaction(exe.id, expected_token=lease_b.fencing_token):
        pass

    # 诊断事件若干条 + 普通事件混合：最终事件 seq 集合必须无缺口
    await repo.record_fenced_diagnostic(exe.id, rejected_token=11, context="it-test")
    async with repo.transaction(exe.id, expected_token=lease_b.fencing_token) as txn:
        await txn.append_event(
            ExecutionEvent(execution_id=exe.id, seq=0, type="step.completed", producer="it")
        )
    await repo.record_fenced_diagnostic(exe.id, rejected_token=9, context="it-test-2")

    cursor = repo_mod.ExecutionRepository()
    seqs = [e["seq"] async for e in real_db.execution_events.find(
        {"execution_id": exe.id}, {"seq": 1}
    ).sort("seq", 1)]
    assert seqs == list(range(1, len(seqs) + 1)), f"事件序号出现缺口: {seqs}"
    # 主记录 counter 与最大事件序号一致
    doc = await real_db.executions.find_one({"_id": exe.id})
    assert doc["event_seq_counter"] == max(seqs)
    del cursor
