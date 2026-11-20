"""RecoverySupervisor —— 执行域三类扫描（E3，架构 v2 §3.6）。

扫描协议（互斥条件，覆盖提案 §9 前两行故障矩阵）：

1. **待派发**：``status=queued`` 且 (dispatch.state=pending 或
   dispatched+next_dispatch_at 到期) → 投递并记 dispatch 元数据（指数退避）。
2. **过期接管**：``status=running`` 且 ``lease.expires_at < now`` →
   takeover（token+1）→ 以新 token 写 ``execution.takeover`` 事件 →
   release → 重置派发状态并立即投递。接管者与旧持有者在主记录上
   CAS 互斥，旧 Worker 的在途写入被 fencing 拒绝。
3. **活跃防重**：``running`` 且 lease 活跃 → 跳过（绝不重复启动）。

dispatch 字段与 lease 同属**调度协调元数据**（scheduler-owned）——它们
由原子 CAS 维护，不经执行事实的 fencing 事务（类比 takeover 本身）。

发现通道：Celery beat 周期任务（``app.workers.tasks.execution_recovery``）；
worker 崩溃不再依赖任何单一进程的内存状态。
"""
from __future__ import annotations

import contextlib
from dataclasses import dataclass
from datetime import timedelta

from loguru import logger

from app.engine.execution.collections import EXECUTIONS
from app.engine.execution.dispatcher import Dispatcher, get_dispatcher
from app.engine.execution.models import ExecutionEvent
from app.engine.execution.repository import ExecutionRepository, LeaseLostError
from app.models.base import utc_now

# 单轮扫描批量上限：避免单 tick 处理过载（下一轮继续）。
_SCAN_BATCH = 50

# 派发退避：5s 起步指数退避，封顶 5 分钟。
_DISPATCH_BACKOFF_BASE_SECONDS = 5
_DISPATCH_BACKOFF_MAX_SECONDS = 300


def _backoff_seconds(attempts: int) -> int:
    return min(
        _DISPATCH_BACKOFF_BASE_SECONDS * (2 ** max(0, attempts - 1)),
        _DISPATCH_BACKOFF_MAX_SECONDS,
    )


@dataclass
class ScanReport:
    """单轮扫描结果（日志/观测用）。"""

    redispatched: int = 0   # 扫描类 1：首次投递或重试
    taken_over: int = 0     # 扫描类 2：接管后重派
    skipped_active: int = 0  # 扫描类 3 活跃执行计数（防重观察）


