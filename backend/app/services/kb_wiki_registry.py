"""Wiki-mode source registry — Mongo-backed extraction lifecycle.

Registers source files uploaded to a wiki-mode tree KB and tracks their
async extraction (``pending → processing → ready | failed``). Wiki pages
need no registry (stats/lint scan the FS); only sources live here, so
the UI can show real per-file status and the builder can tell what has
been digested.

All state is derived: the registry can be rebuilt from the filesystem
(re-upload / re-extract) without losing knowledge.
"""
from __future__ import annotations

from loguru import logger

from app.db.mongodb import get_database
from app.models.base import utc_now
from app.models.kb_wiki_index import (
    EXTRACTABLE_TYPES,
    FAILED,
    PENDING,
    PROCESSING,
    READY,
)

COLLECTION = "kb_wiki_documents"


def _collection():
    return get_database()[COLLECTION]


async def _ensure_index() -> None:
    # Idempotent; unique upsert key is (knowledge_base_id, relative_path).
    await _collection().create_index(
        [("knowledge_base_id", 1), ("relative_path", 1)], unique=True
    )


async def register_source(
    kb_id: str,
    rel_path: str,
    file_type: str,
    file_size: int,
    content_hash: str,
    uploaded_by: str = "",
) -> dict:
    """Upsert a source registration (idempotent per kb+path).

    Extractable types enter ``pending`` (caller dispatches the Celery
    task); ``.md`` sources are readable as-is and go straight to ``ready``.
    Re-registering an unchanged file (same hash, ready) is a no-op so
    re-uploads don't trigger redundant extraction.
    """
    from app.engine.kb.tree import fs as kb_fs

    await _ensure_index()
    ft = (file_type or "").lower().lstrip(".")
    extractable = ft in EXTRACTABLE_TYPES
    extracted_path = kb_fs.extracted_path_for(kb_id, rel_path) if extractable else ""

    existing = await _collection().find_one(
        {"knowledge_base_id": kb_id, "relative_path": rel_path}
    )
    if (
        existing
        and existing.get("status") == READY
        and existing.get("content_hash") == content_hash
    ):
        return existing

    now = utc_now().isoformat()
    fields = {
        "knowledge_base_id": kb_id,
        "relative_path": rel_path,
        "file_type": ft,
        "file_size": file_size,
        "status": READY if not extractable else PENDING,
        "error": "",
        "content_hash": content_hash,
        "extracted_path": extracted_path,
        "extracted_at": "" if extractable else now,
        "uploaded_by": uploaded_by,
        "updated_at": now,
    }
    if existing:
        # digest_hash（上次构建消化时的内容指纹）刻意不在 fields 里——
        # 重传覆盖时保留旧值，供构建侧比对 content_hash 判断「内容已变更」。
        await _collection().update_one({"_id": existing["_id"]}, {"$set": fields})
    else:
        await _collection().insert_one(
            {"_id": _new_id(), "created_at": now, "digest_hash": "", **fields}
        )
    registered = await _collection().find_one(
        {"knowledge_base_id": kb_id, "relative_path": rel_path}
    )
    logger.info(
        "kb_wiki_source_registered",
        kb_id=kb_id,
        rel_path=rel_path,
        status=registered.get("status") if registered else "?",
    )
    return registered or fields


def _new_id() -> str:
    from app.models.base import generate_id

    return generate_id("kbwsrc")


async def get(doc_id: str) -> dict | None:
    return await _collection().find_one({"_id": doc_id})


async def set_status(doc_id: str, status: str, error: str = "") -> None:
    await _collection().update_one(
        {"_id": doc_id},
        {"$set": {"status": status, "error": error, "updated_at": utc_now().isoformat()}},
    )


async def mark_extracted(doc_id: str) -> None:
    now = utc_now().isoformat()
    await _collection().update_one(
        {"_id": doc_id},
        {"$set": {"status": READY, "error": "", "extracted_at": now, "updated_at": now}},
    )


async def mark_failed(doc_id: str, error: str) -> None:
    await set_status(doc_id, FAILED, error=error)


async def set_digest_hash(doc_id: str, digest_hash: str) -> None:
    """Stamp the content fingerprint of the last build that digested this source."""
    await _collection().update_one(
        {"_id": doc_id},
        {"$set": {"digest_hash": digest_hash, "updated_at": utc_now().isoformat()}},
    )


def processing_status() -> str:
    return PROCESSING


async def remove_source(kb_id: str, rel_path: str) -> None:
    await _collection().delete_one(
        {"knowledge_base_id": kb_id, "relative_path": rel_path}
    )


async def delete_by_kb(kb_id: str) -> None:
    await _collection().delete_many({"knowledge_base_id": kb_id})


async def list_by_kb(kb_id: str) -> list[dict]:
    cursor = _collection().find({"knowledge_base_id": kb_id}).sort("relative_path", 1)
    return await cursor.to_list(length=1000)


def dispatch_extract_task(doc_id: str) -> None:
    """Dispatch the Celery extraction task (lazy import; tests monkeypatch)."""
    try:
        from app.workers.tasks.wiki_source_extract import extract_wiki_source

        extract_wiki_source.delay(doc_id)
    except Exception as exc:
        logger.error("kb_wiki_extract_dispatch_failed", doc_id=doc_id, error=str(exc))
        raise RuntimeError(f"无法派发提取任务，请检查 Celery 是否运行: {exc}") from exc
