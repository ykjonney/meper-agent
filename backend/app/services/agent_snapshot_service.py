"""AgentSnapshotService — Agent 配置快照的创建 / 列表 / 回滚。

版本化是自优化循环的硬前置（"严格提升才保留"的物理前提是可回滚）：
- 每次 update_agent $set 之前自动快照当前完整状态
- 回滚 = 以快照恢复 + version 递增到 max+1（版本号永不复用）
- published 不可编辑的既有闸门保持——快照与回滚仅作用于 draft

存储：agent_snapshots 集合，每个 agent 按版本号索引（agent_id + version 唯一）。
"""

from __future__ import annotations

from loguru import logger

from app.db.mongodb import get_database
from app.models.agent import AgentSnapshot
from app.models.base import utc_now


class AgentSnapshotService:
    """CRUD for ``agent_snapshots``（静态方法风格，对齐 AgentService）。"""

    COLLECTION = "agent_snapshots"

    @staticmethod
    def _collection():
        return get_database()[AgentSnapshotService.COLLECTION]

    @staticmethod
    async def ensure_indexes() -> None:
        col = AgentSnapshotService._collection()
        await col.create_index(
            [("agent_id", 1), ("snapshot_of_version", -1)],
            unique=True,
            name="idx_asnap_agent_version",
        )
        logger.info("AgentSnapshot indexes ensured")

    # ── Create ──

    @staticmethod
    async def take_snapshot(
        agent_doc: dict,
        *,
        label: str = "update",
        created_by: str = "",
    ) -> dict | None:
        """在 update $set 之前调用：快照当前完整 Agent 状态。

        幂等：同版本号已有快照则跳过（DuplicateKeyError 吞掉）——
        保证"每个版本号恰好一份快照"的简单性。
        """
        from pymongo.errors import DuplicateKeyError

        agent_id = agent_doc.get("_id", "")
        version = int(agent_doc.get("version", 1) or 1)
        if not agent_id:
            return None
        snap = AgentSnapshot(
            agent_id=agent_id,
            snapshot_of_version=version,
            doc=agent_doc,
            label=label,
            created_by=created_by,
        )
        try:
            await AgentSnapshotService._collection().insert_one(snap.model_dump(by_alias=True))
        except DuplicateKeyError:
            return None  # 已有同版本快照（重复保存等场景）
        logger.info(
            "agent_snapshot_taken",
            agent_id=agent_id, version=version, label=label,
        )
        return snap.model_dump(by_alias=True)

    # ── Read ──

    @staticmethod
    async def list_snapshots(agent_id: str) -> list[dict]:
        """列某 Agent 的全部快照（版本倒序），返回摘要（不含 doc 全文）。"""
        cursor = (
            AgentSnapshotService._collection()
            .find(
                {"agent_id": agent_id},
                {"doc": 0},  # 摘要不带全文（体积控制）
            )
            .sort("snapshot_of_version", -1)
        )
        return await cursor.to_list(length=100)

    @staticmethod
    async def get_snapshot(agent_id: str, version: int) -> dict | None:
        """取指定版本的完整快照（含 doc 全文）。"""
        return await AgentSnapshotService._collection().find_one(
            {"agent_id": agent_id, "snapshot_of_version": version},
        )

    @staticmethod
    async def latest_version(agent_id: str) -> int:
        """Agent 当前最大版本号（无快照返回 1）。"""
        snap = await AgentSnapshotService._collection().find_one(
            {"agent_id": agent_id},
            sort=[("snapshot_of_version", -1)],
        )
        return int(snap["snapshot_of_version"]) if snap else 1

    # ── Restore ──

    @staticmethod
    async def restore(
        agent_id: str,
        version: int,
        *,
        created_by: str = "",
    ) -> dict | None:
        """回滚到指定版本：快照当前（保底）→ 以目标快照恢复 → version=max+1。

        版本号永不复用——恢复 v3 后新版本号是 max(v3,当前)+1，不是 v3。
        published 不可回滚（AGENT_PUBLISHED_IMMUTABLE 语义保持）。
        """
        from app.core.errors import ConflictError, NotFoundError
        from app.services.agent_service import AgentService

        current = await AgentService.get_agent(agent_id)
        if current is None:
            raise NotFoundError(code="AGENT_NOT_FOUND", message=f"Agent {agent_id} 不存在")
        if current.get("status") == "published":
            raise ConflictError(
                code="AGENT_PUBLISHED_IMMUTABLE",
                message="已发布 Agent 不可回滚——请先下架或复制。",
            )

        snapshot = await AgentSnapshotService.get_snapshot(agent_id, version)
        if snapshot is None:
            raise NotFoundError(
                code="SNAPSHOT_NOT_FOUND",
                message=f"Agent {agent_id} 无版本 v{version} 的快照",
            )

        # 1) 回滚前快照当前状态（防"回滚后后悔"——回滚本身可回滚）
        await AgentSnapshotService.take_snapshot(
            current, label="pre-restore", created_by=created_by,
        )

        # 2) 以快照恢复，version 取 max(目标版本, 当前版本) + 1（永不复用）
        restored = dict(snapshot["doc"])
        new_version = max(version, int(current.get("version", 1) or 1)) + 1
        restored["version"] = new_version
        restored["updated_at"] = utc_now().isoformat()
        # 恢复不改变 _id / created_at / status
        restored["_id"] = agent_id

        col = AgentService._collection()
        await col.replace_one({"_id": agent_id}, restored)

        logger.info(
            "agent_snapshot_restored",
            agent_id=agent_id, from_version=current.get("version"),
            to_version=new_version, restored_from=version,
        )
        return await AgentService.get_agent(agent_id)
