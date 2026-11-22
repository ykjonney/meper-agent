"""E6 r3 复审测试：step_scope 幂等键 / marker 崩溃窗口 / 并发恢复不双派发。"""
from __future__ import annotations

import app.engine.execution.repository as repo_mod
import pytest
import tests.engine.execution.test_repository_lease as _base


@pytest.fixture
def fake_db(monkeypatch):
    db = _base.FakeDB()
    monkeypatch.setattr(repo_mod, "get_database", lambda: db)
    import app.db.mongodb as app_db_mod

    monkeypatch.setattr(app_db_mod, "get_database", lambda: db)
    return db


# ── r3 P1-1：step_scope 覆盖幂等键生成 ────────────────────────────────


class _RecordingLedger:
    """记录 draft 的键（只测键生成路径，不测状态机）。"""

    def __init__(self) -> None:
        self.keys: list[str] = []

    async def prepare(self, draft):
        self.keys.append(draft.idempotency_key)

    async def claim(self, key, digest):
        return True

    async def mark(self, key, status, **_):
        return None

    async def lookup(self, key):
        return None


class _FakeTool:
    name = "send_email"

    async def ainvoke(self, params):
        return f"sent:{params}"


async def test_step_scope_covers_key_generation():
    """同 Execution 两节点同 Tool → 键不同；同节点重试 → 键稳定。"""
    from agent_flow_harness.execution_context import (
        ExecutionIdentity,
        execution_identity_scope,
    )
    from agent_flow_harness.ledger import set_ledger

    ledger = _RecordingLedger()
    set_ledger(ledger)
    try:
        identity = ExecutionIdentity(execution_id="exec_k", fencing_token=1)
        with execution_identity_scope(identity):
            from app.engine.workflow.node_executor import ToolNodeExecutor

            node_a = ToolNodeExecutor("node_a", {})
            node_b = ToolNodeExecutor("node_b", {})
            tool = _FakeTool()
            params = {"to": "x@y.z"}

            # 两节点各一次
            await node_a._ledger_invoked(tool, params, "tool_X")
            await node_b._ledger_invoked(tool, params, "tool_X")
            assert ledger.keys == [
                "exec_k:node_a:tool:tool_X",
                "exec_k:node_b:tool:tool_X",
            ]

            # 同节点重试：键稳定（幂等键不含 attempt/时间因子）
            await node_a._ledger_invoked(tool, params, "tool_X")
            assert ledger.keys[2] == ledger.keys[0]
    finally:
        from agent_flow_harness.ledger import NoLedger

        set_ledger(NoLedger())


# ── r3 P1-2：marker 独立持久化 + 崩溃窗口恢复 ─────────────────────────


async def test_marker_survives_crash_before_resume(fake_db):
    """变量已存、mark 已落、resume CAS 前崩溃 → supervisor 扫描恢复。"""
    from app.engine.execution.models import Execution, ExecutionStatus
    from app.engine.execution.recovery import RecoverySupervisor
    from app.engine.execution.workflow_adapter import mark_input_committed

    db = fake_db
    exe = Execution(task_id="task_m", trigger="workflow",
                    status=ExecutionStatus.WAITING_INPUT)
    db.collections.setdefault("executions", {})[exe.id] = exe.model_dump(by_alias=True)
    db.collections["executions"][exe.id]["input_committed_at"] = None
    # Task 已离开 waiting_human（approve 已转 running）
    db.collections.setdefault("tasks", {})["task_m"] = {"_id": "task_m", "status": "running"}

    await mark_input_committed(repo_mod.ExecutionRepository(), exe.id)
    # —— 崩溃点：resume_waiting_execution 未被调用 ——

    sup = RecoverySupervisor(repo=repo_mod.ExecutionRepository(),
                             dispatcher=_NoopDispatcher())
    await sup.scan_once()
    doc = db.collections["executions"][exe.id]
    assert doc["status"] == "queued"
    assert doc["dispatch"]["state"] == "dispatched"
    assert doc["input_committed_at"] is not None


async def test_supervisor_skips_when_marker_missing(fake_db):
    """Task 离开 waiting_human 但 marker 未落（变量未写完窗口）→ 不恢复。"""
    from app.engine.execution.models import Execution, ExecutionStatus
    from app.engine.execution.recovery import RecoverySupervisor

    db = fake_db
    exe = Execution(task_id="task_n", trigger="workflow",
                    status=ExecutionStatus.WAITING_INPUT)
    db.collections.setdefault("executions", {})[exe.id] = exe.model_dump(by_alias=True)
    db.collections["executions"][exe.id]["input_committed_at"] = None
    db.collections.setdefault("tasks", {})["task_n"] = {"_id": "task_n", "status": "running"}

    sup = RecoverySupervisor(repo=repo_mod.ExecutionRepository(),
                             dispatcher=_NoopDispatcher())
    await sup.scan_once()
    assert db.collections["executions"][exe.id]["status"] == "waiting_input"


class _NoopDispatcher:
    def __init__(self) -> None:
        self.dispatched: list[str] = []

    async def dispatch(self, execution_id: str) -> None:
        self.dispatched.append(execution_id)


# ── r3 P1-3：并发恢复不回退 legacy 双派发 ────────────────────────────


async def test_concurrent_resume_no_legacy_double_dispatch(fake_db, monkeypatch):
    """A 完整恢复后（Execution 已 queued），并发 B 再恢复 → 走 Dispatcher
    而非 legacy run_workflow_task.delay（无双执行路径）。"""
    from app.engine.execution.models import Execution, ExecutionStatus

    db = fake_db
    exe = Execution(task_id="task_c", trigger="workflow",
                    status=ExecutionStatus.WAITING_INPUT)
    db.collections.setdefault("executions", {})[exe.id] = exe.model_dump(by_alias=True)
    db.collections["executions"][exe.id]["input_committed_at"] = None

    legacy_calls: list[str] = []
    dispatcher = _NoopDispatcher()

    class _FakeResult:
        id = "celery_legacy"

    import app.workers.tasks.workflow_execution as wf_mod

    monkeypatch.setattr(
        wf_mod.run_workflow_task, "delay",
        lambda task_id: legacy_calls.append(task_id) or _FakeResult(),
    )
    monkeypatch.setattr(
        "app.engine.execution.dispatcher.get_dispatcher", lambda: dispatcher
    )
    from app.engine.execution import dispatcher as disp_mod

    monkeypatch.setattr(disp_mod, "get_dispatcher", lambda: dispatcher)

    import app.services.task_service as ts_mod

    # A：完整恢复（marker + CAS + dispatch）
    await ts_mod.TaskService.resume_task_execution("task_c")
    # B：并发迟到——Execution 已 queued
    await ts_mod.TaskService.resume_task_execution("task_c")

    # 两次都走 Dispatcher；legacy 从未被调用
    assert legacy_calls == []
    assert len(dispatcher.dispatched) == 2
    doc = db.collections["executions"][exe.id]
    assert doc["status"] == "queued"
