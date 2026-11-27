"""E2 测试：事件通知层——提交后通知 / 回滚不通知 / 通知与游标读衔接。

通知语义（events.py docstring）：只携带最新 seq、事务提交成功后发出、
丢失/乱序/重复无损（消费端一律 read_events 游标补齐）。
"""
from __future__ import annotations

import app.engine.execution.repository as repo_mod
import pytest

# 复用 E1 的内存 fake 基建（FakeDB/FakeCollection/FakeSession）
import tests.engine.execution.test_repository_lease as _base
from app.engine.execution.events import (
    EXECUTION_NOTIFY_CHANNEL,
    CollectingNotifier,
    NoopNotifier,
    RedisNotifier,
    set_notifier,
)
from app.engine.execution.models import ExecutionEvent
from tests.engine.execution.test_repository_lease import _seed_execution


@pytest.fixture
def fake_db(monkeypatch):
    """本地注册（跨模块 import fixture 会被 pytest 当普通名，ruff 也报遮蔽）——
    逻辑与 _base.fake_db 一致。"""
    db = _base.FakeDB()
    monkeypatch.setattr(repo_mod, "get_database", lambda: db)
    import app.db.mongodb as app_db_mod

    monkeypatch.setattr(app_db_mod, "get_database", lambda: db)
    return db


@pytest.fixture(autouse=True)
def _collecting_notifier():
    notifier = CollectingNotifier()
    set_notifier(notifier)
    yield notifier
    set_notifier(NoopNotifier())


async def test_notify_after_commit_with_last_seq(fake_db, _collecting_notifier):
    exe = _seed_execution(fake_db)
    repo = repo_mod.ExecutionRepository()

    async with repo.transaction(exe.id, expected_token=exe.lease.fencing_token) as txn:
        await txn.append_event(
            ExecutionEvent(execution_id=exe.id, seq=0, type="step.started", producer="t")
        )
        await txn.append_event(
            ExecutionEvent(execution_id=exe.id, seq=0, type="step.completed", producer="t")
        )

    # 一次事务多次追加 → 一条通知，携带最大 seq
    assert _collecting_notifier.calls == [(exe.id, 2)]


async def test_no_notify_on_abort(fake_db, _collecting_notifier):
    exe = _seed_execution(fake_db)
    repo = repo_mod.ExecutionRepository()

    class _BoomError(Exception):
        pass

    with pytest.raises(_BoomError):
        async with repo.transaction(exe.id, expected_token=exe.lease.fencing_token) as txn:
            await txn.append_event(
                ExecutionEvent(execution_id=exe.id, seq=0, type="step.started", producer="t")
            )
            raise _BoomError

    assert _collecting_notifier.calls == []
    # 回滚后的零落库语义由真实 RS 集成测试覆盖（fake 不模拟 abort 丢弃）：
    # test_serialized_outcome_b_takes_over_first 断言被拒事务事件数为 0。


async def test_no_notify_when_txn_has_no_events(fake_db, _collecting_notifier):
    exe = _seed_execution(fake_db)
    repo = repo_mod.ExecutionRepository()

    async with repo.transaction(exe.id, expected_token=exe.lease.fencing_token) as txn:
        await txn.update_execution({"$set": {"status": "waiting_input"}})

    assert _collecting_notifier.calls == []


async def test_consumer_catches_up_via_cursor(fake_db, _collecting_notifier):
    """通知语义的收尾验证：消费端从游标补齐，不依赖通知内容。"""
    exe = _seed_execution(fake_db)
    repo = repo_mod.ExecutionRepository()

    async with repo.transaction(exe.id, expected_token=exe.lease.fencing_token) as txn:
        await txn.append_event(
            ExecutionEvent(execution_id=exe.id, seq=0, type="execution.started", producer="t")
        )
    async with repo.transaction(exe.id, expected_token=exe.lease.fencing_token) as txn:
        await txn.append_event(
            ExecutionEvent(execution_id=exe.id, seq=0, type="step.completed", producer="t")
        )

    first = await repo.read_events(exe.id, after_seq=0, limit=1)
    assert [e["seq"] for e in first] == [1]
    rest = await repo.read_events(exe.id, after_seq=first[-1]["seq"])
    assert [e["seq"] for e in rest] == [2]


async def test_redis_notifier_publishes_and_swallows_errors(monkeypatch):
    """RedisNotifier：publish 最新 seq 字符串；Redis 故障只告警不抛。"""
    published: list[tuple[str, str]] = []

    class _FakeRedis:
        async def publish(self, channel: str, payload: str) -> int:
            published.append((channel, payload))
            return 1

    import app.db.redis as redis_mod

    async def _get_fake():
        return _FakeRedis()

    monkeypatch.setattr(redis_mod, "get_redis_client", _get_fake)

    notifier = RedisNotifier()
    await notifier.notify("exec_x", 7)
    assert published == [(EXECUTION_NOTIFY_CHANNEL.format(execution_id="exec_x"), "7")]

    # Redis 异常：吞掉（通知尽力而为）
    async def _broken():
        raise ConnectionError("redis down")

    monkeypatch.setattr(redis_mod, "get_redis_client", _broken)
    await notifier.notify("exec_x", 8)  # 不 raise
