"""LeaseManager —— Execution 所有权 CAS（#64 提案 §3.5/§4.2 + 架构 v2 §3.2）。

与 Celery 解耦（审查 P1 修正）：Lease 只表达执行所有权；发现与接管由
RecoverySupervisor 扫描承担（E3），不依赖 visibility_timeout。

参数起点（压测后调整）：heartbeat 10–15s、TTL 45–60s（settings 可配）。
所有接管必须提升 fencing_token；token 单调递增、不得回退或复用。
"""
from __future__ import annotations

from datetime import timedelta

from pymongo import ReturnDocument

from app.core.config import settings
from app.engine.execution.models import LeaseInfo
from app.engine.execution.repository import ExecutionRepository, LeaseLostError
from app.models.base import generate_id, utc_now


class LeaseManager:
    """Lease 原语。CAS 全部落在 executions 主记录上——与 Repository 的
    事务级 fencing 共享同一冲突文档（铁律 4 的另一半）。"""

    def __init__(self, repo: ExecutionRepository | None = None):
        self._repo = repo or ExecutionRepository()

    def _collection(self):
        return self._repo._executions()  # noqa: SLF001 - 同包协作层

    async def acquire(
        self, execution_id: str, owner: str, *, token: int = 1
    ) -> LeaseInfo:
        """worker 认领：无 lease 且非终态时获取（token 从 1 起）。

        用于 dispatch → in_progress 的首次认领；重复认领由条件
        ``lease: None`` 互斥（输家返回 None → 调用方退出）。
        """
        now = utc_now()
        ttl = timedelta(seconds=settings.EXECUTION_LEASE_TTL_SECONDS)
        lease = LeaseInfo(
            owner=owner,
            fencing_token=token,
            heartbeat_at=now,
            expires_at=now + ttl,
        )
        doc = await self._collection().find_one_and_update(
            {"_id": execution_id, "lease": None, "status": {"$nin": [
                "succeeded", "failed", "cancelled", "timed_out", "expired",
            ]}},
            {"$set": {"lease": lease.model_dump()}},
            return_document=ReturnDocument.AFTER,
        )
        if doc is None:
            raise LeaseLostError(execution_id, token)
        return lease

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
        """过期接管：CAS（expires_at <= now）→ token+1。

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
                {
                    "$set": {
                        "lease": {
                            "owner": owner,
                            "lease_id": real_id,
                            # token 单调 +1：接管必须提升，不得回退或复用
                            "fencing_token": {"$add": ["$lease.fencing_token", 1]},
                            "heartbeat_at": now,
                            "expires_at": expires_at,
                        }
                    }
                }
            ],
            return_document=ReturnDocument.AFTER,
        )
        if doc is None:
            return None
        return LeaseInfo(**doc["lease"])

    async def release(self, execution_id: str, token: int) -> None:
        """正常完成释放（终态事务内调用；token 校验防误释放他人执行）。"""
        result = await self._collection().update_one(
            {"_id": execution_id, "lease.fencing_token": token},
            {"$set": {"lease": None}},
        )
        if result.matched_count == 0:
            raise LeaseLostError(execution_id, token)
