"""WebSocket endpoint for real-time notifications and task status updates."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from loguru import logger

from app.core.security import decode_access_token
from app.services.ws_manager import get_ws_manager

router = APIRouter(tags=["websocket"])

HEARTBEAT_INTERVAL = 30  # seconds


def verify_ws_token(token: str) -> str | None:
    """Verify JWT token from query param. Returns user_id or None."""
    payload = decode_access_token(token)
    if payload is None:
        return None
    return payload.get("sub")


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str = ""):
    """WebSocket connection for real-time updates.

    Auth: token passed as query parameter `?token=xxx`.
    """
    user_id = verify_ws_token(token)
    if user_id is None:
        await websocket.close(code=4001, reason="Authentication failed")
        return

    manager = get_ws_manager()
    await manager.connect(user_id, websocket)
    logger.info("ws_client_connected", user_id=user_id)

    try:
        heartbeat_task = asyncio.create_task(
            _heartbeat_loop(websocket, user_id)
        )

        while True:
            data = await websocket.receive_text()
            logger.debug("ws_client_message", user_id=user_id, data=data[:100])

    except WebSocketDisconnect:
        logger.info("ws_client_disconnected", user_id=user_id)
    except Exception as e:
        logger.warning("ws_error", user_id=user_id, error=str(e))
    finally:
        heartbeat_task.cancel()
        manager.disconnect(user_id, websocket)


async def _heartbeat_loop(ws: WebSocket, user_id: str) -> None:
    """Send periodic ping messages to keep the connection alive."""
    while True:
        await asyncio.sleep(HEARTBEAT_INTERVAL)
        try:
            await ws.send_text('{"type": "ping"}')
        except Exception:
            logger.debug("ws_heartbeat_failed", user_id=user_id)
            break
