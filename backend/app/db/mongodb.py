"""Async MongoDB client (singleton) and database accessor.

Uses Motor (async PyMongo) so all DB I/O is non-blocking in the
FastAPI async event loop.
"""
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.core.config import settings

_client: AsyncIOMotorClient | None = None


def get_mongodb_client() -> AsyncIOMotorClient:
    """Return the process-wide async MongoDB client (lazy-initialized).

    ``tz_aware=True`` ensures datetimes read back from MongoDB carry UTC
    timezone info (``+00:00``). Without it, PyMongo returns naive UTC
    datetimes whose ``isoformat()`` lacks a zone indicator, so the frontend
    (JS ``new Date()``) misinterprets them as local time — shifting every
    timestamp by the user's UTC offset (e.g. -8h for Asia/Shanghai).
    """
    global _client
    if _client is None:
        _client = AsyncIOMotorClient(settings.MONGODB_URI, tz_aware=True)
    return _client


def get_database() -> AsyncIOMotorDatabase:
    """Return the configured application database."""
    return get_mongodb_client()[settings.MONGODB_DB_NAME]


async def close_mongodb_client() -> None:
    """Close the MongoDB client (call on app shutdown)."""
    global _client
    if _client is not None:
        _client.close()
        _client = None
