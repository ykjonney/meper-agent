"""One-click wiki build — async Celery task.

Owns the KB-level ``last_build_status`` lifecycle: running (re-entry
guard) → completed | failed. The actual LLM loop lives in
``app.services.kb_wiki_builder.run_wiki_build``.
"""
from typing import Any

from loguru import logger

from app.workers.celery_app import celery_app
from app.workers.loop import run_async


@celery_app.task(name="app.workers.tasks.wiki_build.build_wiki_kb")
def build_wiki_kb(kb_id: str) -> dict[str, Any]:
    """Build/update the wiki layer for one KB (Celery entry point)."""
    return run_async(_build_async(kb_id))


async def _build_async(kb_id: str) -> dict[str, Any]:
    from app.db.mongodb import get_database
    from app.models.base import utc_now
    from app.services.kb_wiki_builder import run_wiki_build

    col = get_database()["knowledge_bases"]
    now = utc_now().isoformat()

    # Re-entry guard: claim the running slot atomically.
    claimed = await col.find_one_and_update(
        {"_id": kb_id, "last_build_status": {"$ne": "running"}},
        {"$set": {"last_build_status": "running", "last_build_at": now, "last_build_error": ""}},
    )
    if claimed is None:
        logger.warning("wiki_build_already_running", kb_id=kb_id)
        return {"status": "already_running", "kb_id": kb_id}

    try:
        result = await run_wiki_build(kb_id)
    except Exception as exc:
        logger.exception("wiki_build_failed", kb_id=kb_id)
        reason = str(exc) or type(exc).__name__  # 空 message 异常也给个名字
        await col.update_one(
            {"_id": kb_id},
            {"$set": {"last_build_status": "failed", "last_build_error": reason[:2000]}},
        )
        return {"status": "failed", "kb_id": kb_id, "error": reason}

    status = result.get("status", "completed")
    error = str(result.get("error") or "") if status == "failed" else ""
    if status == "failed" and not error:
        error = "构建失败但未返回原因——请查看 Worker 日志 wiki_build_failed 事件"
    if status == "completed":
        # 回写 digest_hash：本次构建覆盖到的（已被引用的）源以当前内容盖章，
        # 供下次构建识别「已引用但内容已更新」的源。
        from app.services.kb_wiki_builder import stamp_digested

        stamped = await stamp_digested(kb_id)
        if stamped:
            logger.info("wiki_build_digest_stamped", kb_id=kb_id, stamped=stamped)
    await col.update_one(
        {"_id": kb_id},
        {
            "$set": {
                "last_build_status": status,
                "last_build_error": error[:2000],
                "updated_at": utc_now().isoformat(),
            }
        },
    )
    logger.info("wiki_build_finished", kb_id=kb_id, status=status, steps=result.get("steps"))
    return result
