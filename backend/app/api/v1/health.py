"""Health check endpoint - no auth required."""
from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health", summary="Liveness/readiness probe")
async def health_check() -> dict[str, str]:
    """Return 200 OK if the process is running."""
    return {"status": "ok"}


@router.get("/health/debug/event-bridge", summary="Event bridge diagnostics")
async def event_bridge_debug() -> dict:
    """Check event bridge listener status and test Redis pub/sub."""
    from app.services import event_bridge

    task = event_bridge._listener_task
    task_info = "not_started"
    if task is not None:
        task_info = "running" if not task.done() else f"done({task.exception()})"

    # Pubsub subscription state
    pubsub = event_bridge._listener_pubsub
    pubsub_info = "no_ref"
    if pubsub is not None:
        pubsub_info = {
            "channels": list(pubsub.channels.keys()),
            "patterns": list(pubsub.patterns.keys()),
            "subscribed": pubsub.subscribed,
        }

    # Test Redis connectivity
    redis_ok = False
    try:
        client = await event_bridge._get_bridge_redis()
        await client.ping()
        redis_ok = True
    except Exception as e:
        redis_ok = str(e)

    return {
        "listener_task": task_info,
        "listener_error": event_bridge._listener_error,
        "pubsub": pubsub_info,
        "bridge_redis_ok": redis_ok,
        "redis_url": event_bridge.settings.REDIS_URL,
    }


@router.post("/health/debug/event-bridge/test", summary="Test event bridge pub/sub")
async def event_bridge_test() -> dict:
    """Publish a test message to Redis and check if the bridge listener picks it up."""
    import json

    from app.services import event_bridge

    client = await event_bridge._get_bridge_redis()
    import datetime

    payload = json.dumps({
        "event_type": "task.completed",
        "task_id": "debug_test",
        "from_status": "running",
        "to_status": "completed",
        "data": {},
        "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
    })
    receivers = await client.publish("task_events", payload)
    return {"published": True, "receivers": receivers, "channel": "task_events"}
