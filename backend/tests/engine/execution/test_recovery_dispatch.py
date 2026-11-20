"""E3 测试：三类扫描 / 派发退避 / takeover 重派 / 重复投递互斥。

复用 E1 的内存 fake（FakeDB/FakeCollection —— 其 _match/find/管道支持
已覆盖本模块所需原语）。
"""
from __future__ import annotations

from datetime import timedelta

# 复用 E1 fake 基建（FakeDB 等）；fixture 本地注册（跨模块 import 不生效）
import app.engine.execution.repository as repo_mod
import pytest
import tests.engine.execution.test_repository_lease as _base
from app.engine.execution.dispatcher import NoopDispatcher
from app.engine.execution.recovery import RecoverySupervisor, _backoff_seconds
from app.models.base import utc_now


@pytest.fixture
def fake_db(monkeypatch):
    db = _base.FakeDB()
    monkeypatch.setattr(repo_mod, "get_database", lambda: db)
    import app.db.mongodb as app_db_mod

    monkeypatch.setattr(app_db_mod, "get_database", lambda: db)
    return db


@pytest.fixture
def env(fake_db, monkeypatch):
    """组一个完整被测环境：fake db + Noop dispatcher + supervisor。"""
    dispatcher = NoopDispatcher()
    sup = RecoverySupervisor(repo=repo_mod.ExecutionRepository(), dispatcher=dispatcher)
    return fake_db, dispatcher, sup


def _seed_queued(db, *, attempts=0, next_dispatch_at=None, state="pending"):
    from app.engine.execution.models import DispatchInfo, Execution, ExecutionStatus

    exe = Execution(trigger="workflow", status=ExecutionStatus.QUEUED)
    exe.dispatch = DispatchInfo(
        state=state, attempts=attempts, next_dispatch_at=next_dispatch_at
    )
    db.collections.setdefault("executions", {})[exe.id] = exe.model_dump(by_alias=True)
    return exe


def _seed_running_expired(db, *, token=11):
    exe = _base._seed_execution(db, token=token, expired=True)
    return exe


# ── 扫描类 1：待派发 ───────────────────────────────────────────────────


async def test_scan_dispatches_pending_queued(env):
    db, dispatcher, sup = env
    exe = _seed_queued(db)

    report = await sup.scan_once()
    assert report.redispatched == 1
    assert dispatcher.dispatched == [exe.id]

    doc = db.collections["executions"][exe.id]
    assert doc["dispatch"]["state"] == "dispatched"
    assert doc["dispatch"]["attempts"] == 1
    assert doc["dispatch"]["next_dispatch_at"] is not None  # 退避已排


async def test_scan_skips_unretired_retry(env):
    """dispatched 但退避未到期 → 不重派（防重试风暴）。"""
    db, dispatcher, sup = env
    _seed_queued(
        db, state="dispatched", attempts=1,
        next_dispatch_at=utc_now() + timedelta(seconds=30),
    )
    report = await sup.scan_once()
    assert report.redispatched == 0
    assert dispatcher.dispatched == []


async def test_two_supervisors_cannot_claim_same_dispatch_snapshot(env):
    """两个 Supervisor 使用同一旧快照并发 CAS：仅一个增加 attempts 并投递。

    这是基于内存 FakeCollection 的原子条件更新单测；MongoDB 并发语义仍需
    Replica Set 集成测试验证，不能把本测试当作真实数据库证明。
    """
    import asyncio

    db, dispatcher, sup = env
    exe = _seed_queued(db)
    snapshot = dict(db.collections["executions"][exe.id]["dispatch"])

    results = await asyncio.gather(
        sup._redispatch(exe.id, snapshot),
        sup._redispatch(exe.id, snapshot),
    )

    assert sorted(results) == [False, True]
    assert dispatcher.dispatched == [exe.id]
    doc = db.collections["executions"][exe.id]
    assert doc["dispatch"]["attempts"] == 1


async def test_stale_dispatched_snapshot_cannot_override_new_backoff(env):
    """旧 attempts/next_dispatch_at 快照不能覆盖已推进的新一代派发。"""
    db, dispatcher, sup = env
    exe = _seed_queued(
        db, state="dispatched", attempts=1,
        next_dispatch_at=utc_now() - timedelta(seconds=1),
    )
    stale = dict(db.collections["executions"][exe.id]["dispatch"])
    assert await sup._redispatch(exe.id, stale) is True
    assert await sup._redispatch(exe.id, stale) is False

    doc = db.collections["executions"][exe.id]
    assert doc["dispatch"]["attempts"] == 2
    assert dispatcher.dispatched == [exe.id]


