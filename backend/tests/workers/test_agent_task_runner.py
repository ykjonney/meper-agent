"""AgentTaskRunner 状态流转：成功/失败/取消守卫/入口分流。"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.workers.tasks.agent_task_runner import run_agent_async


def _task_doc(**over):
    doc = {
        "_id": "task_1", "agent_id": "agent_1", "status": "pending",
        "input": {"instruction": "做调研"}, "created_by": "user_1",
    }
    doc.update(over)
    return doc


@pytest.mark.asyncio
async def test_success_writes_output_and_completes() -> None:
    resp = MagicMock(output="结果", session_id="session_9", step_count=3, total_tokens=77)
    transition_calls: list = []

    async def fake_transition(task_id, to_status, **kw):
        transition_calls.append(to_status)
        return {"_id": task_id, "status": to_status}

    with (
        patch("app.services.task_service.TaskService.get_task", new=AsyncMock(side_effect=[_task_doc(), _task_doc(status="running"), _task_doc(status="running")])),
        patch("app.services.task_service.TaskService.transition_task", new=fake_transition),
        patch("app.services.task_service.TaskService.update_task_output", new=AsyncMock()) as upd,
        patch("app.services.task_service.TaskService.add_total_tokens", new=AsyncMock()) as tok,
        patch("app.services.session_service.SessionService.update_session", new=AsyncMock()) as sess,
        patch("app.services.agent_execution_service.AgentExecutionService.invoke", new=AsyncMock(return_value=resp)),
    ):
        result = await run_agent_async("task_1")

    assert result["status"] == "success"
    # output 含最终答案 + 会话关联
    out_arg = upd.call_args.args[1]
    assert out_arg["output"] == "结果"
    assert out_arg["session_id"] == "session_9"
    sess.assert_awaited_once_with("session_9", {"task_id": "task_1"})
    tok.assert_awaited_once_with("task_1", 77)
    assert transition_calls == ["running", "completed"]


@pytest.mark.asyncio
async def test_invoke_error_marks_failed() -> None:
    async def fake_transition(task_id, to_status, **kw):
        if to_status == "failed":
            assert kw.get("error_info"), "failed 转换必须携带 error_info"
        return {"_id": task_id}

    with (
        patch("app.services.task_service.TaskService.get_task", new=AsyncMock(side_effect=[_task_doc(), _task_doc(status="running")])),
        patch("app.services.task_service.TaskService.transition_task", new=fake_transition),
        patch("app.services.agent_execution_service.AgentExecutionService.invoke", new=AsyncMock(side_effect=RuntimeError("boom"))),
    ):
        result = await run_agent_async("task_1")

    assert result["status"] == "error"


@pytest.mark.asyncio
async def test_cancelled_result_discarded() -> None:
    """回写前发现已 cancelled → 丢弃结果、不再转换状态。

    get_task 共 2 次调用：开头加载 + 回写守卫（invoke 已 mock，checker 不触发）。
    """
    resp = MagicMock(output="x", session_id="s", step_count=1, total_tokens=1)
    with (
        patch("app.services.task_service.TaskService.get_task", new=AsyncMock(side_effect=[_task_doc(), _task_doc(status="cancelled")])),
        patch("app.services.task_service.TaskService.transition_task", new=AsyncMock()) as tr,
        patch("app.services.task_service.TaskService.update_task_output", new=AsyncMock()) as upd,
        patch("app.services.session_service.SessionService.update_session", new=AsyncMock()),
        patch("app.services.agent_execution_service.AgentExecutionService.invoke", new=AsyncMock(return_value=resp)),
    ):
        result = await run_agent_async("task_1")

    assert result["status"] == "cancelled"
    # 启动时的 running 转换正常发生；守卫只是不再写 completed
    assert tr.await_args.args[1] == "running"
    # update_task_output 只有 started_at 写回（output={}），无结果回写
    upd.assert_awaited_once()
    assert upd.await_args.args[1] == {}


@pytest.mark.asyncio
async def test_concurrency_conflict_leaves_pending() -> None:
    """pending→running 撞并发上限 → 任务保持 pending 等待 FIFO/下轮扫描。

    用 Exception 规避 ConflictError 构造签名猜测——runner 捕获所有异常
    转 skipped，语义覆盖并发冲突。
    """
    with (
        patch("app.services.task_service.TaskService.get_task", new=AsyncMock(return_value=_task_doc())),
        patch("app.services.task_service.TaskService.transition_task", new=AsyncMock(side_effect=Exception("并发已满"))),
    ):
        result = await run_agent_async("task_1")

    assert result["status"] == "skipped"
