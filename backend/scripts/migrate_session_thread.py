"""迁移脚本：老 session 历史 → thread checkpoint（批量预热）。

对每个有 agent 消息的 session，重建 LangChain messages 并写入 thread
checkpoint（thread_id = session_id）。灌入后该 session 的 thread 非空，
后续请求走新路径（只喂增量），不再依赖 MessageRecord 重建历史。

此脚本与懒迁移（MIGRATE_LEGACY_SESSIONS=True）二选一即可：
- 懒迁移：首次请求时自动灌入（每次请求多一次 aget_state 检查）
- 本脚本：一次性批量灌入，灌完后 MIGRATE_LEGACY_SESSIONS 可以关掉

用法：
    cd backend
    source .venv/bin/activate
    # 干跑（只打印，不写库）
    python scripts/migrate_session_thread.py --dry-run
    # 实跑
    python scripts/migrate_session_thread.py
"""
from __future__ import annotations

import argparse
import asyncio
import sys

sys.path.insert(0, ".")


async def migrate(*, dry_run: bool, only_session: str | None) -> None:
    from agent_flow_harness import (
        build_agent_graph,
        build_config,
        configure_checkpointer,
        get_checkpointer,
    )
    from app.db.mongodb import get_database
    from app.engine.harness_integration.history import rebuild_messages_from_records
    from langgraph.checkpoint.memory import MemorySaver

    # 用进程级 checkpointer（生产环境 lifespan 会覆盖为 MongoDB）
    # 这里显式用 MongoDB checkpointer，确保灌入的数据持久化
    try:
        from agent_flow_harness import build_mongo_saver
        from app.core.config import settings
        from app.db.mongodb import get_mongodb_client
        saver = build_mongo_saver(client=get_mongodb_client().delegate, db_name=settings.MONGODB_DB_NAME)
        configure_checkpointer(saver, overwrite=True)
        print(f"checkpointer: MongoDB ({settings.MONGODB_DB_NAME})")
    except Exception as e:
        configure_checkpointer(MemorySaver(), overwrite=True)
        print(f"checkpointer: MemorySaver (MongoDB unavailable: {e})")

    db = get_database()

    # 找所有有 agent 消息的 session
    pipeline = [
        {"$match": {"role": "agent"}},
        {"$group": {"_id": "$session_id", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]
    sessions = await db["messages"].aggregate(pipeline).to_list(10000)

    if only_session:
        sessions = [s for s in sessions if s["_id"] == only_session]

    print(f"待迁移 session 数: {len(sessions)}")
    print(f"模式: {'干跑（不写库）' if dry_run else '实跑'}")
    print()

    migrated = 0
    skipped = 0
    failed = 0

    for sess in sessions:
        session_id = sess["_id"]
        msg_count = sess["count"]

        # 取这个 session 的 agent_id（从第一条 user/agent 消息）
        sample = await db["messages"].find_one({"session_id": session_id})
        if sample is None:
            continue
        # 找 agent_id：session 文档里有
        session_doc = await db["sessions"].find_one({"_id": session_id})
        if session_doc is None:
            print(f"  跳过 {session_id}: session 文档不存在")
            skipped += 1
            continue
        agent_id = session_doc.get("agent_id")
        if not agent_id:
            print(f"  跳过 {session_id}: 无 agent_id")
            skipped += 1
            continue

        # 读历史
        records = await db["messages"].find({"session_id": session_id}).sort("created_at", 1).to_list(1000)
        rebuilt = await rebuild_messages_from_records(records)
        if not rebuilt:
            print(f"  跳过 {session_id}: 重建后为空")
            skipped += 1
            continue

        if dry_run:
            print(f"  [干跑] {session_id}: {msg_count} 条消息 → {len(rebuilt)} 条 LangChain messages")
            migrated += 1
            continue

        # 灌入 thread
        try:
            agent_doc = await db["agents"].find_one({"_id": agent_id})
            if agent_doc is None:
                print(f"  跳过 {session_id}: agent {agent_id} 不存在")
                skipped += 1
                continue

            # 最小 agent_doc
            min_doc = {"_id": agent_doc.get("_id", "agent"), "name": agent_doc.get("name", "agent")}
            graph = build_agent_graph(min_doc, checkpointer=get_checkpointer(), tools=[], middleware=[])
            config = build_config(min_doc, llm=None, tools=[], thread_id=session_id)  # type: ignore[arg-type]

            # 检查是否已迁移
            state = await graph.aget_state(config)
            if state.values:
                print(f"  跳过 {session_id}: thread 已有数据")
                skipped += 1
                continue

            await graph.aupdate_state(config, {"messages": rebuilt})
            print(f"  ✅ {session_id}: 灌入 {len(rebuilt)} 条消息")
            migrated += 1
        except Exception as e:
            print(f"  ❌ {session_id}: 失败 - {e}")
            failed += 1

    print(f"\n{'='*40}")
    print(f"迁移: {migrated}, 跳过: {skipped}, 失败: {failed}")


def main() -> None:
    parser = argparse.ArgumentParser(description="老 session 历史 → thread 迁移")
    parser.add_argument("--dry-run", action="store_true", help="只打印，不写库")
    parser.add_argument("--session", default=None, help="只迁移指定 session（调试用）")
    args = parser.parse_args()
    asyncio.run(migrate(dry_run=args.dry_run, only_session=args.session))


if __name__ == "__main__":
    main()
