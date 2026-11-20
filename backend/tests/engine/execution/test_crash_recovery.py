"""E6 复审 P2：Task completed / Execution 未收敛的崩溃恢复故障注入。

时序：Task 已 completed、Execution 仍 running 且 lease 过期（Worker 在
_finish 前崩溃）→ takeover → 重入 runner → 先决检查直接收敛 Execution，
**engine 不被调用**（不重放已完成副作用、不伪造 Manifest/成功事件以外的
执行事实——收敛只写终态映射事件）。
"""
from __future__ import annotations

from datetime import timedelta

import app.engine.execution.workflow_adapter as adapter_mod
import pytest
import tests.engine.execution.test_repository_lease as _base
from app.models.base import utc_now


@pytest.fixture
def fake_db(monkeypatch):
    db = _base.FakeDB()
    import app.db.mongodb as app_db_mod
    import app.engine.execution.repository as repo_mod

    monkeypatch.setattr(app_db_mod, "get_database", lambda: db)
    monkeypatch.setattr(repo_mod, "get_database", lambda: db)
    return db


async def test_completed_task_crash_recovery_does_not_replay(fake_db, monkeypatch):
    from app.engine.execution.lease import LeaseManager
    from app.engine.execution.models import ExecutionStatus
    from app.engine.execution.repository import ExecutionRepository

    db = fake_db
    exe = _base._seed_execution(db, token=11)  # running + 有效 lease
    db.collections["executions"][exe.id]["task_id"] = "task_crash_1"
    # Worker 已把 Task 写成 completed，随后在 _finish 前崩溃：
    # lease 过期 → supervisor takeover → 重入 runner
    db.collections["executions"][exe.id]["lease"]["expires_at"] = (
        utc_now() - timedelta(seconds=1)
    )
    db.collections.setdefault("tasks", {})[exe.id] = {}  # 占位，下方 patch 返回

    # engine 绝不能被调用（调用即重放副作用）
    async def _engine_must_not_run(task_id):
        raise AssertionError(f"engine must not re-run completed task: {task_id}")

    class _FakeTaskDoc(dict):
        pass

    task_doc = _FakeTaskDoc(status="completed")

    class _FakeTaskService:
        @staticmethod
        async def get_task(task_id):
            return {"_id": task_id, "status": "completed"}

    import app.services.task_service as ts_mod

    monkeypatch.setattr(adapter_mod, "WorkflowEngine", None, raising=False)
    monkeypatch.setattr(
        "app.engine.workflow.engine.WorkflowEngine", _engine_must_not_run
    )
    monkeypatch.setattr(ts_mod, "TaskService", _FakeTaskService)
    # adapter 内部 from app.services.task_service import TaskService 是
    # 函数内 import → 绑定模块属性，patch ts_mod.TaskService 生效。

    repo = ExecutionRepository()
    lease_b = await LeaseManager(repo).takeover(exe.id, "supervisor")
    assert lease_b is not None and lease_b.fencing_token == 12

    # 重入 runner（takeover 后的派发目标）
    doc = db.collections["executions"][exe.id]
    await adapter_mod.run_workflow_execution(doc, lease_b)

    # 收敛结果：Execution succeeded、事件只有收敛事件、无 engine 副作用
    final = db.collections["executions"][exe.id]
    assert final["status"] == ExecutionStatus.SUCCEEDED.value
    assert final["completed_at"] is not None
    assert final["lease"] is None  # 释放
    events = [e for e in db.collections.get("execution_events", {}).values()
              if e["execution_id"] == exe.id]
    assert [e["type"] for e in events] == ["execution.succeeded"]
    # started 事件也不会有（engine 未跑）——这正是"不伪造执行"的证明
    del task_doc
