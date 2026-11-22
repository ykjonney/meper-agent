"""E6 r4 复审测试：input-intent 补偿 / 真交错恢复 / lease 竞争。"""
from __future__ import annotations

import asyncio

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


class _RecDispatcher:
    def __init__(self) -> None:
        self.dispatched: list[str] = []

    async def dispatch(self, execution_id: str) -> None:
        self.dispatched.append(execution_id)


def _seed_waiting(db, *, task_status="running", with_intent=False, patch=None,
                  marker=False):
    from app.engine.execution.models import Execution, ExecutionStatus

    exe = Execution(task_id="task_r4", trigger="workflow",
                    status=ExecutionStatus.WAITING_INPUT)
    doc = exe.model_dump(by_alias=True)
    doc["input_committed_at"] = None if not marker else "2026-01-01T00:00:00Z"
    if with_intent:
        doc["input_intent"] = {
            "task_id": "task_r4",
            "variable_patch": patch or {},
            "recorded_at": "2026-01-01T00:00:00Z",
        }
    db.collections.setdefault("executions", {})[exe.id] = doc
    db.collections.setdefault("tasks", {})["task_r4"] = {
        "_id": "task_r4", "status": task_status, "variables": {},
    }
    return exe


async def test_intent_compensates_variables_written_marker_missing(fake_db):
    """崩溃点①：变量已写、marker 未落——intent 补偿：mark + resume。"""
    from app.engine.execution.recovery import RecoverySupervisor

    db = fake_db
    exe = _seed_waiting(db, with_intent=True,
                        patch={"human_decision_n1": {"decision": "approve"}})
    # 变量已被 approve 路径写入（intent 之后、marker 之前崩溃）
    db.collections["tasks"]["task_r4"]["variables"] = {
        "human_decision_n1": {"decision": "approve"}}
    db.collections["tasks"]["task_r4"]["status"] = "running"

    sup = RecoverySupervisor(repo=repo_mod.ExecutionRepository(),
                             dispatcher=_RecDispatcher())
    await sup.scan_once()
    doc = db.collections["executions"][exe.id]
    assert doc["status"] == "queued"
    assert doc["input_committed_at"] is not None
    # 变量重放幂等——值不变
    v = db.collections["tasks"]["task_r4"]["variables"]["human_decision_n1"]
    assert v == {"decision": "approve"}


async def test_intent_compensates_variables_not_yet_written(fake_db):
    """崩溃点②：intent 已记、变量未写——补偿从 intent payload 重放写入。"""
    from app.engine.execution.recovery import RecoverySupervisor

    db = fake_db
    patch = {"n1": {"decision": "approve"}, "human_decision_n1": {"d": 1}}
    exe = _seed_waiting(db, with_intent=True, patch=patch)
    db.collections["tasks"]["task_r4"]["variables"] = {}  # 变量未写（更早崩溃）
    db.collections["tasks"]["task_r4"]["status"] = "running"

    sup = RecoverySupervisor(repo=repo_mod.ExecutionRepository(),
                             dispatcher=_RecDispatcher())
    await sup.scan_once()
    doc = db.collections["executions"][exe.id]
    assert doc["status"] == "queued"
    tv = db.collections["tasks"]["task_r4"]["variables"]
    assert tv["n1"] == {"decision": "approve"}  # 从 intent 重放


async def test_no_intent_no_marker_still_waits(fake_db):
    """intent 与 marker 皆缺 = 提交流程未开始 → 不恢复（不误恢复）。"""
    from app.engine.execution.recovery import RecoverySupervisor

    db = fake_db
    exe = _seed_waiting(db)  # 无 intent
    sup = RecoverySupervisor(repo=repo_mod.ExecutionRepository(),
                             dispatcher=_RecDispatcher())
    await sup.scan_once()
    assert db.collections["executions"][exe.id]["status"] == "waiting_input"


# ── r4 P2：真交错恢复 + lease 竞争 ───────────────────────────────────


async def test_truly_interleaved_resume_no_legacy(fake_db, monkeypatch):
    """barrier 控制两个恢复请求同时读到 waiting_input 再交错执行。"""
    from app.engine.execution.models import Execution, ExecutionStatus

    db = fake_db
    exe = Execution(task_id="task_i", trigger="workflow",
                    status=ExecutionStatus.WAITING_INPUT)
    db.collections.setdefault("executions", {})[exe.id] = exe.model_dump(by_alias=True)
    db.collections["executions"][exe.id]["input_committed_at"] = None

    barrier = asyncio.Barrier(2)
    original_find_one = repo_mod.ExecutionRepository.get_execution

    async def _gated_find_one(self, execution_id):
        doc = await original_find_one(self, execution_id)
        return doc

    # 在 resume 的查询路径上设 barrier：两个协程都完成 find_one 后才放行
    import app.db.mongodb as mongodb_mod

    real_get_db = mongodb_mod.get_database

    class _GatedDB:
        def __init__(self, inner):
            self._inner = inner

        def __getitem__(self, name):
            coll = self._inner[name]
            if name != "executions":
                return coll
            return _GatedColl(coll)

    class _GatedColl:
        def __init__(self, coll):
            self._coll = coll

        def __getattr__(self, item):
            return getattr(self._coll, item)

        async def find_one(self, *a, **k):
            doc = await self._coll.find_one(*a, **k)
            if doc is not None and doc.get("status") == "waiting_input":
                await barrier.wait()  # 两请求都读 到旧状态后才继续
            return doc

    monkeypatch.setattr(
        mongodb_mod, "get_database",
        lambda: _GatedDB(real_get_db()),
    )

    legacy: list[str] = []
    dispatcher = _RecDispatcher()

    class _FakeResult:
        id = "x"

    import app.workers.tasks.workflow_execution as wf_mod

    monkeypatch.setattr(
        wf_mod.run_workflow_task, "delay",
        lambda tid: legacy.append(tid) or _FakeResult(),
    )
    from app.engine.execution import dispatcher as disp_mod

    monkeypatch.setattr(disp_mod, "get_dispatcher", lambda: dispatcher)

    import app.services.task_service as ts_mod

    await asyncio.gather(
        ts_mod.TaskService.resume_task_execution("task_i"),
        ts_mod.TaskService.resume_task_execution("task_i"),
    )
    assert legacy == []  # 无 legacy 双派发
    assert len(dispatcher.dispatched) == 2  # 两次都走 Dispatcher
    assert db.collections["executions"][exe.id]["status"] == "queued"


async def test_concurrent_lease_acquire_single_winner(fake_db):
    """两 Worker 同时竞争同一 Execution 的 lease——只有一个获 token。"""
    from app.engine.execution.lease import LeaseLostError, LeaseManager
    from app.engine.execution.models import Execution, ExecutionStatus

    db = fake_db
    exe = Execution(task_id="task_l", trigger="workflow",
                    status=ExecutionStatus.QUEUED)
    db.collections.setdefault("executions", {})[exe.id] = exe.model_dump(by_alias=True)

    lm = LeaseManager(repo_mod.ExecutionRepository())
    results = await asyncio.gather(
        lm.acquire(exe.id, "worker-a"),
        lm.acquire(exe.id, "worker-b"),
        return_exceptions=True,
    )
    winners = [r for r in results if not isinstance(r, BaseException)]
    losers = [r for r in results if isinstance(r, BaseException)]
    assert len(winners) == 1
    assert len(losers) == 1
    assert isinstance(losers[0], LeaseLostError)
    # 唯一持有者可写事实
    async with repo_mod.ExecutionRepository().transaction(
        exe.id, expected_token=winners[0].fencing_token
    ):
        pass
