"""执行域 E1 测试：事务级 fencing / Lease CAS / 事件 seq 分配。

用内存 fake 模拟 motor 关键原语（find_one_and_update 条件更新、
session 事务为透传——fencing 语义靠条件匹配体现，不依赖真实事务）。
"""
from __future__ import annotations

import app.engine.execution.lease as lease_mod
import app.engine.execution.repository as repo_mod
import pytest
from app.engine.execution.models import (
    Execution,
    ExecutionEvent,
    ExecutionStatus,
    LeaseInfo,
    Step,
    StepStatus,
)
from pymongo import ReturnDocument

# ── 内存 fake（只实现用到的原语；条件更新按 Mongo 语义匹配顶层与
#    点路径键；聚合管道 update 仅支持 lease takeover 的 $set+$add 形态）──


class FakeCollection:
    def __init__(self, docs: dict[str, dict]):
        self.docs = docs

    @staticmethod
    def _match(doc: dict, flt: dict) -> bool:
        for k, v in flt.items():
            cur: object = doc
            for part in k.split("."):
                if not isinstance(cur, dict) or part not in cur:
                    return False
                cur = cur[part]
            if isinstance(v, dict) and any(
                op in v for op in ("$lte", "$gte", "$in", "$nin", "$gt", "$lt")
            ):
                if "$lte" in v and not (cur is not None and cur <= v["$lte"]):
                    return False
                if "$gte" in v and not (cur is not None and cur >= v["$gte"]):
                    return False
                if "$gt" in v and not (cur is not None and cur > v["$gt"]):
                    return False
                if "$lt" in v and not (cur is not None and cur < v["$lt"]):
                    return False
                if "$in" in v and cur not in v["$in"]:
                    return False
                if "$nin" in v and cur in v["$nin"]:
                    return False
            elif cur != v:
                return False
        return True

    async def find_one_and_update(self, flt, update, *, return_document=None, session=None, **_):
        for doc in self.docs.values():
            if self._match(doc, flt):
                before = dict(doc)
                if isinstance(update, list):
                    # 聚合管道 update（takeover 形态）
                    for stage in update:
                        self._apply_pipeline_set(doc, stage["$set"])
                else:
                    if "$inc" in update:
                        for k, amt in update["$inc"].items():
                            doc[k] = doc.get(k, 0) + amt
                    if "$set" in update:
                        for k, v in update["$set"].items():
                            self._set_path(doc, k, v)
                if return_document == ReturnDocument.AFTER:
                    return doc
                return before
        return None

    async def insert_one(self, doc, *, session=None, **_):
        self.docs[doc["_id"]] = doc
        return type("I", (), {"inserted_id": doc["_id"]})()

    async def find_one(self, flt, projection=None, *, session=None, **_):  # noqa: ARG002
        for doc in self.docs.values():
            if self._match(doc, flt):
                return doc
        return None

    async def update_one(self, flt, update, *, session=None, **_):
        matched = 0
        for doc in self.docs.values():
            if self._match(doc, flt):
                matched += 1
                if isinstance(update, list):
                    for stage in update:
                        self._apply_pipeline_set(doc, stage["$set"])
                else:
                    if "$set" in update:
                        for k, v in update["$set"].items():
                            self._set_path(doc, k, v)
                    if "$inc" in update:
                        for k, amt in update["$inc"].items():
                            doc[k] = doc.get(k, 0) + amt
        return type("R", (), {"matched_count": matched})()

    @staticmethod
    def _set_path(doc: dict, path: str, value):
        parts = path.split(".")
        cur = doc
        for p in parts[:-1]:
            cur = cur.setdefault(p, {})
        cur[parts[-1]] = value

    @staticmethod
    def _resolve_pipeline_value(doc: dict, v):
        """解析管道表达式：{"$add": ["$path", n]} 递归解析嵌套 dict。"""
        if isinstance(v, dict):
            if "$add" in v:
                base = doc
                for part in v["$add"][0].lstrip("$").split("."):
                    base = base[part]
                return base + v["$add"][1]
            return {k: FakeCollection._resolve_pipeline_value(doc, sv) for k, sv in v.items()}
        return v

    @classmethod
    def _apply_pipeline_set(cls, doc: dict, set_expr: dict):
        for k, v in set_expr.items():
            cls._set_path(doc, k, cls._resolve_pipeline_value(doc, v))

    def __getitem__(self, _):  # pragma: no cover
        raise NotImplementedError


class FakeSession:
    async def _await_self(self):
        return self

    def __await__(self):
        return self._await_self().__await__()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def start_transaction(self):
        return self  # async CM：事务体

    async def commit_transaction(self):
        return None

    async def abort_transaction(self):
        return None


class FakeClient:
    def start_session(self):
        return FakeSession()


class FakeDB:
    def __init__(self):
        self.client = FakeClient()
        self.collections: dict[str, dict[str, dict]] = {}

    def get_collection(self, name):
        return FakeCollection(self.collections.setdefault(name, {}))

    def __getitem__(self, name):
        return self.get_collection(name)


