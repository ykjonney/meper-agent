"""LeaseManager —— Execution 所有权 CAS（#64 提案 §3.5/§4.2 + 架构 v2 §3.2）。

与 Celery 解耦（审查 P1 修正）：Lease 只表达执行所有权；发现与接管由
RecoverySupervisor 扫描承担（E3），不依赖 visibility_timeout。

参数起点（压测后调整）：heartbeat 10–15s、TTL 45–60s（settings 可配）。

token 单调性（PR #73 第三轮审查 §1 修正）：主记录持有**持久化的
``fencing_token_counter``——首次 acquire、release 后 reacquire、takeover
都在同一文档上原子递增它并把新值写入 Lease。release 只清空 lease，不
清计数器，杜绝 "A(token=1) release → B acquire 也拿到 token=1 → A 的
旧事务被误接受"。

到期即失去所有权（第二轮审查 §4）：heartbeat 与 acquire/takeover 条件
均校验有效期。
"""
from __future__ import annotations

import contextlib
from contextlib import asynccontextmanager
from datetime import timedelta

from pymongo import ReturnDocument

from app.core.config import settings
from app.engine.execution.models import LeaseInfo
from app.engine.execution.repository import ExecutionRepository, LeaseLostError
from app.models.base import generate_id, utc_now

_TERMINAL = ["succeeded", "failed", "cancelled", "timed_out", "expired"]


def _counter_expr() -> dict:
    """聚合管道：counter = ifNull(counter, ifNull(lease.fencing_token, 0)) + 1。

    旧数据没有 counter 字段（E1 遗留）——从当前 lease token 接续，保证
    严格递增不回退（迁移即首次写入，无需后台任务）。
    """
    return {
        "$add": [
            {
                "$ifNull": [
                    "$fencing_token_counter",
                    {"$ifNull": ["$lease.fencing_token", 0]},
                ]
            },
            1,
        ]
    }


