"""API Key call statistics — tracking and aggregation via Redis."""
from __future__ import annotations

import time

from loguru import logger

from app.db.redis import get_redis_client

# Redis key patterns
_STATS_PREFIX = "api_key_stats"
_STATS_TTL = 86400 * 30  # 30 days


async def record_request(
    api_key_id: str,
    endpoint: str,
    status_code: int,
) -> None:
    """Record an API Key request for statistics.

    Uses Redis hashes for efficient aggregation:
    - api_key_stats:{id}:total — total request count
    - api_key_stats:{id}:endpoints — per-endpoint counts
    - api_key_stats:{id}:success — success count (2xx)
    - api_key_stats:{id}:failed — failed count (4xx/5xx)
    - api_key_stats:{id}:last_used — last request timestamp
    """
    redis = await get_redis_client()
    prefix = f"{_STATS_PREFIX}:{api_key_id}"

    pipe = redis.pipeline()
    pipe.hincrby(prefix, "total_requests", 1)
    pipe.hincrby(prefix, f"endpoint:{endpoint}", 1)

    if 200 <= status_code < 300:
        pipe.hincrby(prefix, "successful", 1)
    else:
        pipe.hincrby(prefix, "failed", 1)

    pipe.hset(prefix, "last_used_at", str(int(time.time())))
    pipe.expire(prefix, _STATS_TTL)

    try:
        await pipe.execute()
    except Exception as exc:
        logger.warning("api_key_stats_record_error", error=str(exc))


async def get_stats(api_key_id: str) -> dict:
    """Get aggregated statistics for an API Key.

    Returns:
        Dict with total_requests, successful, failed, by_endpoint, last_used_at.
    """
    redis = await get_redis_client()
    prefix = f"{_STATS_PREFIX}:{api_key_id}"

    data = await redis.hgetall(prefix)
    if not data:
        return {
            "api_key_id": api_key_id,
            "total_requests": 0,
            "successful": 0,
            "failed": 0,
            "by_endpoint": {},
            "last_used_at": None,
        }

    by_endpoint = {}
    for key, value in data.items():
        if key.startswith("endpoint:"):
            endpoint_name = key[len("endpoint:"):]
            by_endpoint[endpoint_name] = int(value)

    last_used = data.get("last_used_at")
    last_used_iso = None
    if last_used:
        from datetime import UTC, datetime

        last_used_iso = datetime.fromtimestamp(int(last_used), tz=UTC).isoformat()

    return {
        "api_key_id": api_key_id,
        "total_requests": int(data.get("total_requests", 0)),
        "successful": int(data.get("successful", 0)),
        "failed": int(data.get("failed", 0)),
        "by_endpoint": by_endpoint,
        "last_used_at": last_used_iso,
    }
