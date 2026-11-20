"""执行域集合定义与索引（#64 提案 §6.4 + 架构 v2 §3.3 修正）。

索引要点：
- ``execution_events(event_id 唯一)``：seq 唯一兜底并发缺陷；
- ``event_key`` 去重用 **partial unique index**（compound sparse 不适用——
  ``execution_id`` 恒存在，sparse 判定失效；这是审查修正项）；
- 扫描索引对齐 RecoverySupervisor 三类查询（v2 §3.6）。

具体索引按实际查询模式压测后调整（提案 §6.4 原话）。
"""
from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

EXECUTIONS = "executions"
STEPS = "execution_steps"
CHECKPOINT_MANIFESTS = "execution_checkpoints"
EXECUTION_EVENTS = "execution_events"
TOOL_INVOCATIONS = "tool_invocations"
RESOURCE_BINDINGS = "resource_bindings"


async def ensure_execution_indexes(db: AsyncIOMotorDatabase) -> None:
    """创建执行域全部索引（幂等；bootstrap ensure_all_indexes 调用）。"""
    await db[EXECUTIONS].create_index([("task_id", 1), ("created_at", -1)])
    await db[EXECUTIONS].create_index([("session_id", 1), ("created_at", -1)])
    await db[EXECUTIONS].create_index([("parent_execution_id", 1), ("created_at", -1)])
    # 扫描 1：queued + 待派发/重试（RecoverySupervisor）
    await db[EXECUTIONS].create_index(
        [("status", 1), ("dispatch.state", 1), ("dispatch.next_dispatch_at", 1)]
    )
    # 扫描 2：running + lease 过期接管
    await db[EXECUTIONS].create_index([("status", 1), ("lease.expires_at", 1)])

    await db[STEPS].create_index(
        [("execution_id", 1), ("step_seq", 1)], unique=True
    )
    await db[STEPS].create_index([("execution_id", 1), ("status", 1)])

    await db[CHECKPOINT_MANIFESTS].create_index(
        [("execution_id", 1), ("checkpoint_seq", -1)], unique=True
    )

    await db[EXECUTION_EVENTS].create_index(
        [("execution_id", 1), ("seq", 1)], unique=True
    )
    # event_key 去重：partial（仅存在时参与唯一约束）——审查修正项
    await db[EXECUTION_EVENTS].create_index(
        [("execution_id", 1), ("event_key", 1)],
        unique=True,
        partialFilterExpression={"event_key": {"$type": "string"}},
    )

    await db[TOOL_INVOCATIONS].create_index(
        [("execution_id", 1), ("idempotency_key", 1)], unique=True
    )
    await db[TOOL_INVOCATIONS].create_index([("execution_id", 1), ("status", 1)])

    await db[RESOURCE_BINDINGS].create_index(
        [("execution_id", 1), ("lifecycle_state", 1)]
    )
    await db[RESOURCE_BINDINGS].create_index(
        [("resource_type", 1), ("resource_id", 1), ("lease_expires_at", 1)]
    )
