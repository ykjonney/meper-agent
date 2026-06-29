"""WebSocket connection manager — tracks per-user connections and dispatches messages."""
from __future__ import annotations

import json

from fastapi import WebSocket
from loguru import logger


class WebSocketConnectionManager:
    """Manages WebSocket connections indexed by user_id.

    A single user may have multiple connections (multi-tab / multi-device).
    """

    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = {}

    async def connect(self, user_id: str, ws: WebSocket) -> None:
        """Register a new WebSocket connection for a user."""
        if user_id not in self._connections:
            self._connections[user_id] = set()
        self._connections[user_id].add(ws)
        logger.debug("ws_connected", user_id=user_id, total=len(self._connections[user_id]))

    def disconnect(self, user_id: str, ws: WebSocket) -> None:
        """Remove a WebSocket connection. Cleans up empty user entries."""
        conns = self._connections.get(user_id)
        if conns:
            conns.discard(ws)
            if not conns:
                del self._connections[user_id]
        logger.debug("ws_disconnected", user_id=user_id)

    async def send_to_user(self, user_id: str, message: dict) -> None:
        """Send a JSON message to all connections of a specific user."""
        conns = self._connections.get(user_id)
        if not conns:
            return

        text = json.dumps(message, ensure_ascii=False)
        failed: list[WebSocket] = []

        for ws in conns:
            try:
                await ws.send_text(text)
            except Exception:
                failed.append(ws)

        for ws in failed:
            self.disconnect(user_id, ws)

    async def broadcast(self, message: dict) -> None:
        """Send a JSON message to all connected users."""
        text = json.dumps(message, ensure_ascii=False)
        for user_id, conns in list(self._connections.items()):
            failed: list[WebSocket] = []
            for ws in conns:
                try:
                    await ws.send_text(text)
                except Exception:
                    failed.append(ws)
            for ws in failed:
                self.disconnect(user_id, ws)


# Module-level singleton
_manager: WebSocketConnectionManager | None = None


def get_ws_manager() -> WebSocketConnectionManager:
    """Return the process-level WebSocketConnectionManager singleton."""
    global _manager
    if _manager is None:
        _manager = WebSocketConnectionManager()
    return _manager
