"""Async Redis client (singleton) accessor.

Uses redis.asyncio so all Redis I/O is non-blocking in the
FastAPI async event loop.
"""
import redis.asyncio as aioredis

from app.core.config import settings

_redis_client: aioredis.Redis | None = None


async def get_redis_client() -> aioredis.Redis:
    """Return the process-wide async Redis client (lazy-initialized)."""
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(
            settings.REDIS_URL, decode_responses=True
        )
    return _redis_client


async def close_redis_client() -> None:
    """Close the Redis client (call on app shutdown)."""
    global _redis_client
    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None
