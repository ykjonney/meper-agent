"""WorkflowRuntimeAdapter —— workflow 的 Durable Runner（E6，#64/PR #73）。

把真实 Step Identity 与 Execution Fencing 接入 workflow 执行：

- **identity + token**：runner 全程绑定 ``ExecutionIdentity``（含 lease
  token）——副作用账本（E5）经 ``MongoToolLedger`` 的 fenced 路径写账本，
  被接管的旧 Worker 账本写入被拒；
- **心跳**：``lease_heartbeat`` 包裹执行体（TTL 内续约；心跳丢失即取消
  Runner 并传播 LeaseLostError——执行让位给接管者，不双跑）；
- **节点级 step**：node_executor 在 agent 执行处 ``step_scope(node_id)``
  细化幂等键（{execution}:{node}:{call}，不再落 root）；
- **终态映射**：engine 返回后按 Task 终态映射 Execution 状态并写事件；
  waiting_human → waiting_input（释放 lease，恢复走重新派发）。

现有 Celery 旧路径（run_workflow_task）仍是生产主入口——本 Adapter 注册
给 execution 域派发的执行（E3 的 run_execution → runner）；权威翻转
（恢复读 Manifest）在后续评审 gates 后进行。
"""
from __future__ import annotations

from typing import Any

from loguru import logger

from app.engine.execution.repository import ExecutionRepository, LeaseLostError

# Task 终态 → Execution 终态映射（waiting_human 特殊：等待输入非终态）
_TASK_TO_EXECUTION = {
    "completed": "succeeded",
    "failed": "failed",
    "cancelled": "cancelled",
}


async def run_workflow_execution(doc: dict[str, Any], lease: Any) -> None:
    """Durable workflow runner（register_runner("workflow", ...) 注册）。"""
    from agent_flow_harness.execution_context import (
        ExecutionIdentity,
        execution_identity_scope,
    )

    from app.engine.execution.lease import LeaseManager, lease_heartbeat
    from app.engine.workflow.engine import WorkflowEngine

    execution_id = doc["_id"]
    task_id = doc.get("task_id")
    if not task_id:
        raise ValueError(f"workflow execution {execution_id} has no task_id")

    identity = ExecutionIdentity(
        execution_id=execution_id,
        step_id=None,  # root；节点级由 node_executor 的 step_scope 细化
        fencing_token=lease.fencing_token,
    )
    lm = LeaseManager()
    repo = ExecutionRepository()

    async with lease_heartbeat(
        lm, execution_id, lease.owner, lease.fencing_token
    ):
        with execution_identity_scope(identity):
            result = await WorkflowEngine().run_and_persist(task_id)

    # 终态映射（engine 内部消化业务失败，不 raise）
    from app.services.task_service import TaskService

    task = await TaskService.get_task(task_id)
    task_status = (task or {}).get("status", "")
    execution_status = _TASK_TO_EXECUTION.get(task_status)
    if execution_status is None and task_status == "waiting_human":
        await _finish(
            repo, execution_id, lease, status="waiting_input",
            event_type="execution.waiting_input",
            payload={"task_status": task_status, "result_keys": sorted(result or {})},
            release=True,  # 暂停无运行体：释放 lease，恢复走重新派发
        )
        return
    if execution_status is None:
        # 未知/中间态（engine 异常返回空等）——不猜终态，留 lease 自然过期
        # 由 supervisor 接管裁决（与 runner 异常语义一致）。
        logger.warning(
            "workflow_runner_unmapped_task_status",
            execution_id=execution_id, task_id=task_id, task_status=task_status,
        )
        return
    await _finish(
        repo, execution_id, lease, status=execution_status,
        event_type=f"execution.{execution_status}",
        payload={"task_status": task_status},
        release=True,
    )


async def _finish(
    repo: ExecutionRepository,
    execution_id: str,
    lease: Any,
    *,
    status: str,
    event_type: str,
    payload: dict[str, Any],
    release: bool,
) -> None:
    """fenced 终态写入：状态 + 事件 (+ 释放 lease)。"""
    from agent_flow_harness.ledger import LedgerStatus  # noqa: F401 - 语义引用

    from app.engine.execution.models import ExecutionEvent
    from app.models.base import utc_now

    async with repo.transaction(execution_id, expected_token=lease.fencing_token) as txn:
        await txn.append_event(
            ExecutionEvent(
                execution_id=execution_id,
                seq=0,
                type=event_type,
                producer="workflow-runtime",
                payload=payload,
            )
        )
        await txn.update_execution(
            {
                "$set": {
                    "status": status,
                    "completed_at": utc_now(),
                    "dispatch.state": "done",
                }
            }
        )
    if release:
        try:
            from app.engine.execution.lease import LeaseManager

            await LeaseManager(repo).release(execution_id, lease.fencing_token)
        except LeaseLostError:
            logger.info(
                "workflow_runner_release_lost execution={}", execution_id
            )


def register_workflow_runner() -> None:
    """注册入口（worker bootstrap / lifespan 调用；幂等）。"""
    from app.workers.tasks.execution_run import register_runner

    register_runner("workflow", run_workflow_execution)
