"""CheckpointCoordinator —— 恢复 Manifest 的两阶段提交协调器（E4）。

提交协议（提案 §3.7，顺序不可换）：

1. **Graph Checkpoint 先落库**（agent 中断边界场景）——由调用方完成
   （node_executor 的 LangGraph checkpointer 自动保存），协调器只要求
   传入读回验证过的精确 identity（thread + ns + checkpoint_id）。
2. **Manifest + 事件同事务提交**（fenced txn）：$inc checkpoint_seq_counter
   分配序号 → insert Manifest → append checkpoint.committed 事件。

故障语义：
- Graph Checkpoint 成功、Manifest 失败 → 允许孤儿 Graph Checkpoint
  （非权威恢复点，checkpoint_prune 兜底回收）；
- Manifest 不先于 Graph Checkpoint 提交——引用不存在状态的窗口不允许。

E4 双写期（workflow 侧）：旧 Task.checkpoint 仍是权威恢复源，Manifest
为影子。影子 Execution 由 ``ensure_workflow_execution`` find-or-create，
持长期 lease（owner=workflow-shadow）使 fenced 写入合法——E6 切换权威
时由 Adapter 改为真实 lease 生命周期。
"""
from __future__ import annotations

from datetime import timedelta

from loguru import logger
from pymongo import ReturnDocument

from app.engine.execution.collections import EXECUTIONS
from app.engine.execution.models import (
    CheckpointManifest,
    Execution,
    ExecutionEvent,
    ExecutionStatus,
    LeaseInfo,
)
from app.engine.execution.repository import ExecutionRepository, LeaseLostError
from app.models.base import utc_now

# 影子 lease：远期过期（1 年）——影子执行不参与 supervisor 接管扫描的
# 正常节奏；E6 切换时由 Adapter 接管真实生命周期。
_SHADOW_LEASE_OWNER = "workflow-shadow"
_SHADOW_LEASE_DAYS = 365


