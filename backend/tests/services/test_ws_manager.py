"""Tests for WebSocketConnectionManager."""
import pytest
from unittest.mock import AsyncMock

from app.services.ws_manager import WebSocketConnectionManager


class TestWebSocketConnectionManager:
    def setup_method(self):
        self.manager = WebSocketConnectionManager()

    async def test_connect_adds_connection(self):
        ws = AsyncMock()
        await self.manager.connect("user_1", ws)
        assert "user_1" in self.manager._connections
        assert ws in self.manager._connections["user_1"]

    async def test_connect_multiple_for_same_user(self):
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        await self.manager.connect("user_1", ws1)
        await self.manager.connect("user_1", ws2)
        assert len(self.manager._connections["user_1"]) == 2

    async def test_disconnect_removes_connection(self):
        ws = AsyncMock()
        await self.manager.connect("user_1", ws)
        self.manager.disconnect("user_1", ws)
        assert "user_1" not in self.manager._connections

    async def test_disconnect_keeps_other_connections(self):
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        await self.manager.connect("user_1", ws1)
        await self.manager.connect("user_1", ws2)
        self.manager.disconnect("user_1", ws1)
        assert ws2 in self.manager._connections["user_1"]
        assert ws1 not in self.manager._connections.get("user_1", set())

    async def test_send_to_user(self):
        ws = AsyncMock()
        await self.manager.connect("user_1", ws)
        await self.manager.send_to_user("user_1", {"type": "test", "data": {}})
        ws.send_text.assert_awaited_once()

    async def test_send_to_user_removes_failed_connections(self):
        ws = AsyncMock()
        ws.send_text.side_effect = Exception("connection closed")
        await self.manager.connect("user_1", ws)
        await self.manager.send_to_user("user_1", {"type": "test", "data": {}})
        assert "user_1" not in self.manager._connections

    async def test_send_to_unknown_user_does_nothing(self):
        await self.manager.send_to_user("unknown_user", {"type": "test", "data": {}})

    async def test_broadcast(self):
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        await self.manager.connect("user_1", ws1)
        await self.manager.connect("user_2", ws2)
        await self.manager.broadcast({"type": "test"})
        ws1.send_text.assert_awaited_once()
        ws2.send_text.assert_awaited_once()