class RecoverySupervisor:
    def __init__(
        self,
        repo: ExecutionRepository | None = None,
        dispatcher: Dispatcher | None = None,
        owner: str = "supervisor",
    ):
        from app.engine.execution.lease import LeaseManager

        self._repo = repo or ExecutionRepository()
        self._dispatcher = dispatcher or get_dispatcher()
        self._lease = LeaseManager(self._repo)
        self._owner = owner

    def _collection(self):
        return self._repo._executions()  # noqa: SLF001 - 同包协作层

    async def scan_once(self) -> ScanReport:
        report = ScanReport()
        report.redispatched = await self._scan_due_dispatches()
        report.taken_over = await self._scan_expired_leases()
        report.skipped_active = await self._count_active()
        if report.redispatched or report.taken_over:
            logger.info(
                "execution_scan redispatched={} taken_over={} active={}",
                report.redispatched,
                report.taken_over,
                report.skipped_active,
            )
        return report

    # ── 扫描类 1：待派发 / 派发重试 ──────────────────────────────────

    async def _scan_due_dispatches(self) -> int:
        now = utc_now()
        cursor = self._collection().find(
            {
                "status": "queued",
                "$or": [
                    {"dispatch.state": "pending"},
                    {
                        "dispatch.state": "dispatched",
                        "dispatch.next_dispatch_at": {"$lte": now},
                    },
                ],
            }
        ).limit(_SCAN_BATCH)

        count = 0
        async for doc in cursor:
            if await self._redispatch(doc["_id"], doc.get("dispatch", {})):
                count += 1
        return count

    async def _redispatch(self, execution_id: str, dispatch: dict) -> bool:
        attempts = int(dispatch.get("attempts", 0)) + 1
        # 先落 dispatch 元数据（原子 CAS 防双 supervisor 并发重复计数），
        # 再投递——顺序与创建路径一致：状态先行，投递可失败由下轮兜底。
        result = await self._collection().update_one(
            {
                "_id": execution_id,
                "status": "queued",
                "$or": [
                    {"dispatch.state": "pending"},
                    {"dispatch.state": "dispatched"},
                ],
            },
            {
                "$set": {
                    "dispatch.state": "dispatched",
                    "dispatch.attempts": attempts,
                    "dispatch.last_dispatch_at": utc_now(),
                    "dispatch.next_dispatch_at": utc_now()
                    + timedelta(seconds=_backoff_seconds(attempts)),
                }
            },
        )
        if result.matched_count == 0:
            return False  # 已被并发处理/状态变化
        try:
            await self._dispatcher.dispatch(execution_id)
        except Exception as exc:  # noqa: BLE001 - 投递失败留下轮退避重试
            logger.warning(
                "execution_dispatch_failed execution={} attempts={} error={}",
                execution_id,
                attempts,
                exc,
            )
        return True

    # ── 扫描类 2：过期接管 ──────────────────────────────────────────

    async def _scan_expired_leases(self) -> int:
        now = utc_now()
        cursor = self._collection().find(
            {"status": "running", "lease.expires_at": {"$lt": now}}
        ).limit(_SCAN_BATCH)

        count = 0
        async for doc in cursor:
            if await self._takeover_and_redispatch(doc["_id"]):
                count += 1
        return count

    async def _takeover_and_redispatch(self, execution_id: str) -> bool:
        lease = await self._lease.takeover(execution_id, self._owner)
        if lease is None:
            return False  # 未过期/已被接管/不存在——竞争失败，下一轮再看

        # 以新 token 写接管事件（supervisor 此刻持有 lease，可写事实）
        try:
            async with self._repo.transaction(
                execution_id, expected_token=lease.fencing_token
            ) as txn:
                await txn.append_event(
                    ExecutionEvent(
                        execution_id=execution_id,
                        seq=0,
                        type="execution.takeover",
                        producer="supervisor",
                        payload={
                            "previous_owner": None,  # 事件消费者按需从历史推
                            "new_owner": self._owner,
                            "fencing_token": lease.fencing_token,
                        },
                    )
                )
                # 重置派发与状态：running→queued（重派语义——worker 认领后
                # 再回 running），走全新一轮投递计数
                await txn.update_execution(
                    {
                        "$set": {
                            "status": "queued",
                            "dispatch.state": "pending",
                            "dispatch.attempts": 0,
                            "dispatch.next_dispatch_at": None,
                        }
                    }
                )
        except (LeaseLostError, KeyError):
            # 极端并发：又被更高 token 接管——本 supervisor 退出竞争。
            logger.info("execution_takeover_race_lost execution={}", execution_id)
            return False

        # 释放 lease 让重派 worker 走正常 acquire 认领（token 持续单调）；
        # 已被更高代持有时无需处理（竞争失败方）。
        with contextlib.suppress(LeaseLostError):
            await self._lease.release(execution_id, lease.fencing_token)

        await self._redispatch(execution_id, {"state": "pending", "attempts": 0})
        logger.info(
            "execution_takeover execution={} new_token={}",
            execution_id,
            lease.fencing_token,
        )
        return True

    # ── 扫描类 3：活跃防重（仅计数观察，绝不启动） ────────────────────

    async def _count_active(self) -> int:
        return await self._collection().count_documents(
            {"status": "running", "lease.expires_at": {"$gt": utc_now()}}
        )


# 扫描查询导出（beat 任务/测试复用，避免重复字面量漂移）
SCAN_COLLECTION = EXECUTIONS
