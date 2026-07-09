"""Redis Pub/Sub bridge for cross-process task event delivery.

EventBus is an in-process singleton — events published inside a Celery worker
never reach the FastAPI process where NotificationService / WebSocket lives.

This module bridges the gap:

- Celery worker:  ``transition_task()`` calls ``publish_task_event_to_redis()``
                  → writes JSON to ``task_events`` Redis channel
- FastAPI:        ``start_event_bridge_listener()`` subscribes to the channel,
                  reconstructs ``TaskEvent``, publishes to the local EventBus
                  → NotificationService picks it up → WebSocket push
"""
from __future__ import annotations

import asyncio
import contextlib
import json
from datetime import UTC, datetime

import redis.asyncio as aioredis
from loguru import logger

from app.core.config import settings
from app.engine.events import TaskEvent, get_event_bus

# Dedicated Redis connection for pubsub (separate from the shared client
# because a pubsub-subscribed connection cannot run regular commands).
_bridge_redis: aioredis.Redis | None = None
_listener_task: asyncio.Task | None = None
_listener_pubsub = None  # reference for diagnostics
_listener_error: str | None = None  # last error for diagnostics


async def _get_bridge_redis() -> aioredis.Redis:
    """Return a dedicated Redis client for the event bridge.

    socket_timeout=None is critical: redis-py 8+ defaults to 5s which causes
    pubsub.listen() to raise TimeoutError when no messages arrive for 5s.
    """
    global _bridge_redis
    if _bridge_redis is None:
        _bridge_redis = aioredis.from_url(
            settings.REDIS_URL, decode_responses=True, socket_timeout=None,
        )
    return _bridge_redis


async def publish_task_event_to_redis(
    event_type: str,
    task_id: str,
    from_status: str | None,
    to_status: str | None,
    data: dict | None = None,
) -> None:
    """Publish a task event to Redis Pub/Sub (fire-and-forget).

    Safe to call from inside a Celery task.
    Errors are logged but never raised.
    """
    try:
        from app.db.redis import get_redis_client

        redis_client = await get_redis_client()
        payload = json.dumps({
            "event_type": event_type,
            "task_id": task_id,
            "from_status": from_status,
            "to_status": to_status,
            "data": data or {},
            "timestamp": datetime.now(UTC).isoformat(),
        })
        await redis_client.publish("task_events", payload)
        logger.debug("event_bridge_published", channel="task_events", event_type=event_type)
    except Exception as exc:
        logger.warning("event_bridge_publish_failed", error=str(exc))


async def start_event_bridge_listener() -> asyncio.Task:
    """Start a background task that subscribes to Redis ``task_events`` channel."""
    global _listener_task, _listener_pubsub, _listener_error

    async def _listener() -> None:
        global _listener_error
        pubsub = None
        try:
            client = await _get_bridge_redis()
            pubsub = client.pubsub()
            _listener_pubsub = pubsub
            await pubsub.subscribe("task_events")
            logger.info("event_bridge_listener_subscribed", channel="task_events")

            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue
                try:
                    payload = json.loads(message["data"])
                    event = TaskEvent(
                        event_type=payload["event_type"],
                        task_id=payload.get("task_id", ""),
                        from_status=payload.get("from_status"),
                        to_status=payload.get("to_status"),
                        data=payload.get("data", {}),
                    )
                    logger.info(
                        "event_bridge_forwarding",
                        event_type=event.event_type,
                        task_id=event.task_id,
                    )
                    await get_event_bus().publish(event)
                except Exception:
                    logger.opt(exception=True).warning(
                        "event_bridge_message_failed",
                        raw_data=message.get("data"),
                    )
        except asyncio.CancelledError:
            pass  # Normal shutdown
        except Exception as exc:
            # Connection errors during shutdown are expected — not a crash
            _listener_error = f"{type(exc).__name__}: {exc}"
            logger.info("event_bridge_listener_exited", error=str(exc), exc_type=type(exc).__name__)
        finally:
            if pubsub is not None:
                try:
                    await pubsub.unsubscribe("task_events")
                    await pubsub.aclose()
                except Exception:
                    pass

    _listener_task = asyncio.create_task(_listener(), name="event_bridge_listener")
    return _listener_task


async def stop_event_bridge_listener() -> None:
    """Cancel the listener task and close the bridge Redis connection."""
    global _listener_task, _bridge_redis

    # 1. Cancel task FIRST (while connection is still alive)
    if _listener_task is not None and not _listener_task.done():
        _listener_task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await _listener_task
        _listener_task = None

    # 2. Then close connection
    if _bridge_redis is not None:
        await _bridge_redis.aclose()
        _bridge_redis = None
