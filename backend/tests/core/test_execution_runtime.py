"""执行域运行时前提检查测试（#64 / PR #73 E0）。

覆盖矩阵（对齐审查要求）：
- 事务能力探测：成功 / standalone 失败归因。
- fail-closed：EXECUTION_DURABLE=true 且探测失败 → RuntimeError。
- 显式降级：EXECUTION_DURABLE=false → 不 raise，状态明示 non-durable。
- /health 投影：未初始化 / 已初始化的字段形态。
"""
from __future__ import annotations

import app.core.execution_runtime as rt
import pytest


class _FakeCollection:
    """内存集合：记录 insert 的文档，delete_many 按 probe_id 精确删——
    用于验证 #75 的清理语义（只删自己的，不动他人/不 drop 集合）。"""

    def __init__(self):
        self.docs: list[dict] = []
        self.delete_errors = False

    async def insert_one(self, doc, session=None):  # noqa: ARG002
        self.docs.append(dict(doc))
        return None

    async def delete_many(self, flt):
        if self.delete_errors:
            raise RuntimeError("cleanup failed")
        self.docs = [d for d in self.docs if not all(d.get(k) == v for k, v in flt.items())]


class _OkSession:
    """支持事务的会话（replica set 形态）。motor 的 start_session 返回
    既可 await 又可 async-with 的对象，fake 需同时实现两种协议。

    真实语义（#75）：事务 CM 正常退出 = 自动提交——fake 以
    ``committed`` 标记模拟，供断言探测不会在提交后再 abort。"""

    committed = False

    def __await__(self):
        return self
        yield  # pragma: no cover - 使 __await__ 成为 generator（永不触达）

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        self.committed = exc_info[0] is None
        return False

    def start_transaction(self):
        return self  # async CM：事务体


class _StandaloneSession(_OkSession):
    """standalone 形态：开启事务即被 mongod 拒绝。"""

    def start_transaction(self):
        raise RuntimeError(
            "Transaction numbers are only allowed on a replica set member or mongos"
        )


class _FakeClient:
    def __init__(self, session_cls):
        self._session_cls = session_cls

    def start_session(self):
        return self._session_cls()


class _FakeDatabase:
    def __init__(self, session_cls, *, set_name="rs0"):
        self.client = _FakeClient(session_cls)
        self._set_name = set_name
        self.collections: dict[str, _FakeCollection] = {}

    def get_collection(self, name):
        return self.collections.setdefault(name, _FakeCollection())

    async def command(self, name):  # noqa: ARG002
        if name == "hello":
            return {"setName": self._set_name} if self._set_name else {}
        return {}


@pytest.fixture
def _patch_db(monkeypatch):
    """替换 get_database，按用例注入不同形态的假库。"""

    def _install(db: _FakeDatabase):
        import app.db.mongodb as mongodb_mod

        monkeypatch.setattr(mongodb_mod, "get_database", lambda: db)

    return _install


@pytest.fixture(autouse=True)
def _reset_status():
    """每个用例重置进程级状态，避免用例间泄漏。"""
    rt._status = None
    yield
    rt._status = None


async def test_probe_ok_on_replica_set(_patch_db):
    db = _FakeDatabase(_OkSession)
    # 预置其他进程的探测文档：本次探测的清理不得波及（#75 并发清理语义）
    other = db.get_collection(rt._PROBE_COLLECTIONS[0])
    await other.insert_one({"probe_id": "probe-other", "ts": 0})

    _patch_db(db)
    ok, error = await rt.probe_transaction_capability()
    assert ok is True
    assert error is None
    # 提交语义：本次探测文档与他人的都按精确清理处理——本次的已删，
    # 他人的保留
    assert {d["probe_id"] for d in other.docs} == {"probe-other"}


async def test_probe_cleanup_failure_does_not_flip_result(_patch_db):
    """清理失败只告警，不覆盖事务能力结论（#75 修复要求 5）。"""
    db = _FakeDatabase(_OkSession)
    _patch_db(db)
    db.get_collection(rt._PROBE_COLLECTIONS[0]).delete_errors = True

    ok, error = await rt.probe_transaction_capability()
    assert ok is True
    assert error is None


async def test_probe_fails_on_standalone(_patch_db):
    _patch_db(_FakeDatabase(_StandaloneSession))
    ok, error = await rt.probe_transaction_capability()
    assert ok is False
    assert "replica set" in error


async def test_check_fail_closed_when_durable_required(_patch_db, monkeypatch):
    """durable=true 且探测失败 → 拒绝启动（生产/开发一致）。"""
    from app.core.config import settings

    monkeypatch.setattr(settings, "EXECUTION_DURABLE", True)
    _patch_db(_FakeDatabase(_StandaloneSession))

    with pytest.raises(RuntimeError, match="multi-document transactions"):
        await rt.check_execution_runtime()


async def test_check_explicit_non_durable_allows_startup(_patch_db, monkeypatch):
    """durable=false → 不 raise；健康状态明示 non-durable。"""
    from app.core.config import settings

    monkeypatch.setattr(settings, "EXECUTION_DURABLE", False)
    _patch_db(_FakeDatabase(_StandaloneSession, set_name=None))

    status = await rt.check_execution_runtime()
    assert status.durable is False
    assert status.transactions_ok is False

    health = rt.as_health_dict()
    assert health["execution_durable"] is False
    assert health["execution_transactions_ok"] is False
    assert health["execution_mongo_backend"] == "standalone"


async def test_check_ok_reports_replica_set(_patch_db, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "EXECUTION_DURABLE", True)
    _patch_db(_FakeDatabase(_OkSession))

    status = await rt.check_execution_runtime()
    assert status.durable is True
    assert status.transactions_ok is True
    assert status.backend_type == "replica_set"

    health = rt.as_health_dict()
    assert health["execution_durable"] is True
    assert health["execution_error"] is None


def test_health_before_init_reports_unknown():
    health = rt.as_health_dict()
    assert health["execution_transactions_ok"] is None
    assert health["execution_error"] == "not initialized"
