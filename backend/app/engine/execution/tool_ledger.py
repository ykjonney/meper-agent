"""MongoToolLedger —— SideEffectLedger 的 Mongo 实现（E5，app 侧）。

写入 ``tool_invocations`` 集合（唯一索引 (execution_id, idempotency_key)）。
prepare 用 upsert 持久化**原始调用意图**（提案 §3.8：恢复裁决以持久化
意图为准，不假设重生成 tool_call_id 稳定）。

E5 影子期说明：账本写入发生在图执行内部，尚无 lease token（E6/E7 的
Adapter 才绑定 token）——本阶段写入为无 fencing 影子记录，幂等键唯一
索引兜底并发。E6/E7 接入后改走 repo.transaction 带 token 写入。
"""
from __future__ import annotations

from typing import Any

from agent_flow_harness.ledger import (
    LedgerRecord,
    LedgerStatus,
    SideEffectLedger,
    ToolInvocationDraft,
)
from loguru import logger

from app.db.mongodb import get_database
from app.engine.execution.collections import TOOL_INVOCATIONS
from app.models.base import generate_id, utc_now


def _idempotency_scope(idempotency_key: str) -> tuple[str, str]:
    """幂等键约定 {execution_id}:{step}:{tool_call_id} → (execution, key)。

    lookup/mark 按 (execution_id, idempotency_key) 双条件与唯一索引对齐
    （不同 Execution 可复用相同键尾——第三轮审查 §6 的隔离语义）。
    """
    execution_id = idempotency_key.split(":", 1)[0]
    return execution_id, idempotency_key


def _fencing_token() -> int | None:
    """当前 identity 携带的 lease token（E6 起 Adapter 绑定；无则影子期）。"""
    from agent_flow_harness.execution_context import get_execution_identity

    identity = get_execution_identity()
    return identity.fencing_token if identity else None


class MongoToolLedger(SideEffectLedger):
    """生产实现。准备/认领失败必须向上抛出，避免无账本保护地执行副作用。

    E6 起：identity 携带 fencing_token 时，prepare/claim/mark 走
    ``ExecutionRepository.transaction``（fenced：touch 主记录 + 账本写同
    事务）——被接管的旧 Worker 的账本写入被拒绝（LeaseLostError 上抛，
    由 ledger_protected_call 归入 UNKNOWN 路径后向调用方传播）。无 token
    （legacy/影子）保持直接写，边界与 E5 声明一致。
    """

    async def prepare(self, draft: ToolInvocationDraft) -> None:
        execution_id, key = _idempotency_scope(draft.idempotency_key)
        doc = {
            "_id": generate_id("tinv"),
            "execution_id": execution_id,
            "step_id": draft.step_id,
            "tool_call_id": draft.tool_call_id,
            "tool_name": draft.tool_name,
            "tool_version": draft.tool_version,
            "idempotency_key": key,
            "request_digest": draft.request_digest,
            "request_intent": {"args": draft.args},  # 原始调用意图
            "status": LedgerStatus.PREPARED.value,
            "retry_count": 0,
            "started_at": utc_now(),
        }
        coll = get_database()[TOOL_INVOCATIONS]
        token = _fencing_token()
        if token is not None:
            from app.engine.execution.repository import ExecutionRepository

            async with ExecutionRepository().transaction(
                execution_id, expected_token=token
            ) as txn:
                await coll.update_one(
                    {"execution_id": execution_id, "idempotency_key": key},
                    {"$setOnInsert": doc},
                    upsert=True,
                    session=txn.session,
                )
            return
        await coll.update_one(
            {"execution_id": execution_id, "idempotency_key": key},
            {"$setOnInsert": doc},
            upsert=True,
        )

    async def claim(self, idempotency_key: str, expected_digest: str) -> bool:
        """CAS claim: only PREPARED *with matching digest* → IN_PROGRESS.

        digest 是原子谓词的一部分（follow-up P1-3）：lookup 瞬态失败时，
        旧 PREPARED + 不同 digest 的记录不能被认领后以旧身份执行新参数。
        UNKNOWN/IN_PROGRESS/终态记录不被普通恢复路径重执行（需专门裁决）。
        """
        execution_id, key = _idempotency_scope(idempotency_key)
        flt = {
            "execution_id": execution_id,
            "idempotency_key": key,
            "status": LedgerStatus.PREPARED.value,
            "request_digest": expected_digest,
        }
        update = {"$set": {"status": LedgerStatus.IN_PROGRESS.value,
                           "started_at": utc_now()}}
        coll = get_database()[TOOL_INVOCATIONS]
        token = _fencing_token()
        if token is not None:
            from app.engine.execution.repository import ExecutionRepository

            async with ExecutionRepository().transaction(
                execution_id, expected_token=token
            ) as txn:
                result = await coll.update_one(flt, update, session=txn.session)
            return result.matched_count == 1
        result = await coll.update_one(flt, update)
        return result.matched_count == 1

    async def mark(
        self,
        idempotency_key: str,
        status: LedgerStatus,
        *,
        result_summary: str | None = None,
        error: str | None = None,
    ) -> None:
        execution_id, key = _idempotency_scope(idempotency_key)
        # State changes are fenced by the current state. An old worker cannot
        # overwrite a terminal result after a newer recovery decision.
        flt = {"execution_id": execution_id, "idempotency_key": key,
               "status": LedgerStatus.IN_PROGRESS.value}
        update = {"$set": {
            "status": status.value,
            "result_ref": result_summary,
            "error": error,
            "completed_at": utc_now(),
        }}
        coll = get_database()[TOOL_INVOCATIONS]
        token = _fencing_token()
        if token is not None:
            from app.engine.execution.repository import ExecutionRepository

            async with ExecutionRepository().transaction(
                execution_id, expected_token=token
            ) as txn:
                await coll.update_one(flt, update, session=txn.session)
            return
        await coll.update_one(flt, update)

    async def lookup(self, idempotency_key: str) -> LedgerRecord | None:
        execution_id, key = _idempotency_scope(idempotency_key)
        doc: dict[str, Any] | None = await get_database()[
            TOOL_INVOCATIONS
        ].find_one({"execution_id": execution_id, "idempotency_key": key})
        if doc is None:
            return None
        return LedgerRecord(
            idempotency_key=doc["idempotency_key"],
            status=LedgerStatus(doc.get("status", LedgerStatus.UNKNOWN.value)),
            tool_call_id=doc.get("tool_call_id", ""),
            tool_name=doc.get("tool_name", ""),
            request_digest=doc.get("request_digest", ""),
            result_summary=doc.get("result_ref"),
            error=doc.get("error"),
            raw=doc,
        )


