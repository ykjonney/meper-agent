"""worker 进程装配账本的 bootstrap 测试（E5 follow-up P1-1）。

不装配则 harness 账本保持 NoLedger（claim 恒 True）= worker 执行副作用
工具时无 durable 保护。验证：
- `_init_worker` 调用 `configure_tool_ledger`（在 MCP 注入之前）；
- durable 模式下索引创建失败 → worker 启动失败（fail-closed，不静默旁路）。
"""
from __future__ import annotations

import asyncio

import pytest


def _run_init_worker(monkeypatch) -> tuple[list[str], list[asyncio.AbstractEventLoop]]:
    """绕过 license/checkpointer 等真实副作用，只观察装配顺序。"""
    calls: list[str] = []
    loops: list[asyncio.AbstractEventLoop] = []

    async def _fake_check():
        loops.append(asyncio.get_running_loop())
        calls.append("check_execution_runtime")

    async def _fake_configure():
        loops.append(asyncio.get_running_loop())
        calls.append("configure_tool_ledger")

    from app.core import license as lic

    class _NotEnforced:
        enforced = False
        ok = True
        code = ""

    monkeypatch.setattr(lic, "evaluate_license", lambda force=False: _NotEnforced())
    monkeypatch.setattr(
        "app.core.execution_runtime.check_execution_runtime", _fake_check
    )
    monkeypatch.setattr(
        "app.engine.execution.tool_ledger.configure_tool_ledger", _fake_configure
    )
    import app.workers.celery_app as celery_mod

    celery_mod._init_worker()
    return calls, loops


def test_init_worker_installs_tool_ledger(monkeypatch):
    calls, loops = _run_init_worker(monkeypatch)
    assert "configure_tool_ledger" in calls
    # 顺序：前提检查 → 账本（账本不得晚于任务可执行点）
    assert calls.index("configure_tool_ledger") > calls.index(
        "check_execution_runtime"
    )
    # Mongo client and ledger bootstrap must share the persistent worker loop;
    # separate asyncio.run() calls would create and close different loops.
    assert len(loops) == 2
    assert loops[0] is loops[1]
    from app.workers.loop import get_worker_loop

    assert get_worker_loop() is loops[0]
    assert not loops[0].is_closed()


async def test_configure_tool_ledger_fails_closed_on_index_error(monkeypatch):
    """durable 模式索引创建失败 → 异常上抛（worker 启动失败），不旁路。"""
    import app.engine.execution.tool_ledger as ledger_mod
    from app.core.config import settings

    monkeypatch.setattr(settings, "EXECUTION_DURABLE", True)

    class _BrokenColl:
        async def create_index(self, *a, **k):  # noqa: ARG002
            raise ConnectionError("mongo unreachable")

    class _BrokenDB:
        def __getitem__(self, name):  # noqa: ARG002
            return _BrokenColl()

    monkeypatch.setattr(ledger_mod, "get_database", lambda: _BrokenDB())

    from agent_flow_harness.ledger import NoLedger, get_ledger, set_ledger

    set_ledger(NoLedger())  # 确保未装配状态
    with pytest.raises(ConnectionError):
        await ledger_mod.configure_tool_ledger()
    # 未装配（保持 NoLedger——但启动路径已因异常退出，此断言防半装配）
    assert isinstance(get_ledger(), NoLedger)
