"""MongoDBSaver singleton for LangGraph checkpoint persistence.

Replaces the placeholder ``get_checkpointer`` with a real implementation
that returns a ``langgraph.checkpoint.mongodb.MongoDBSaver`` instance
backed by the application's primary MongoDB database.

Uses the underlying synchronous PyMongo ``MongoClient`` via Motor's
``.delegate`` property so that both async (Motor) and sync (LangGraph
checkpointer) operations share the same connection pool.
"""
from __future__ import annotations

from langgraph.checkpoint.mongodb import MongoDBSaver

from app.core.config import settings
from app.db.mongodb import get_mongodb_client

_saver: MongoDBSaver | None = None


def get_checkpointer() -> MongoDBSaver:
    """Return a shared MongoDBSaver singleton.

    The underlying connection is lazily created on first call and
    re-used for the lifetime of the process.
    """
    global _saver  # noqa: PLW0603
    if _saver is None:
        sync_client = get_mongodb_client().delegate
        _saver = MongoDBSaver(
            client=sync_client,
            db_name=settings.MONGODB_DB_NAME,
        )
    return _saver
