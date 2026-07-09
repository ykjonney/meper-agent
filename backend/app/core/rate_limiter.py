"""Rate limiter — Redis sliding window for API Key quotas."""
from __future__ import annotations

import time

from loguru import logger

from app.db.redis import get_redis_client

# Key pattern: ratelimit:{api_key_id}:{window_key}
_KEY_PREFIX = "ratelimit"
_WINDOW_TTL = 120  # seconds — auto-cleanup after 2 minutes


async def check_rate_limit(api_key_id: str, limit: int) -> tuple[bool, int, int]:
    """Check if a request is within the rate limit.

    Uses a Redis sorted set as a sliding window counter.
    Each request is scored by its timestamp (microsecond precision).

    Args:
        api_key_id: The API Key ID to check.
        limit: Maximum requests per 60-second window.

    Returns:
        Tuple of (allowed, remaining, reset_timestamp).
        - allowed: True if the request is within the limit.
        - remaining: Number of requests remaining in the current window.
        - reset_timestamp: Unix timestamp when the current window resets.
    """
    redis = await get_redis_client()
    now = time.time()
    window_start = now - 60  # 60-second sliding window
    reset_ts = int(now) + 60  # when the oldest entries expire

    key = f"{_KEY_PREFIX}:{api_key_id}"

    # Use a pipeline for atomicity
    pipe = redis.pipeline()

    # Remove entries outside the window
    pipe.zremrangebyscore(key, 0, window_start)

    # Count current entries
    pipe.zcard(key)

    # Add current request with timestamp as score
    pipe.zadd(key, {f"{now}": now})

    # Set TTL for auto-cleanup
    pipe.expire(key, _WINDOW_TTL)

    results = await pipe.execute()

    # results[0] = removed count, results[1] = count before adding
    current_count = results[1]
    allowed = current_count < limit

    if not allowed:
        # Remove the entry we just added since it exceeded the limit
        await redis.zrem(key, f"{now}")

    remaining = max(0, limit - current_count - (1 if allowed else 0))

    if not allowed:
        logger.info(
            "rate_limit_exceeded",
            api_key_id=api_key_id,
            limit=limit,
            current=current_count,
        )

    return allowed, remaining, reset_ts
