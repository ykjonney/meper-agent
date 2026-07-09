"""迁移脚本：agent 消息数据模型 v1 → v2。

变更内容：
1. agent 消息的 timeline_entries 里 type="final_answer" → type="text"
2. agent 消息删除顶层 content 字段（正文只在 timeline 的 text 条目里）
3. 没有 timeline 的 agent 消息（纯文本老数据）直接删除

user 消息不动（content 是用户正文，无 timeline）。

用法：
    cd backend
    source .venv/bin/activate
    # 干跑（只打印变更，不写库）
    python scripts/migrate_messages_v2.py --dry-run
    # 实跑
    python scripts/migrate_messages_v2.py

支持 --db 指定数据库名（默认读 settings.MONGODB_DB_NAME）。
"""
from __future__ import annotations

import argparse
import asyncio
import sys

# 确保能 import app.*
sys.path.insert(0, ".")


async def migrate(*, dry_run: bool, db_name: str | None) -> None:
    from app.core.config import settings
    from app.db.mongodb import get_database

    db = get_database()
    col = db["messages"]

    target_db = db_name or settings.MONGODB_DB_NAME
    print(f"数据库: {target_db}")
    print(f"模式: {'干跑（不写库）' if dry_run else '实跑'}")
    print()

    # ── 1. 无 timeline 的 agent 消息：删除 ──
    no_tl_filter = {
        "role": "agent",
        "$or": [
            {"timeline_entries": {"$exists": False}},
            {"timeline_entries": {"$size": 0}},
            {"timeline_entries": None},
        ],
    }
    no_tl_count = await col.count_documents(no_tl_filter)
    print(f"[1] 无 timeline 的 agent 消息: {no_tl_count} 条 → 删除")
    if no_tl_count and not dry_run:
        result = await col.delete_many(no_tl_filter)
        print(f"    已删除: {result.deleted_count} 条")

    # ── 2. 有 timeline 的 agent 消息：final_answer→text + 删 content ──
    with_tl_filter = {
        "role": "agent",
        "timeline_entries": {"$ne": [], "$exists": True},
    }
    with_tl_msgs = await col.find(with_tl_filter).to_list(10000)
    print(f"\n[2] 有 timeline 的 agent 消息: {len(with_tl_msgs)} 条 → 改名+删 content")

    renamed = 0
    content_removed = 0
    for msg in with_tl_msgs:
        tl = msg.get("timeline_entries") or []
        update_ops: dict = {}

        # 2a. final_answer → text
        changed = False
        for entry in tl:
            if entry.get("type") == "final_answer":
                entry["type"] = "text"
                changed = True
        if changed:
            update_ops["$set"] = {"timeline_entries": tl}
            renamed += 1

        # 2b. 删 content 字段
        if "content" in msg:
            update_ops.setdefault("$unset", {})["content"] = ""
            content_removed += 1

        if update_ops and not dry_run:
            await col.update_one({"_id": msg["_id"]}, update_ops)

    print(f"    final_answer→text 改名: {renamed} 条")
    print(f"    content 字段删除: {content_removed} 条")

    # ── 汇总 ──
    print(f"\n{'='*40}")
    if dry_run:
        print("干跑完成，未写库。去掉 --dry-run 实跑。")
    else:
        print("迁移完成。")
        # 验证：确认无残留
        remaining_fa = await col.count_documents({
            "role": "agent",
            "timeline_entries.type": "final_answer",
        })
        remaining_content = await col.count_documents({
            "role": "agent",
            "content": {"$exists": True},
        })
        remaining_no_tl = await col.count_documents({
            "role": "agent",
            "$or": [
                {"timeline_entries": {"$exists": False}},
                {"timeline_entries": {"$size": 0}},
            ],
        })
        print(f"验证 — 残留 final_answer: {remaining_fa}（应为 0）")
        print(f"验证 — 残留 agent content: {remaining_content}（应为 0）")
        print(f"验证 — 残留无 timeline agent: {remaining_no_tl}（应为 0）")


def main() -> None:
    parser = argparse.ArgumentParser(description="迁移 agent 消息到 v2 格式")
    parser.add_argument("--dry-run", action="store_true", help="只打印变更，不写库")
    parser.add_argument("--db", default=None, help="数据库名（默认读 settings）")
    args = parser.parse_args()
    asyncio.run(migrate(dry_run=args.dry_run, db_name=args.db))


if __name__ == "__main__":
    main()