class LeaseManager:
    """Lease 原语。CAS 全部落在 executions 主记录上——与 Repository 的
    事务级 fencing 共享同一冲突文档（铁律 4 的另一半）。"""

    def __init__(self, repo: ExecutionRepository | None = None):
        self._repo = repo or ExecutionRepository()

    def _collection(self):
        return self._repo._executions()  # noqa: SLF001 - 同包协作层

    async def acquire(self, execution_id: str, owner: str) -> LeaseInfo:
        """worker 认领：无 lease 且非终态时获取（token = counter+1）。

        重复认领由条件 ``lease: None`` 互斥；token 从持久 counter 递增，
        reacquire 不会复用历史值。
        """
        now = utc_now()
        expires_at = now + timedelta(seconds=settings.EXECUTION_LEASE_TTL_SECONDS)
        real_id = generate_id("lease")
        doc = await self._collection().find_one_and_update(
            {"_id": execution_id, "lease": None, "status": {"$nin": _TERMINAL}},
            [
                # 两段管道：先递增 counter，后一段可见新 counter（引用无需重复计算）
                {"$set": {"fencing_token_counter": _counter_expr()}},
                {
                    "$set": {
                        "lease": {
                            "owner": owner,
                            "lease_id": real_id,
                            "fencing_token": "$fencing_token_counter",
                            "heartbeat_at": now,
                            "expires_at": expires_at,
                        }
                    }
                },
            ],
            return_document=ReturnDocument.AFTER,
        )
        if doc is None:
            raise LeaseLostError(execution_id, -1)
        return LeaseInfo(**doc["lease"])

    async def heartbeat(
        self, execution_id: str, owner: str, token: int
    ) -> LeaseInfo:
        """续约。以下任一情况 → LeaseLostError（PR #73 审查 §4）：

        - token 不匹配（被接管）；
        - **Lease 已过期**——到期即失去所有权（fail-safe 方向）：即使
          RecoverySupervisor 尚未 takeover，过期 Worker 也不能续约"复活"
          自己的所有权，必须等待重新派发/接管。
        """
        now = utc_now()
        ttl = timedelta(seconds=settings.EXECUTION_LEASE_TTL_SECONDS)
        doc = await self._collection().find_one_and_update(
            {
                "_id": execution_id,
                "lease.owner": owner,
                "lease.fencing_token": token,
                "lease.expires_at": {"$gt": now},
            },
            {
                "$set": {
                    "lease.heartbeat_at": now,
                    "lease.expires_at": now + ttl,
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        if doc is None:
            raise LeaseLostError(execution_id, token)
        return LeaseInfo(**doc["lease"])

    async def takeover(self, execution_id: str, owner: str) -> LeaseInfo | None:
        """过期接管：CAS（expires_at <= now）→ token = counter+1。

        - 成功：返回新 lease（新 lease_id、更高 token），旧持有者此后
          所有事实写入被 fencing 拒绝。
        - 失败（未过期 / 已被接管 / 不存在）：返回 None，不重试。
        """
        now = utc_now()
        expires_at = now + timedelta(seconds=settings.EXECUTION_LEASE_TTL_SECONDS)
        real_id = generate_id("lease")  # ULID 在管道外预生成
        doc = await self._collection().find_one_and_update(
            {
                "_id": execution_id,
                "status": {"$in": ["running", "queued"]},
                "lease.expires_at": {"$lte": now},
            },
            [
                {"$set": {"fencing_token_counter": _counter_expr()}},
                {
                    "$set": {
                        "lease": {
                            "owner": owner,
                            "lease_id": real_id,
                            "fencing_token": "$fencing_token_counter",
                            "heartbeat_at": now,
                            "expires_at": expires_at,
                        }
                    }
                },
            ],
            return_document=ReturnDocument.AFTER,
        )
        if doc is None:
            return None
        return LeaseInfo(**doc["lease"])

    async def release(self, execution_id: str, token: int) -> None:
        """正常完成释放（终态事务内调用；token 校验防误释放他人执行）。

        清空 lease 的**同时物化 ``fencing_token_counter``**（pipeline：
        先递增 counter 再清 lease）——若只清 lease，旧数据（E1 遗留、
        无 counter 字段）的迁移语义 ifNull(counter, lease.token) 会双双
        落空，reacquire 将退化回 token=1，破坏单调性。
        """
        doc = await self._collection().find_one_and_update(
            {"_id": execution_id, "lease.fencing_token": token},
            [
                {"$set": {"fencing_token_counter": _counter_expr()}},
                {"$set": {"lease": None}},
            ],
            return_document=ReturnDocument.AFTER,
        )
        if doc is None:
            raise LeaseLostError(execution_id, token)


# ── 心跳助手（E6/E7 Runner 契约）──────────────────────────────────────


@asynccontextmanager
async def lease_heartbeat(
    manager: LeaseManager,
    execution_id: str,
    owner: str,
    token: int,
):
    """Runner 执行期间的后台续约循环。

    **Runner 契约（E6/E7 必须遵守）**：lease TTL 默认 60s，执行超过 TTL
    又不续约 → RecoverySupervisor 会接管（fencing 挡旧写入是安全的，但
    执行会分裂）。长任务用本助手包裹执行体：

        async with lease_heartbeat(lm, exec_id, owner, token):
            await run_graph(...)   # 期间每 EXECUTION_LEASE_HEARTBEAT_SECONDS 续约

    LeaseLostError（被接管）从 ``__aexit__`` 传播——调用方按 zombie 协议
    停止推进。心跳失败即终止执行（fail-safe：宁可被重派不可双跑）。
    """
    import asyncio

    from app.core.config import settings

    parent_task = asyncio.current_task()
    if parent_task is None:  # pragma: no cover - async context always has a task
        raise RuntimeError("lease_heartbeat must run inside an asyncio Task")

    async def _loop() -> None:
        try:
            interval = settings.EXECUTION_LEASE_HEARTBEAT_SECONDS
            while True:
                await asyncio.sleep(interval)
                await manager.heartbeat(execution_id, owner, token)
        except asyncio.CancelledError:
            raise
        except Exception:
            # A failed child task does not automatically stop its parent.
            # Cancel the Runner immediately; awaiting this task in finally
            # then propagates the original LeaseLostError to the caller.
            parent_task.cancel()
            raise

    task = asyncio.create_task(_loop(), name=f"lease-heartbeat:{execution_id}")
    try:
        yield
    finally:
        if not task.done():
            task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
