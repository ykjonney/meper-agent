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

    # 先决检查（E6 follow-up P1-4）：Task 已终态/等待 → 直接收敛 Execution，
    # **不再进 engine**。场景：上一次运行已把 Task 写成 completed 但 Worker
    # 在 _finish 前崩溃 → takeover 重入本 runner——若照常 run_and_persist，
    # completed Task 无 checkpoint 时会从头重放已提交的节点副作用。
    from app.services.task_service import TaskService

    pre_task = await TaskService.get_task(task_id)
    pre_status = (pre_task or {}).get("status", "")
    if pre_status in _TASK_TO_EXECUTION or pre_status == "waiting_human":
        logger.info(
            "workflow_runner_precheck_converge",
            execution_id=execution_id, task_id=task_id, task_status=pre_status,
        )
        await _converge_from_task_status(
            repo, execution_id, lease, task_status=pre_status, result_keys=[]
        )
        return

    async with lease_heartbeat(
        lm, execution_id, lease.owner, lease.fencing_token
    ):
        with execution_identity_scope(identity):
            result = await WorkflowEngine().run_and_persist(task_id)

    await _converge_from_task_status(
        repo, execution_id, lease,
        task_status=(await TaskService.get_task(task_id) or {}).get("status", ""),
        result_keys=sorted(result or {}),
    )


async def _converge_from_task_status(
    repo: ExecutionRepository,
    execution_id: str,
    lease: Any,
    *,
    task_status: str,
    result_keys: list[str],
) -> None:
    """按 Task 状态收敛 Execution（先决检查与执行后共用）。"""
    execution_status = _TASK_TO_EXECUTION.get(task_status)
    if execution_status is None and task_status == "waiting_human":
        # 暂停等待输入（E6 follow-up P1-3）：非终态——不写 completed_at、
        # dispatch 置 pending（可被扫描重新派发）、释放 lease（无运行体）。
        # 恢复闭环：输入提交方调 resume_waiting_execution（CAS → queued），
        # 崩溃窗口由 RecoverySupervisor 扫描兜底（见 recovery.py）。
        await _finish(
            repo, execution_id, lease, status="waiting_input",
            event_type="execution.waiting_input",
            payload={"task_status": task_status, "result_keys": result_keys},
            release=True,
            waiting=True,
        )
        return
    if execution_status is None:
        # 未知/中间态（engine 异常返回空等）——不猜终态，留 lease 自然过期
        # 由 supervisor 接管裁决（与 runner 异常语义一致）。
        logger.warning(
            "workflow_runner_unmapped_task_status",
            execution_id=execution_id, task_status=task_status,
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
    waiting: bool = False,
) -> None:
    """fenced 终态/暂停写入：状态 + 事件 (+ 释放 lease)。

    ``waiting=True``（P1-3）：暂停等待输入——**不写 completed_at**、
    ``dispatch`` 置 pending（可重新派发），而非 done。
    """
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
        if waiting:
            await txn.update_execution(
                {
                    "$set": {
                        "status": status,
                        "dispatch.state": "pending",
                        "dispatch.next_dispatch_at": None,
                    }
                }
            )
        else:
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


async def record_input_intent(
    repo: ExecutionRepository, execution_id: str, task_id: str,
    variable_patch: dict[str, Any],
) -> None:
    """input-intent 先行记录（E6 r4 P1，write-ahead）。

    人工输入提交顺序固化为：**intent → 变量持久化 → marker → resume CAS**。
    intent 携带最终变量 patch，使 Supervisor 能在"变量已写/未写"任何崩溃
    点安全补偿：intent 存在 + Task 已离开 waiting_human + marker 缺失 →
    重放 patch（单文档原子 $set，幂等）→ 补 marker → 收敛 queued。
    无 intent + 无 marker = 提交流程未开始，继续等待，不误恢复。
    """
    from app.models.base import utc_now

    await repo._executions().update_one(  # noqa: SLF001 - 同包协作层
        {"_id": execution_id},
        {"$set": {
            "input_intent": {
                "task_id": task_id,
                "variable_patch": variable_patch,
                "recorded_at": utc_now(),
            },
        }},
    )


async def mark_input_committed(repo: ExecutionRepository, execution_id: str) -> bool:
    """input-committed marker 的**独立幂等**持久化（E6 r3 P1-2）。

    语义：人工输入/审批变量已持久化。一致性边界：调用方必须在
    ``update_variables`` 成功**之后立即**调用（同为 update_variables 后
    恢复链路的第一步）——崩溃窗口缩至"变量已落库 → marker 未落库"，
    该窗口内 marker 缺失 = 视为输入未提交（保守正确：supervisor 跳过，
    等待重试审批操作，不会错误恢复）。marker 落库后任何后续崩溃由
    RecoverySupervisor 扫描类 4 兜底恢复。
    """
    from app.models.base import utc_now

    result = await repo._executions().update_one(  # noqa: SLF001 - 同包协作层
        {"_id": execution_id, "input_committed_at": None},
        {"$set": {"input_committed_at": utc_now()}},
    )
    return result.matched_count == 1


async def compensate_pending_input(repo: ExecutionRepository, execution_id: str) -> bool:
    """Supervisor 补偿（E6 r4 P1）：intent 已记、marker 未落 → 补齐收敛。

    幂等：重放 patch 到 Task.variables（单文档原子 $set）→ 补 marker。
    任何崩溃点（变量前/后、marker 前/后）重入本函数都收敛到同一终态。
    """
    doc = await repo.get_execution(execution_id)
    if doc is None:
        return False
    if doc.get("input_committed_at") is not None:
        return True  # 已提交——无需补偿
    intent = doc.get("input_intent")
    if not intent:
        return False  # 提交流程未开始

    patch = intent.get("variable_patch") or {}
    set_ops = {f"variables.{k}": v for k, v in patch.items()}
    if set_ops:
        await repo._database()["tasks"].update_one(  # noqa: SLF001
            {"_id": intent.get("task_id")}, {"$set": set_ops}
        )
    await mark_input_committed(repo, execution_id)
    return True


async def resume_waiting_execution(repo: ExecutionRepository, execution_id: str) -> bool:
    """输入提交后的恢复入口：CAS waiting_input → queued + pending。

    幂等：仅 waiting_input 状态匹配（重复提交天然去重）；成功后由派发方
    立即 dispatch 或 RecoverySupervisor 扫描类 1 兜底。marker 已由
    ``mark_input_committed`` 独立落库（调用顺序：mark → resume）。
    """
    from app.models.base import utc_now

    result = await repo._executions().update_one(  # noqa: SLF001 - 同包协作层
        {"_id": execution_id, "status": "waiting_input"},
        {
            "$set": {
                "status": "queued",
                "dispatch.state": "pending",
                "dispatch.attempts": 0,
                "dispatch.next_dispatch_at": None,
                "updated_at": utc_now(),
            }
        },
    )
    return result.matched_count == 1


def register_workflow_runner() -> None:
    """注册入口（worker bootstrap / lifespan 调用；幂等）。"""
    from app.workers.tasks.execution_run import register_runner

    register_runner("workflow", run_workflow_execution)
