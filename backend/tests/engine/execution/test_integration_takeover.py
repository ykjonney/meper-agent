"""E6 takeover 并发集成测试（真实 RS）——Adapter 的 fencing 闭环验收。

场景（用户指定的 E6 验收）：worker A 以真实 identity+token 执行工具调用
（账本 fenced 写入 + lease 心跳）→ supervisor takeover → A 的后续账本写入
被拒、心跳失败终止 Runner、账本终态不被旧 Worker 覆盖。
"""
from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

pytestmark = pytest.mark.skipif(
    not __import__("os").environ.get("EXEC_TEST_MONGODB_URI"),
    reason="需要真实副本集：设置 EXEC_TEST_MONGODB_URI（含 replicaSet 参数）",
)

_mongo_uri = __import__("os").environ.get("EXEC_TEST_MONGODB_URI", "")


@pytest.fixture
async def real_db(monkeypatch):
    from app.core.config import settings
    from motor.motor_asyncio import AsyncIOMotorClient

    client = AsyncIOMotorClient(_mongo_uri, tz_aware=True)
    db = client[f"{settings.MONGODB_DB_NAME}_exec_it"]

    import app.db.mongodb as mongodb_mod
    import app.engine.execution.repository as repo_mod
    import app.engine.execution.tool_ledger as ledger_mod

    monkeypatch.setattr(mongodb_mod, "get_database", lambda: db)
    monkeypatch.setattr(repo_mod, "get_database", lambda: db)
    monkeypatch.setattr(ledger_mod, "get_database", lambda: db)
    yield db
    client.close()


async def _seed(db):
    from app.engine.execution.models import Execution, ExecutionStatus, LeaseInfo
    from app.models.base import utc_now

    exe = Execution(
        task_id="task_e6", trigger="workflow", status=ExecutionStatus.RUNNING
    )
    exe.lease = LeaseInfo(
        owner="worker-a",
        fencing_token=1,
        expires_at=utc_now() + timedelta(seconds=60),
    )
    await db.executions.insert_one(exe.model_dump(by_alias=True))
    return exe


async def test_takeover_fences_ledger_and_heartbeat(real_db):
    """A 持 token 执行 → B takeover → A 账本写被拒/心跳丢失/终态不被覆盖。"""
    from agent_flow_harness.execution_context import (
        ExecutionIdentity,
        execution_identity_scope,
    )
    from agent_flow_harness.ledger import (
        LedgerStatus,
        ToolInvocationDraft,
        digest_args,
        set_ledger,
    )
    from app.engine.execution.lease import LeaseManager, lease_heartbeat
    from app.engine.execution.repository import ExecutionRepository, LeaseLostError
    from app.engine.execution.tool_ledger import MongoToolLedger

    db = real_db
    await db.executions.delete_many({})
    await db.execution_events.delete_many({})
    await db.tool_invocations.delete_many({})
    exe = await _seed(db)

    repo = ExecutionRepository()
    lm = LeaseManager(repo)
    set_ledger(MongoToolLedger())
    identity = ExecutionIdentity(execution_id=exe.id, step_id="node_a", fencing_token=1)

    # ── A：正常执行一段（账本 prepare+claim+mark 成功，心跳可续约）──
    with execution_identity_scope(identity):
        args = {"to": "x@y.z"}
        draft = ToolInvocationDraft(
            tool_call_id="call_1", tool_name="send_email", args=args,
            idempotency_key=identity.tool_idempotency_key("call_1"),
            request_digest=digest_args(args),
        )
        ledger = MongoToolLedger()
        await ledger.prepare(draft)
        assert await ledger.claim(draft.idempotency_key, draft.request_digest)
        await ledger.mark(
            draft.idempotency_key, LedgerStatus.SUCCEEDED, result_summary="ok"
        )
        await lm.heartbeat(exe.id, "worker-a", 1)  # 心跳正常

    # ── B：lease 过期后 takeover ──
    from app.models.base import utc_now

    await db.executions.update_one(
        {"_id": exe.id},
        {"$set": {"lease.expires_at": utc_now() - timedelta(seconds=1)}},
    )
    lease_b = await lm.takeover(exe.id, "supervisor")
    assert lease_b is not None and lease_b.fencing_token == 2

    # ── A（旧 token=1）：账本 fenced 写入被拒 ──
    with execution_identity_scope(identity):
        new_draft = ToolInvocationDraft(
            tool_call_id="call_2", tool_name="send_email", args={"to": "other"},
            idempotency_key=identity.tool_idempotency_key("call_2"),
            request_digest=digest_args({"to": "other"}),
        )
        with pytest.raises(LeaseLostError):
            await ledger.prepare(new_draft)  # fenced：touch 拒绝
        with pytest.raises(LeaseLostError):
            await lm.heartbeat(exe.id, "worker-a", 1)  # 心跳丢失
        # 旧 token 不能覆盖已写入的终态——fenced 写直接被拒（比静默更强）
        with pytest.raises(LeaseLostError):
            await ledger.mark(
                draft.idempotency_key, LedgerStatus.UNKNOWN, error="stale overwrite"
            )
    doc = await db.tool_invocations.find_one({"idempotency_key": draft.idempotency_key})
    assert doc["status"] == "succeeded"  # 终态未被旧 Worker 碰

    # ── lease_heartbeat 语义：A 的 Runner 被心跳失败终止 ──
    from app.core.config import settings as app_settings

    monkeypatch_holder = pytest.MonkeyPatch()
    monkeypatch_holder.setattr(app_settings, "EXECUTION_LEASE_HEARTBEAT_SECONDS", 0.05)

    async def _runner_heartbeat_loss():
        async with lease_heartbeat(lm, exe.id, "worker-a", 1):
            await asyncio.sleep(0.2)  # 模拟 Runner 执行中
        return "runner-finished"

    try:
        # 传播形态二选一均合法：心跳子任务先抛 LeaseLostError（finally 的
        # await 传播），或 parent cancel 先到（Runner 收到 CancelledError）。
        task = asyncio.create_task(_runner_heartbeat_loss())
        with pytest.raises((asyncio.CancelledError, LeaseLostError)):
            await task
    finally:
        monkeypatch_holder.undo()

    # ── B（新 token=2）：可正常写账本/事实 ──
    identity_b = ExecutionIdentity(
        execution_id=exe.id, step_id="node_a", fencing_token=2
    )
    with execution_identity_scope(identity_b):
        await ledger.prepare(new_draft)
        assert await ledger.claim(new_draft.idempotency_key, new_draft.request_digest)
    # 两个幂等键并存（node 维度），call_1 原文完好
    count = await db.tool_invocations.count_documents({"execution_id": exe.id})
    assert count == 2
