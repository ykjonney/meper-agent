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
            if k == "$or":
                if not any(FakeCollection._match(doc, sub) for sub in v):
                    return False
                continue
            cur: object = doc
            for part in k.split("."):
                if not isinstance(cur, dict) or part not in cur:
                    return False
                cur = cur[part]
            if isinstance(v, dict) and any(
                op in v
                for op in ("$lte", "$gte", "$in", "$nin", "$ne", "$gt", "$lt")
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
                if "$ne" in v and cur == v["$ne"]:
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

    async def find_one(self, flt, projection=None, *, session=None, sort=None, **_):  # noqa: ARG002
        matched = [d for d in self.docs.values() if self._match(d, flt)]
        if not matched:
            return None
        if sort:
            for key, direction in reversed(sort):
                matched.sort(key=lambda d: d.get(key), reverse=(direction == -1))
        return matched[0]

    def find(self, flt, *, session=None, **_):  # noqa: ARG002
        """链式游标 fake：sort/limit + async 迭代（read_events 用）。"""
        matched = [d for d in self.docs.values() if self._match(d, flt)]

        class _Cursor:
            def __init__(self, rows):
                self.rows = rows

            def sort(self, key, direction=1):
                rev = direction == -1
                return _Cursor(sorted(self.rows, key=lambda d: d[key], reverse=rev))

            def limit(self, n):
                return _Cursor(self.rows[:n])

            def __aiter__(self):
                self._iter = iter(self.rows)
                return self

            async def __anext__(self):
                try:
                    return next(self._iter)
                except StopIteration:
                    raise StopAsyncIteration from None

        return _Cursor(matched)

    async def count_documents(self, flt, **_):
        return sum(1 for d in self.docs.values() if self._match(d, flt))

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

    @classmethod
    def _resolve_pipeline_value(cls, doc: dict, v):
        """解析管道表达式：$path 引用 / $add / $ifNull / 嵌套 dict/list。"""
        if isinstance(v, str) and v.startswith("$"):
            cur: object = doc
            for part in v.lstrip("$").split("."):
                if not isinstance(cur, dict) or part not in cur:
                    return None
                cur = cur[part]
            return cur
        if isinstance(v, dict):
            if "$add" in v:
                total = 0
                for operand in v["$add"]:
                    r = cls._resolve_pipeline_value(doc, operand)
                    total += r if r is not None else 0
                return total
            if "$ifNull" in v:
                for candidate in v["$ifNull"]:
                    r = cls._resolve_pipeline_value(doc, candidate)
                    if r is not None:
                        return r
                return None
            return {k: cls._resolve_pipeline_value(doc, sv) for k, sv in v.items()}
        if isinstance(v, list):
            return [cls._resolve_pipeline_value(doc, x) for x in v]
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


async def test_expired_lease_rejects_heartbeat_and_write(fake_db):
    """PR #73 审查§4：到期即失去所有权——token 匹配不自动等同 Lease 有效。"""
    exe = _seed_execution(fake_db, token=11, expired=True, owner="worker-a")
    lm = lease_mod.LeaseManager()
    # 过期但尚未接管：也不能续约"复活"自己
    with pytest.raises(repo_mod.LeaseLostError):
        await lm.heartbeat(exe.id, "worker-a", 11)
    # 过期但 token 正确：事实写入同样被拒
    with pytest.raises(repo_mod.LeaseLostError):
        async with repo_mod.ExecutionRepository().transaction(exe.id, expected_token=11):
            pass


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


# ── PR #73 第三轮审查验收 1：release → reacquire 的 token 严格递增 ──────


async def test_release_then_reacquire_token_strictly_increments(fake_db):
    """A(token=k) release → B acquire 必须拿到 k+1——旧 token 的新事务被拒。

    修复前：acquire 默认 token=1，release 清掉整个 lease 后 reacquire
    复用历史值，旧 Worker 的在途事务会被误接受（审查 §1）。
    """

    exe = _seed_execution(fake_db, token=7, owner="worker-a")
    lm = lease_mod.LeaseManager()
    doc = fake_db.collections["executions"][exe.id]

    await lm.release(exe.id, 7)
    assert doc["lease"] is None
    # release 不清计数器：迁移语义 ifNull(counter, lease token) → 8
    assert doc.get("fencing_token_counter") == 8

    # reacquire：token 从持久 counter 接续 = 9（不复用 7）
    lease_b = await lm.acquire(exe.id, "worker-b")
    assert lease_b.fencing_token == 9

    # 旧 token=7 的事务被拒；新 token=9 可写
    with pytest.raises(repo_mod.LeaseLostError):
        async with repo_mod.ExecutionRepository().transaction(exe.id, expected_token=7):
            pass
    async with repo_mod.ExecutionRepository().transaction(exe.id, expected_token=9):
        pass


async def test_acquire_rejects_when_lease_held(fake_db):
    """lease 已被持有 → 第二个 acquire 被拒（CAS 互斥）。"""
    exe = _seed_execution(fake_db, token=5, owner="worker-a")
    lm = lease_mod.LeaseManager()
    with pytest.raises(repo_mod.LeaseLostError):
        await lm.acquire(exe.id, "worker-b")


async def test_takeover_increments_persistent_counter(fake_db):
    """takeover 同样走持久 counter：多次接管 token 严格递增。"""
    exe = _seed_execution(fake_db, token=11, expired=True, owner="worker-a")
    lm = lease_mod.LeaseManager()
    doc = fake_db.collections["executions"][exe.id]

    l1 = await lm.takeover(exe.id, "worker-b")
    assert l1.fencing_token == 12 and doc["fencing_token_counter"] == 12
    # 再次过期再接管 → 13（counter 持续递增）
    from datetime import timedelta

    from app.models.base import utc_now

    doc["lease"]["expires_at"] = utc_now() - timedelta(seconds=1)
    l2 = await lm.takeover(exe.id, "worker-c")
    assert l2.fencing_token == 13


# ── 审查验收 3：抛异常的 Notifier 不得改变已提交事务的结果 ─────────────


async def test_raising_notifier_does_not_fail_committed_txn(fake_db):
    from app.engine.execution.events import NoopNotifier, set_notifier
    from app.engine.execution.models import ExecutionEvent

    class _RaisingNotifier:
        async def notify(self, execution_id, last_seq):
            raise RuntimeError("notifier exploded")

    set_notifier(_RaisingNotifier())
    try:
        exe = _seed_execution(fake_db)
        repo = repo_mod.ExecutionRepository()
        # 事务正常完成——通知异常被 notify_committed 统一吞掉
        async with repo.transaction(exe.id, expected_token=exe.lease.fencing_token) as txn:
            await txn.append_event(
                ExecutionEvent(execution_id=exe.id, seq=0, type="step.started", producer="t")
            )
        # 事实已落库（提交成功）
        events = await repo.read_events(exe.id)
        assert len(events) == 1
    finally:
        set_notifier(NoopNotifier())


# ── 审查验收 6：相同 idempotency_key 跨 Execution 的 lookup 隔离 ────────


async def test_lookup_invocation_scoped_by_execution(fake_db):
    from app.engine.execution.models import ToolInvocation

    exe1 = _seed_execution(fake_db, token=11)
    exe2 = _seed_execution(fake_db, token=21)
    repo = repo_mod.ExecutionRepository()

    for exe in (exe1, exe2):
        inv = ToolInvocation(
            execution_id=exe.id,
            step_id="step_x",
            tool_call_id="call_1",
            tool_name="send_email",
            idempotency_key=f"{exe.id}:step_x:call_1",  # 业务键相同部分
            request_digest="sha256:abc",
        )
        # 两个 Execution 各自的幂等键（前缀含 execution_id）
        fake_db.collections.setdefault("tool_invocations", {})[inv.id] = inv.model_dump(
            by_alias=True
        )

    # 唯一索引语义 (execution_id, idempotency_key)：同名 key 只查本执行
    key = "shared-key"
    fake_db.collections["tool_invocations"]["inv2"] = {
        "_id": "inv2", "execution_id": exe2.id, "idempotency_key": key
    }
    hit = await repo.lookup_invocation(exe2.id, key)
    assert hit is not None and hit["execution_id"] == exe2.id
    assert await repo.lookup_invocation(exe1.id, key) is None