@pytest.fixture
def fake_db(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr(repo_mod, "get_database", lambda: db)
    import app.db.mongodb as app_db_mod

    monkeypatch.setattr(app_db_mod, "get_database", lambda: db)
    return db


def _seed_execution(db: FakeDB, *, token: int = 11, expired: bool = False, owner="worker-a"):
    from datetime import timedelta

    from app.models.base import utc_now

    exe = Execution(trigger="workflow", status=ExecutionStatus.RUNNING)
    lease = LeaseInfo(
        owner=owner,
        fencing_token=token,
        expires_at=utc_now() + (-timedelta(seconds=1) if expired else timedelta(seconds=60)),
    )
    exe.lease = lease
    db.collections.setdefault("executions", {})[exe.id] = exe.model_dump(by_alias=True)
    return exe


# ── Repository：事务级 fencing ─────────────────────────────────────────


async def test_transaction_touches_write_version(fake_db):
    exe = _seed_execution(fake_db, token=11)
    repo = repo_mod.ExecutionRepository()
    doc_before = dict(fake_db.collections["executions"][exe.id])

    async with repo.transaction(exe.id, expected_token=11) as txn:
        await txn.update_execution({"$set": {"status": "waiting_input"}})

    doc = fake_db.collections["executions"][exe.id]
    assert doc["write_version"] == doc_before["write_version"] + 1  # 铁律 4：先触碰主记录
    assert doc["status"] == "waiting_input"


async def test_stale_token_rejected(fake_db):
    """旧 token（被接管后）→ LeaseLostError，事务体不执行。"""
    exe = _seed_execution(fake_db, token=12)
    repo = repo_mod.ExecutionRepository()

    with pytest.raises(repo_mod.LeaseLostError):
        async with repo.transaction(exe.id, expected_token=11) as txn:
            await txn.update_execution({"$set": {"status": "failed"}})

    assert fake_db.collections["executions"][exe.id]["status"] == "running"


async def test_missing_execution_raises_keyerror(fake_db):
    repo = repo_mod.ExecutionRepository()
    with pytest.raises(KeyError):
        async with repo.transaction("exec_missing", expected_token=1):
            pass


async def test_event_seq_allocated_atomically_in_txn(fake_db):
    """seq 由主记录计数器 $inc 分配（AFTER 语义），事件与状态同事务。"""
    exe = _seed_execution(fake_db)
    repo = repo_mod.ExecutionRepository()

    async with repo.transaction(exe.id, expected_token=exe.lease.fencing_token) as txn:
        seq1 = await txn.append_event(ExecutionEvent(execution_id=exe.id, seq=0, type="step.started", producer="test"))
        seq2 = await txn.append_event(ExecutionEvent(execution_id=exe.id, seq=0, type="step.completed", producer="test"))

    assert (seq1, seq2) == (1, 2)
    events = fake_db.collections["execution_events"]
    assert sorted(e["seq"] for e in events.values()) == [1, 2]


async def test_step_write_in_txn(fake_db):
    exe = _seed_execution(fake_db)
    repo = repo_mod.ExecutionRepository()

    step = Step(
        execution_id=exe.id,
        step_seq=1,
        kind="workflow_node",
        idempotency_key=f"{exe.id}:node_a",
    )
    async with repo.transaction(exe.id, expected_token=exe.lease.fencing_token) as txn:
        await txn.insert_step(step)
        await txn.update_step(step.id, {"$set": {"status": StepStatus.SUCCEEDED}})

    doc = fake_db.collections["execution_steps"][step.id]
    assert doc["status"] == "succeeded"


async def test_fenced_diagnostic_bypasses_token(fake_db):
    """诊断通道：不带调用方 token 写入 execution.fenced 事件。"""
    exe = _seed_execution(fake_db, token=12)
    repo = repo_mod.ExecutionRepository()

    await repo.record_fenced_diagnostic(exe.id, rejected_token=11, context="takeover-race")

    events = fake_db.collections["execution_events"]
    ev = next(iter(events.values()))
    assert ev["type"] == "execution.fenced"
    assert ev["producer"] == "system"
    assert ev["payload"]["rejected_token"] == 11


# ── LeaseManager：CAS ─────────────────────────────────────────────────


async def test_lease_heartbeat_extends_expiry(fake_db):
    exe = _seed_execution(fake_db, token=11, owner="worker-a")
    lm = lease_mod.LeaseManager()
    lease = await lm.heartbeat(exe.id, "worker-a", 11)
    assert lease.fencing_token == 11
    assert fake_db.collections["executions"][exe.id]["lease"]["owner"] == "worker-a"


async def test_lease_heartbeat_wrong_token_lost(fake_db):
    exe = _seed_execution(fake_db, token=12, owner="worker-b")
    lm = lease_mod.LeaseManager()
    with pytest.raises(repo_mod.LeaseLostError):
        await lm.heartbeat(exe.id, "worker-a", 11)


async def test_lease_takeover_requires_expiry(fake_db):
    """未过期 → 接管失败（None）；过期 → token+1。"""
    exe = _seed_execution(fake_db, token=11, expired=False, owner="worker-a")
    lm = lease_mod.LeaseManager()
    assert await lm.takeover(exe.id, "worker-b") is None  # 未过期拒绝

    fake_db.collections["executions"][exe.id]["lease"]["expires_at"] = (
        fake_db.collections["executions"][exe.id]["lease"]["heartbeat_at"]  # 已过期
    )
    lease = await lm.takeover(exe.id, "worker-b")
    assert lease is not None
    assert lease.fencing_token == 12
    assert lease.owner == "worker-b"
    # 旧 token 在接管后写入被拒（fencing 生效的闭环验证）
    with pytest.raises(repo_mod.LeaseLostError):
        async with repo_mod.ExecutionRepository().transaction(exe.id, expected_token=11):
            pass
    # 新 token 可写
    async with repo_mod.ExecutionRepository().transaction(exe.id, expected_token=12):
        pass


async def test_lease_release(fake_db):
    exe = _seed_execution(fake_db, token=11)
    lm = lease_mod.LeaseManager()
    await lm.release(exe.id, 11)
    assert fake_db.collections["executions"][exe.id]["lease"] is None
