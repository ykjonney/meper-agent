"""Redis cache layer for API Key lookups.

Caches ``key_prefix → api_key document`` mappings so that authentication
does not hit MongoDB on every request.
"""
import json

from loguru import logger

from app.db.redis import get_redis_client

_CACHE_PREFIX = "apikey:prefix:"
_CACHE_TTL = 600  # 10 minutes


async def cache_api_key_doc(key_prefix: str, doc: dict) -> None:
    """Cache an API Key document by its prefix."""
    try:
        redis = await get_redis_client()
        await redis.set(
            f"{_CACHE_PREFIX}{key_prefix}",
            json.dumps(doc, default=str),
            ex=_CACHE_TTL,
        )
    except Exception:
        logger.debug("api_key_cache_set_failed", key_prefix=key_prefix)


async def get_cached_api_key_doc(key_prefix: str) -> dict | None:
    """Retrieve a cached API Key document by prefix. Returns None on miss."""
    try:
        redis = await get_redis_client()
        raw = await redis.get(f"{_CACHE_PREFIX}{key_prefix}")
        if raw is not None:
            return json.loads(raw)
    except Exception:
        logger.debug("api_key_cache_get_failed", key_prefix=key_prefix)
    return None


async def invalidate_api_key_cache(key_prefix: str) -> None:
    """Remove a cached API Key entry (on revoke/update)."""
    try:
        redis = await get_redis_client()
        await redis.delete(f"{_CACHE_PREFIX}{key_prefix}")
    except Exception:
        logger.debug("api_key_cache_invalidate_failed", key_prefix=key_prefix)