class CheckpointCoordinator:
    def __init__(self, repo: ExecutionRepository | None = None):
        self._repo = repo or ExecutionRepository()

    async def commit_boundary(
        self,
        execution_id: str,
        token: int,
        *,
        kind: str,
        step_id: str | None = None,
        committed_step_ids: list[str] | None = None,
        graph_thread_id: str | None = None,
        graph_checkpoint_ns: str = "",
        graph_checkpoint_id: str | None = None,
    ) -> int:
        """提交一个恢复边界（fenced 事务：序号分配 + Manifest + 事件）。

        Returns:
            分配到的 checkpoint_seq。
        Raises:
            LeaseLostError / KeyError：fencing 拒绝（调用方停止推进）。
        """
        async with self._repo.transaction(execution_id, expected_token=token) as txn:
            # 序号原子分配（与事件 seq 同模式：主记录计数器 + AFTER）
            doc = await self._repo._executions().find_one_and_update(  # noqa: SLF001
                {"_id": execution_id},
                {"$inc": {"checkpoint_seq_counter": 1}},
                return_document=ReturnDocument.AFTER,
                session=txn.session,
            )
            if doc is None:  # pragma: no cover - 事务开启时已确认存在
                raise LeaseLostError(execution_id, token)
            seq = doc["checkpoint_seq_counter"]

            manifest = CheckpointManifest(
                execution_id=execution_id,
                checkpoint_seq=seq,
                step_id=step_id,
                committed_step_ids=committed_step_ids or [],
                kind=kind,
                graph_thread_id=graph_thread_id,
                graph_checkpoint_ns=graph_checkpoint_ns,
                graph_checkpoint_id=graph_checkpoint_id,
                fencing_token=token,
            )
            await txn.insert_manifest(manifest)
            await txn.append_event(
                ExecutionEvent(
                    execution_id=execution_id,
                    seq=0,
                    type="checkpoint.committed",
                    producer="checkpoint-coordinator",
                    payload={"checkpoint_seq": seq, "kind": kind, "step_id": step_id},
                )
            )
        return seq

    # ── E4 影子执行（workflow 双写期） ────────────────────────────────

    async def ensure_workflow_execution(self, task_id: str) -> tuple[str, int] | None:
        """find-or-create workflow 任务的影子 Execution，返回 (id, token)。

        幂等：按 task_id+trigger 查活跃（非终态）影子执行；创建原子性由
        唯一性需求保证——无唯一索引时并发可能创建多条，取查询到的第一条
        即可（对账脚本会发现；E6 建索引时收紧）。失败返回 None（影子
        双写尽力而为，绝不阻断权威路径）。
        """
        from app.db.mongodb import get_database

        try:
            db = get_database()
            existing = await db[EXECUTIONS].find_one(
                {"task_id": task_id, "trigger": "workflow", "status": {"$nin": [
                    "succeeded", "failed", "cancelled", "timed_out", "expired",
                ]}},
                sort=[("created_at", -1)],
            )
            if existing is not None:
                lease = existing.get("lease")
                if lease and lease.get("fencing_token"):
                    return existing["_id"], lease["fencing_token"]
                # 无 lease 的遗留影子：补一个长期 lease
                return await self._attach_shadow_lease(existing["_id"])

            now = utc_now()
            exe = Execution(
                task_id=task_id,
                trigger="workflow",
                status=ExecutionStatus.RUNNING,
                started_at=now,
            )
            token = 1
            exe.lease = LeaseInfo(
                owner=_SHADOW_LEASE_OWNER,
                fencing_token=token,
                expires_at=now + timedelta(days=_SHADOW_LEASE_DAYS),
            )
            await db[EXECUTIONS].insert_one(exe.model_dump(by_alias=True))
            return exe.id, token
        except Exception as exc:  # noqa: BLE001 - 影子路径不反噬权威执行
            logger.warning(
                "execution_shadow_ensure_failed task={} error={}", task_id, exc
            )
            return None

    async def _attach_shadow_lease(self, execution_id: str) -> tuple[str, int] | None:
        from app.db.mongodb import get_database

        db = get_database()
        now = utc_now()
        doc = await db[EXECUTIONS].find_one_and_update(
            {"_id": execution_id, "lease": None},
            {
                "$set": {
                    "lease": LeaseInfo(
                        owner=_SHADOW_LEASE_OWNER,
                        fencing_token=1,
                        expires_at=now + timedelta(days=_SHADOW_LEASE_DAYS),
                    ).model_dump(),
                    "fencing_token_counter": 1,
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        if doc is None:
            return None
        return doc["_id"], doc["lease"]["fencing_token"]

    async def shadow_commit_workflow_boundary(
        self,
        task_id: str,
        *,
        kind: str,
        step_id: str | None = None,
        committed_step_ids: list[str] | None = None,
        agent_thread_id: str | None = None,
    ) -> int | None:
        """E4 双写入口：影子提交 workflow 边界（尽力而为，不抛）。

        旧 Task.checkpoint 仍是权威恢复源；本方法失败只告警。
        """
        try:
            ensured = await self.ensure_workflow_execution(task_id)
            if ensured is None:
                return None
            execution_id, token = ensured
            return await self.commit_boundary(
                execution_id,
                token,
                kind=kind,
                step_id=step_id,
                committed_step_ids=committed_step_ids,
                # agent 中断边界：thread 即精确定位（LangGraph 最新 checkpoint）；
                # E6 接入读回验证的精确 checkpoint_id。
                graph_thread_id=agent_thread_id,
                graph_checkpoint_id=(
                    f"latest:{agent_thread_id}" if agent_thread_id else None
                ),
            )
        except Exception as exc:  # noqa: BLE001 - 影子双写绝不阻断权威路径
            logger.warning(
                "execution_shadow_commit_failed task={} kind={} error={}",
                task_id, kind, exc,
            )
            return None
