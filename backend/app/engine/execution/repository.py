"""ExecutionRepository —— 执行事实写入的唯一受控通道（架构 v2 铁律 1/2/4）。

事务级 fencing（审查 P0-2 修正）：**每个执行事实写事务的第一步**是对
Execution 主记录做带 token 条件的 ``$inc write_version``。takeover 也修改
同一主记录——旧 Worker 的事务与 takeover 事务因此在同一文档上形成
MongoDB 写冲突，二者只可能有一个提交成功。只在子集合写入时过滤 token
不构成防并发（事务写冲突以文档为单位）。

铁律 2：状态变更与事件同事务——``append_event`` 只在 ``transaction()``
上下文内可用，不存在独立入口。

诊断事件（fenced 拒绝记录）由 ``record_fenced_diagnostic`` 写入：它不携带
调用方 token、不推进任何执行事实，是唯一允许绕过 fencing 的写入口，
producer 恒为 ``system``（提案 §5.2）。
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from types import TracebackType
from typing import Any, TypeVar

from motor.motor_asyncio import (
    AsyncIOMotorClientSession,
    AsyncIOMotorCollection,
    AsyncIOMotorDatabase,
)
from pymongo import ReturnDocument
from pymongo.errors import PyMongoError

from app.db.mongodb import get_database
from app.engine.execution import collections as cols
from app.engine.execution.models import (
    CheckpointManifest,
    ExecutionEvent,
    Step,
    ToolInvocation,
)

T = TypeVar("T")


class LeaseLostError(RuntimeError):
    """当前 Worker 不再持有有效 Lease（token 过期/被接管）。

    调用方必须停止推进当前执行并退出；不得用旧 token 追加普通执行事件。
    """

    def __init__(self, execution_id: str, expected_token: int):
        self.execution_id = execution_id
        self.expected_token = expected_token
        super().__init__(
            f"Lease lost for execution {execution_id} "
            f"(held token={expected_token} no longer current) — stop progressing"
        )


class ExecutionTxn:
    """事务上下文（``ExecutionRepository.transaction()`` 产出）。

    进入时已完成 fencing 触碰（主记录条件 ``$inc write_version``）；
    退出无异常 → 提交，有异常 → 回滚。Session 供各写方法复用。
    """

    def __init__(
        self,
        repo: ExecutionRepository,
        execution_id: str,
        token: int,
        session: AsyncIOMotorClientSession,
    ):
        self._repo = repo
        self.execution_id = execution_id
        self.token = token
        self.session = session
        self._committed = False

    async def __aenter__(self) -> ExecutionTxn:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if exc_type is None:
            await self.session.commit_transaction()
            self._committed = True
        else:
            await self.session.abort_transaction()

    # ── 事务内写原语 ──────────────────────────────────────────────────

    async def update_execution(self, update: dict[str, Any]) -> None:
        """更新 Execution 主记录（fencing 条件已在事务开启时验证）。"""
        await self._repo._executions().update_one(
            {"_id": self.execution_id}, update, session=self.session
        )

    async def insert_step(self, step: Step) -> None:
        await self._repo._steps().insert_one(
            step.model_dump(by_alias=True), session=self.session
        )

    async def update_step(self, step_id: str, update: dict[str, Any]) -> None:
        await self._repo._steps().update_one(
            {"_id": step_id, "execution_id": self.execution_id},
            update,
            session=self.session,
        )

    async def insert_manifest(self, manifest: CheckpointManifest) -> None:
        await self._repo._checkpoints().insert_one(
            manifest.model_dump(by_alias=True), session=self.session
        )

    async def upsert_tool_invocation(self, inv: ToolInvocation) -> None:
        """账本 upsert：幂等键冲突时更新既有记录（恢复期重放 prepare）。"""
        await self._repo._tool_invocations().update_one(
            {"execution_id": inv.execution_id, "idempotency_key": inv.idempotency_key},
            {"$setOnInsert": inv.model_dump(by_alias=True)},
            upsert=True,
            session=self.session,
        )

    async def update_tool_invocation(
        self, invocation_id: str, update: dict[str, Any]
    ) -> None:
        await self._repo._tool_invocations().update_one(
            {"_id": invocation_id, "execution_id": self.execution_id},
            update,
            session=self.session,
        )

    async def append_event(self, event: ExecutionEvent, *, allocate_seq: bool = True) -> int:
        """事务内追加事件（铁律 2：只在本上下文存在）。

        seq 由主记录 ``event_seq_counter`` 原子自增分配（ReturnDocument.AFTER
        ——默认 BEFORE 会拿到旧计数，审查修正项）；调用方通常不预设 seq。
        """
        if allocate_seq:
            doc = await self._repo._executions().find_one_and_update(
                {"_id": self.execution_id},
                {"$inc": {"event_seq_counter": 1}},
                return_document=ReturnDocument.AFTER,
                session=self.session,
            )
            if doc is None:  # pragma: no cover - 事务开启时已确认存在
                raise LeaseLostError(self.execution_id, self.token)
            event.seq = doc["event_seq_counter"]
        await self._repo._events().insert_one(
            event.model_dump(by_alias=True), session=self.session
        )
        return event.seq


class ExecutionRepository:
    """执行域唯一写入通道。所有方法面向 ``get_database()``。"""

    def __init__(self, db: AsyncIOMotorDatabase | None = None):
        self._db = db

    def _database(self) -> AsyncIOMotorDatabase:
        return self._db if self._db is not None else get_database()

    def _executions(self) -> AsyncIOMotorCollection:
        return self._database()[cols.EXECUTIONS]

    def _steps(self) -> AsyncIOMotorCollection:
        return self._database()[cols.STEPS]

    def _checkpoints(self) -> AsyncIOMotorCollection:
        return self._database()[cols.CHECKPOINT_MANIFESTS]

    def _events(self) -> AsyncIOMotorCollection:
        return self._database()[cols.EXECUTION_EVENTS]

    def _tool_invocations(self) -> AsyncIOMotorCollection:
        return self._database()[cols.TOOL_INVOCATIONS]

    # ── 读取（无 fencing——读不改事实） ────────────────────────────────

    async def get_execution(self, execution_id: str) -> dict[str, Any] | None:
        return await self._executions().find_one({"_id": execution_id})

    async def get_step(self, step_id: str) -> dict[str, Any] | None:
        return await self._steps().find_one({"_id": step_id})

    async def latest_manifest(self, execution_id: str) -> dict[str, Any] | None:
        return await self._checkpoints().find_one(
            {"execution_id": execution_id}, sort=[("checkpoint_seq", -1)]
        )

    async def read_events(
        self, execution_id: str, *, after_seq: int = 0, limit: int = 200
    ) -> list[dict[str, Any]]:
        """游标读（SSE/重放的唯一消费方式；Redis 只做通知）。"""
        cursor = (
            self._events()
            .find({"execution_id": execution_id, "seq": {"$gt": after_seq}})
            .sort("seq", 1)
            .limit(limit)
        )
        return [doc async for doc in cursor]

    async def lookup_invocation(self, idempotency_key: str) -> dict[str, Any] | None:
        return await self._tool_invocations().find_one(
            {"idempotency_key": idempotency_key}
        )

    # ── 事务级 fencing 写入 ──────────────────────────────────────────

    @asynccontextmanager
    async def transaction(self, execution_id: str, expected_token: int):
        """执行事实写事务：开启即触碰主记录（铁律 4）。

        带 token 条件的 ``$inc write_version`` 失败 = Lease 已丢失/被接管
        → ``LeaseLostError``（事务不开启，调用方立即停止推进）。
        """
        db = self._database()
        async with await db.client.start_session() as session:
            touched = await self._executions().find_one_and_update(
                {"_id": execution_id, "lease.fencing_token": expected_token},
                {"$inc": {"write_version": 1}},
                return_document=ReturnDocument.AFTER,
                session=session,
            )
            if touched is None:
                # 区分「execution 不存在」与「token 过期」便于诊断。
                exists = await self._executions().find_one(
                    {"_id": execution_id}, {"_id": 1}, session=session
                )
                if exists is None:
                    raise KeyError(f"execution not found: {execution_id}")
                raise LeaseLostError(execution_id, expected_token)

            async with session.start_transaction():
                txn = ExecutionTxn(self, execution_id, expected_token, session)
                async with txn:
                    yield txn

    async def record_fenced_diagnostic(
        self, execution_id: str, rejected_token: int, context: str
    ) -> None:
        """记录 fenced 拒绝的诊断事件（提案 §5.2）。

        由服务端（本方法）写、producer=system、不带 token——这是唯一
        绕过 fencing 的写入口，旧 Worker 不得用它追加普通执行事件
        （type 固定 ``execution.fenced``，事件域可识别）。
        """
        from app.engine.execution.models import ExecutionEvent

        # seq 分配不依赖被拒绝的 token：直接对主记录自增（无事务——
        # 诊断通道允许尽力而为， uniqueness 由 (execution_id, seq) 兜底重试）。
        for _ in range(3):
            try:
                doc = await self._executions().find_one_and_update(
                    {"_id": execution_id},
                    {"$inc": {"event_seq_counter": 1}},
                    return_document=ReturnDocument.AFTER,
                )
                if doc is None:
                    return
                event = ExecutionEvent(
                    execution_id=execution_id,
                    seq=doc["event_seq_counter"],
                    type="execution.fenced",
                    producer="system",
                    payload={
                        "rejected_token": rejected_token,
                        "context": context,
                    },
                )
                await self._events().insert_one(event.model_dump(by_alias=True))
                return
            except PyMongoError:
                continue  # 序号冲突（并发 fenced 记录）→ 重试
