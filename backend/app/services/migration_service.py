"""Migration service — one-shot data migrations run at startup.

prompt_slots → system_prompt（五槽废弃迁移，见 scripts/migrate_system_prompt.py）：
由 settings.MIGRATE_PROMPT_SLOTS_ON_STARTUP 控制是否随启动执行（默认开，
存量环境自动迁移；确认迁移完成后置 false 关闭，启动少一次全表扫描）。
"""
from __future__ import annotations

from app.db.mongodb import get_database

# 与 SLOT_SCHEMA 同序同 label（role→task→constraints→context→output_format）
_SLOT_ORDER = [
    ("role", "角色定义"),
    ("task", "任务描述"),
    ("constraints", "约束规则"),
    ("context", "上下文信息"),
    ("output_format", "输出格式"),
]


def merge_slots_to_system_prompt(slots: dict) -> str:
    """按旧渲染格式合并槽位为整段（与 slot_renderer 旧行为等价，零漂移）。"""
    parts = [
        f"【{label}】\n{slots[name]}"
        for name, label in _SLOT_ORDER
        if str(slots.get(name) or "").strip()
    ]
    return "\n\n".join(parts)


async def migrate_prompt_slots() -> tuple[int, int]:
    """prompt_slots → system_prompt 启动迁移。

    幂等：prompt_slots 为空/缺失的文档自动跳过，可重复执行。迁移后
    prompt_slots 字段 unset（新代码不再读它）。

    Returns:
        (迁移数, 跳过数)。
    """
    from loguru import logger

    db = get_database()
    col = db["agents"]

    migrated = skipped = 0
    async for doc in col.find({"prompt_slots": {"$exists": True}}, {"_id": 1, "name": 1, "prompt_slots": 1}):
        slots = doc.get("prompt_slots") or {}
        if not any(str(v or "").strip() for v in slots.values()):
            skipped += 1
            continue

        system_prompt = merge_slots_to_system_prompt(slots)
        update: dict = {"$set": {"system_prompt": system_prompt}}
        if slots:
            update["$unset"] = {"prompt_slots": ""}
        await col.update_one({"_id": doc["_id"]}, update)
        migrated += 1
        logger.info("startup_migrate_prompt_slots", agent_id=str(doc["_id"]), name=doc.get("name", ""), length=len(system_prompt))

    if migrated or skipped:
        logger.info("startup_migrate_prompt_slots_done", migrated=migrated, skipped=skipped)
    return migrated, skipped