def test_execution_celery_tasks_are_included_and_registered():
    """worker include 与实际 task registry 必须同时覆盖 E3 两个任务。"""
    from app.workers.celery_app import celery_app
    from app.workers.tasks import execution_recovery, execution_run  # noqa: F401

    included = set(celery_app.conf.include or ())
    assert "app.workers.tasks.execution_run" in included
    assert "app.workers.tasks.execution_recovery" in included
    assert "app.workers.tasks.execution_run.run_execution" in celery_app.tasks
    assert "app.workers.tasks.execution_recovery.scan" in celery_app.tasks


async def test_scan_retries_when_backoff_elapsed(env):
    db, dispatcher, sup = env
    exe = _seed_queued(
        db, state="dispatched", attempts=1,
        next_dispatch_at=utc_now() - timedelta(seconds=1),
    )
    report = await sup.scan_once()
    assert report.redispatched == 1
    doc = db.collections["executions"][exe.id]
    assert doc["dispatch"]["attempts"] == 2


async def test_dispatch_failure_leaves_retryable_state(env, monkeypatch):
    """投递失败：dispatch 元数据已落、下轮按退避重试（不丢不炸）。"""
    db, dispatcher, sup = env

    class _BrokenDispatcher:
        async def dispatch(self, execution_id):
            raise ConnectionError("broker down")

    sup._dispatcher = _BrokenDispatcher()
    exe = _seed_queued(db)

    report = await sup.scan_once()  # 不抛
    assert report.redispatched == 1
    doc = db.collections["executions"][exe.id]
    assert doc["dispatch"]["state"] == "dispatched"  # 元数据先行，下轮兜底


def test_backoff_schedule():
    assert _backoff_seconds(1) == 5
    assert _backoff_seconds(2) == 10
    assert _backoff_seconds(4) == 40
    assert _backoff_seconds(99) == 300  # 封顶 5 分钟


# ── 扫描类 2：过期接管 ─────────────────────────────────────────────────


async def test_scan_takes_over_expired_and_redispatches(env):
    db, dispatcher, sup = env
    exe = _seed_running_expired(db, token=11)

    report = await sup.scan_once()
    assert report.taken_over == 1
    assert dispatcher.dispatched == [exe.id]  # 接管后立即重派

    doc = db.collections["executions"][exe.id]
    # takeover 事件已写（supervisor 以新 token 持有期间）+ dispatch 重置 pending→dispatched
    events = [e for e in db.collections.get("execution_events", {}).values()
              if e["execution_id"] == exe.id]
    assert any(e["type"] == "execution.takeover" for e in events)
    assert doc["dispatch"]["state"] == "dispatched"
    # 接管后 lease 已释放（重派 worker 走 acquire 认领）
    assert doc["lease"] is None
    # token counter 持久递增：11 → takeover(12) → release(13)
    assert doc["fencing_token_counter"] == 13


async def test_scan_skips_active_lease(env):
    """扫描类 3：running 且 lease 活跃 → 绝不接管、不投递。"""
    db, dispatcher, sup = env
    exe = _base._seed_execution(db, token=11, expired=False)
    del exe  # 活跃执行

    report = await sup.scan_once()
    assert report.taken_over == 0
    assert report.redispatched == 0
    assert report.skipped_active == 1
    assert dispatcher.dispatched == []


# ── worker 入口：重复投递互斥 ──────────────────────────────────────────


async def test_run_execution_lease_mutex(fake_db):
    """同一 execution 投递两次：第二个认领者安静退出（CAS 互斥）。"""
    from app.workers.tasks import execution_run as run_mod

    db = fake_db
    from app.engine.execution.models import Execution, ExecutionStatus, LeaseInfo

    exe = Execution(trigger="workflow", status=ExecutionStatus.QUEUED)
    db.collections.setdefault("executions", {})[exe.id] = exe.model_dump(by_alias=True)

    # 第一次：认领成功（无 runner → 诚实失败 failed）
    r1 = await run_mod._run_async(exe.id)
    assert r1["outcome"] == "no_runner"
    doc = db.collections["executions"][exe.id]
    assert doc["status"] == "failed"
    assert doc["lease"] is None  # 已释放

    # 重新排队后模拟"重复消息迟到"：认领→释放循环可重复，但同一时刻仅一方持有
    doc["status"] = "queued"
    doc["lease"] = None
    r2 = await run_mod._run_async(exe.id)
    assert r2["outcome"] == "no_runner"

    # 已持有 lease 的执行：第二投递 lease_held
    doc2 = Execution(trigger="workflow", status=ExecutionStatus.QUEUED)
    db.collections["executions"][doc2.id] = doc2.model_dump(by_alias=True)
    db.collections["executions"][doc2.id]["lease"] = LeaseInfo(
        owner="worker-x", fencing_token=5,
        expires_at=utc_now() + timedelta(seconds=60),
    ).model_dump()
    r3 = await run_mod._run_async(doc2.id)
    assert r3["outcome"] == "lease_held"
