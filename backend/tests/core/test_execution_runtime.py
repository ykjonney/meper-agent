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
    async def insert_one(self, doc, session=None):  # noqa: ARG002
        return None

    async def drop(self):
        return None


class _OkSession:
    """支持事务的会话（replica set 形态）。motor 的 start_session 返回
    既可 await 又可 async-with 的对象，fake 需同时实现两种协议。"""

    def __await__(self):
        return self
        yield  # pragma: no cover - 使 __await__ 成为 generator（永不触达）

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    def start_transaction(self):
        return self  # async CM：事务体

    async def abort_transaction(self):
        return None


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

    def get_collection(self, name):  # noqa: ARG002
        return _FakeCollection()

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
    _patch_db(_FakeDatabase(_OkSession))
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
