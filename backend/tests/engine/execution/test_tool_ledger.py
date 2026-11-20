"""E5 backend 测试：MongoToolLedger——prepare 意图持久化 / lookup 隔离。"""
from __future__ import annotations

import app.engine.execution.repository as repo_mod
import pytest
import tests.engine.execution.test_repository_lease as _base
from app.engine.execution.tool_ledger import MongoToolLedger


@pytest.fixture
def fake_db(monkeypatch):
    db = _base.FakeDB()
    monkeypatch.setattr(repo_mod, "get_database", lambda: db)
    import app.db.mongodb as app_db_mod
    import app.engine.execution.tool_ledger as ledger_mod

    monkeypatch.setattr(app_db_mod, "get_database", lambda: db)
    monkeypatch.setattr(ledger_mod, "get_database", lambda: db)
    return db


async def test_prepare_persists_original_intent(fake_db):
    from agent_flow_harness.ledger import ToolInvocationDraft, digest_args

    ledger = MongoToolLedger()
    draft = ToolInvocationDraft(
        tool_call_id="call_9",
        tool_name="send_email",
        args={"to": "x@y.z", "body": "hi"},
        idempotency_key="exec_A:step_1:call_9",
        request_digest=digest_args({"to": "x@y.z", "body": "hi"}),
        step_id="step_1",
    )
    await ledger.prepare(draft)

    inv = fake_db.collections["tool_invocations"][list(
        fake_db.collections["tool_invocations"]
    )[0]]
    assert inv["execution_id"] == "exec_A"
    assert inv["status"] == "prepared"
    assert inv["request_intent"] == {"args": {"to": "x@y.z", "body": "hi"}}  # 原始意图
    assert inv["request_digest"] == draft.request_digest
    assert inv["step_id"] == "step_1"


async def test_lookup_scoped_by_execution(fake_db):
    """同 key 尾不同 execution → 隔离（与唯一索引语义一致）。"""
    from agent_flow_harness.ledger import LedgerRecord, LedgerStatus

    ledger = MongoToolLedger()
    fake_db.collections["tool_invocations"] = {
        "inv1": {"_id": "inv1", "execution_id": "exec_A",
                 "idempotency_key": "exec_A:s:call_1", "status": "succeeded",
                 "tool_call_id": "call_1", "tool_name": "t",
                 "request_digest": "d", "result_ref": "done"},
    }
    hit = await ledger.lookup("exec_A:s:call_1")
    assert isinstance(hit, LedgerRecord)
    assert hit.status == LedgerStatus.SUCCEEDED
    assert hit.result_summary == "done"
    # exec_B 同尾键查不到
    assert await ledger.lookup("exec_B:s:call_1") is None


async def test_mark_transitions(fake_db):
    from agent_flow_harness.ledger import LedgerStatus

    ledger = MongoToolLedger()
    fake_db.collections["tool_invocations"] = {
        "inv1": {"_id": "inv1", "execution_id": "exec_A",
                 "idempotency_key": "exec_A:s:call_1",
                 "status": "in_progress", "request_digest": "d"},
    }
    assert await ledger.claim("exec_A:s:call_1") is True
    assert await ledger.claim("exec_A:s:call_1") is False
    await ledger.mark(
        "exec_A:s:call_1", LedgerStatus.UNKNOWN, error="smtp timeout"
    )
    # Terminal records cannot be overwritten by a stale worker.
    await ledger.mark(
        "exec_A:s:call_1", LedgerStatus.SUCCEEDED, result_summary="stale"
    )
    inv = fake_db.collections["tool_invocations"]["inv1"]
    assert inv["status"] == "unknown"
    assert inv["error"] == "smtp timeout"
    assert inv["completed_at"] is not None
