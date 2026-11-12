"""迁移脚本：Agent prompt 五槽合并为整段 system_prompt。

prompt_slots 分段表单设计废弃——prompt 本质是连续文本，主流（GPTs/Coze/Dify）
均为单一自由文本框。本脚本把存量槽位按原渲染格式（【label】\\n值，\\n\\n 连接）
合并为 system_prompt 整段写回，行为与 slot_renderer 旧路径完全等价（零漂移）。

变更内容：
1. prompt_slots 非空的 agent：合并五槽（role/task/constraints/context/output_format）
   为 system_prompt，$unset prompt_slots
2. prompt_slots 为空的 agent：跳过（system_prompt 保持现状，通常为空）

合并格式与 slot_renderer 渲染顺序一致：role → task → constraints → context →
output_format；槽值中的 Jinja2 {{var}} 语法原样保留（运行时仍会解析）。

用法：
    cd backend
    # 干跑（只打印变更，不写库）
    uv run python scripts/migrate_system_prompt.py --dry-run
    # 实跑
    uv run python scripts/migrate_system_prompt.py
"""
from __future__ import annotations

import argparse
import asyncio
import sys

# 确保能 import app.*
sys.path.insert(0, ".")

# 与 agent_flow_harness SLOT_SCHEMA 同序同 label（role→task→constraints→context→output_format）
_SLOT_ORDER = [
    ("role", "角色定义"),
    ("task", "任务描述"),
    ("constraints", "约束规则"),
    ("context", "上下文信息"),
    ("output_format", "输出格式"),
]


def merge_slots_to_system_prompt(slots: dict) -> str:
    """按原渲染格式合并槽位为整段（与 slot_renderer 旧行为等价）。"""
    parts = [
        f"【{label}】\n{slots[name]}"
        for name, label in _SLOT_ORDER
        if str(slots.get(name) or "").strip()
    ]
    return "\n\n".join(parts)


async def migrate(*, dry_run: bool) -> None:
    from app.db.mongodb import get_database

    db = get_database()
    col = db["agents"]

    print(f"模式: {'干跑（不写库）' if dry_run else '实跑'}")
    print()

    migrated = skipped = 0
    async for doc in col.find({"prompt_slots": {"$exists": True}}, {"_id": 1, "name": 1, "prompt_slots": 1}):
        slots = doc.get("prompt_slots") or {}
        if not any(str(v or "").strip() for v in slots.values()):
            skipped += 1
            continue

        system_prompt = merge_slots_to_system_prompt(slots)
        name = doc.get("name", doc["_id"])
        preview = system_prompt.replace("\n", "⏎")[:120]
        print(f"• {name}（{doc['_id']}）→ {len(system_prompt)} 字符：{preview}…")

        if not dry_run:
            update: dict = {"$set": {"system_prompt": system_prompt}}
            if slots:
                update["$unset"] = {"prompt_slots": ""}
            await col.update_one({"_id": doc["_id"]}, update)
        migrated += 1

    print()
    print(f"迁移 {migrated} 个，跳过（无槽位）{skipped} 个" + ("（干跑未写库）" if dry_run else ""))


def main() -> None:
    parser = argparse.ArgumentParser(description="prompt_slots → system_prompt 数据迁移")
    parser.add_argument("--dry-run", action="store_true", help="只打印变更，不写库")
    args = parser.parse_args()
    asyncio.run(migrate(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