class CollectingLedger(SideEffectLedger):
    """测试实现：内存记录状态迁移序列（harness/backend 测试共用）。"""

    def __init__(self) -> None:
        self.records: dict[str, LedgerRecord] = {}
        self.calls: list[tuple[str, str]] = []  # (key, 转移)

    async def prepare(self, draft: ToolInvocationDraft) -> None:
        self.calls.append((draft.idempotency_key, "prepared"))
        self.records[draft.idempotency_key] = LedgerRecord(
            idempotency_key=draft.idempotency_key,
            status=LedgerStatus.PREPARED,
            tool_call_id=draft.tool_call_id,
            tool_name=draft.tool_name,
            request_digest=draft.request_digest,
        )

    async def claim(self, idempotency_key: str, expected_digest: str) -> bool:
        rec = self.records.get(idempotency_key)
        if rec is None or rec.status != LedgerStatus.PREPARED:
            return False
        if rec.request_digest != expected_digest:
            return False  # invocation identity conflict（P1-3 同语义）
        self.calls.append((idempotency_key, "in_progress"))
        rec.status = LedgerStatus.IN_PROGRESS
        return True

    async def mark(
        self,
        idempotency_key: str,
        status: LedgerStatus,
        *,
        result_summary: str | None = None,
        error: str | None = None,
    ) -> None:
        rec = self.records.get(idempotency_key)
        if rec is None or rec.status != LedgerStatus.IN_PROGRESS:
            return
        self.calls.append((idempotency_key, status.value))
        rec.status = status
        rec.result_summary = result_summary
        rec.error = error

    async def lookup(self, idempotency_key: str) -> LedgerRecord | None:
        return self.records.get(idempotency_key)


async def configure_tool_ledger() -> None:
    """装配入口（bootstrap 调用）：durable 模式注入 Mongo 实现。"""
    from agent_flow_harness.ledger import set_ledger

    from app.core.config import settings

    if not settings.EXECUTION_DURABLE:
        logger.info("tool_ledger_disabled reason=non-durable mode")
        return
    await get_database()[TOOL_INVOCATIONS].create_index([("execution_id", 1), ("idempotency_key", 1)], unique=True)
    await get_database()[TOOL_INVOCATIONS].create_index([("execution_id", 1), ("status", 1)])
    set_ledger(MongoToolLedger())
    logger.info("tool_ledger_ready implementation=mongo")
