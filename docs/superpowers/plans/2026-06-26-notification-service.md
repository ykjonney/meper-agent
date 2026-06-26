# 通知提醒服务实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 WebSocket 实时推送 + MongoDB 通知持久化，替换前端所有 Task 状态轮询。

**Architecture:** EventBus 注册通配符 handler，收到 task 事件后通过 WebSocketConnectionManager 定向推送给 `created_by` 用户。特定事件（failed/waiting_human/completed）同时写入 MongoDB 持久化。前端通过 WebSocket 接收 `task_status` 刷新 TanStack Query，接收 `notification` 更新通知中心。

**Tech Stack:** FastAPI WebSocket, MongoDB (Motor), EventBus, Zustand, TanStack Query

**Spec:** `docs/superpowers/specs/2026-06-26-notification-service-design.md`

---

## 文件结构

### 后端新建文件

| 文件 | 职责 |
|---|---|
| `backend/app/models/notification.py` | Notification MongoDB 模型 |
| `backend/app/schemas/notification.py` | Notification API request/response schemas |
| `backend/app/services/notification_repo.py` | Notification CRUD 仓库 |
| `backend/app/services/ws_manager.py` | WebSocket 连接管理器 |
| `backend/app/services/notification_service.py` | EventBus → WS 桥接服务 |
| `backend/app/api/v1/notifications.py` | 通知 REST API |
| `backend/app/api/v1/ws.py` | WebSocket 端点 |

### 后端修改文件

| 文件 | 修改内容 |
|---|---|
| `backend/app/api/v1/router.py` | 注册 notifications + ws 路由 |
| `backend/app/db/indexes.py` | 添加 notifications 集合索引 |
| `backend/app/main.py` | lifespan 中初始化 NotificationService |

### 前端新建文件

| 文件 | 职责 |
|---|---|
| `frontend/src/services/notifications-api.ts` | 通知 REST API + query keys |
| `frontend/src/hooks/use-task-realtime.ts` | WS 事件 → TanStack Query invalidate |
| `frontend/src/components/notification-center.tsx` | 通知下拉面板 + badge |

### 前端修改文件

| 文件 | 修改内容 |
|---|---|
| `frontend/src/lib/ws-client.ts` | 替换空壳为完整 WebSocket 客户端 |
| `frontend/src/stores/notification-store.ts` | 替换占位为完整通知 store |
| `frontend/src/features/layout/header.tsx` | 集成 NotificationCenter |
| `frontend/src/pages/tasks-page.tsx` | 移除所有 refetchInterval 轮询 |
| `frontend/src/pages/workflow-detail-page.tsx` | 移除 pollTaskStatus 轮询 |
| `frontend/src/App.tsx` | 挂载 useTaskRealtime + wsClient 生命周期 |

---

### Task 1: Notification 数据模型 + Schema

**Files:**
- Create: `backend/app/models/notification.py`
- Create: `backend/app/schemas/notification.py`
- Test: `backend/tests/models/test_notification.py`

- [ ] **Step 1: 写 Notification model 测试**

```python
# backend/tests/models/test_notification.py
"""Tests for Notification model."""
from app.models.notification import Notification, NotificationKind


class TestNotificationModel:
    def test_create_notification_with_defaults(self):
        n = Notification(
            user_id="user_abc",
            kind=NotificationKind.TASK_COMPLETED,
            title="任务完成",
            body="Workflow「测试」已完成",
        )
        assert n.id.startswith("notif_")
        assert n.read is False
        assert n.related_task_id is None
        assert n.related_workflow_id is None

    def test_create_notification_with_all_fields(self):
        n = Notification(
            user_id="user_abc",
            kind=NotificationKind.TASK_FAILED,
            title="任务失败",
            body="节点 LLM 超时",
            related_task_id="task_xxx",
            related_workflow_id="wf_yyy",
        )
        assert n.kind == NotificationKind.TASK_FAILED
        assert n.related_task_id == "task_xxx"

    def test_notification_kind_values(self):
        assert NotificationKind.TASK_FAILED == "task_failed"
        assert NotificationKind.TASK_WAITING_HUMAN == "task_waiting_human"
        assert NotificationKind.TASK_COMPLETED == "task_completed"

    def test_to_mongo_dict(self):
        n = Notification(
            user_id="user_abc",
            kind=NotificationKind.TASK_COMPLETED,
            title="任务完成",
            body="test",
        )
        d = n.model_dump(by_alias=True)
        assert "_id" in d
        assert d["user_id"] == "user_abc"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && uv run pytest tests/models/test_notification.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.models.notification'`

- [ ] **Step 3: 实现 Notification model**

```python
# backend/app/models/notification.py
"""Notification data model for MongoDB — persistent user notifications."""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from app.models.base import generate_id, utc_now


class NotificationKind(StrEnum):
    """Types of notifications that can be created."""

    TASK_FAILED = "task_failed"
    TASK_WAITING_HUMAN = "task_waiting_human"
    TASK_COMPLETED = "task_completed"


class Notification(BaseModel):
    """MongoDB Notification document.

    Follows the same pattern as Task — raw Pydantic model,
    serialized to dict for MongoDB insertion/update.
    """

    id: str = Field(default_factory=lambda: generate_id("notif"), alias="_id")
    user_id: str = Field(..., max_length=100)
    kind: NotificationKind
    title: str = Field(..., max_length=200)
    body: str = Field(default="", max_length=1000)
    related_task_id: str | None = Field(default=None, max_length=100)
    related_workflow_id: str | None = Field(default=None, max_length=100)
    read: bool = False
    created_at: datetime = Field(default_factory=utc_now)

    model_config = {"populate_by_name": True}
```

- [ ] **Step 4: 实现 Notification schemas**

```python
# backend/app/schemas/notification.py
"""API schemas for notification endpoints."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from app.models.notification import NotificationKind


class NotificationResponse(BaseModel):
    """Single notification in API responses."""

    id: str
    user_id: str
    kind: NotificationKind
    title: str
    body: str
    related_task_id: str | None = None
    related_workflow_id: str | None = None
    read: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class NotificationListResponse(BaseModel):
    """Paginated notification list response."""

    total: int
    page: int
    page_size: int
    items: list[NotificationResponse]


class UnreadCountResponse(BaseModel):
    """Unread notification count."""

    count: int
```

- [ ] **Step 5: 运行测试确认通过**

Run: `cd backend && uv run pytest tests/models/test_notification.py -v`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add backend/app/models/notification.py backend/app/schemas/notification.py backend/tests/models/test_notification.py
git commit -m "feat(notification): add Notification model and API schemas"
```

---

### Task 2: Notification Repository

**Files:**
- Create: `backend/app/services/notification_repo.py`
- Test: `backend/tests/services/test_notification_repo.py`

- [ ] **Step 1: 写 NotificationRepository 测试**

```python
# backend/tests/services/test_notification_repo.py
"""Tests for NotificationRepository."""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.models.notification import Notification, NotificationKind
from app.services.notification_repo import NotificationRepository


@pytest.fixture
def mock_db():
    """Create a mock database with collection."""
    db = MagicMock()
    collection = AsyncMock()
    db.__getitem__ = MagicMock(return_value=collection)
    return db, collection


class TestNotificationRepository:
    async def test_insert(self, mock_db):
        db, collection = mock_db
        repo = NotificationRepository(db)
        notif = Notification(
            user_id="user_abc",
            kind=NotificationKind.TASK_FAILED,
            title="失败",
            body="测试",
        )
        collection.insert_one.return_value = MagicMock(inserted_id=notif.id)
        result = await repo.insert(notif)
        assert result == notif
        collection.insert_one.assert_awaited_once()

    async def test_list_by_user(self, mock_db):
        db, collection = mock_db
        repo = NotificationRepository(db)

        notif = Notification(
            user_id="user_abc",
            kind=NotificationKind.TASK_COMPLETED,
            title="完成",
            body="测试",
        )
        collection.find.return_value.sort.return_value.skip.return_value.limit.return_value.to_list = AsyncMock(
            return_value=[notif.model_dump(by_alias=True)]
        )
        collection.count_documents.return_value = 1

        result = await repo.list_by_user("user_abc", page=1, page_size=20)
        assert result["total"] == 1
        assert len(result["items"]) == 1

    async def test_count_unread(self, mock_db):
        db, collection = mock_db
        repo = NotificationRepository(db)
        collection.count_documents.return_value = 5
        count = await repo.count_unread("user_abc")
        assert count == 5
        collection.count_documents.assert_awaited_once_with({"user_id": "user_abc", "read": False})

    async def test_mark_read(self, mock_db):
        db, collection = mock_db
        repo = NotificationRepository(db)
        collection.update_one.return_value = MagicMock(modified_count=1)
        await repo.mark_read("user_abc", "notif_xxx")
        collection.update_one.assert_awaited_once()

    async def test_mark_all_read(self, mock_db):
        db, collection = mock_db
        repo = NotificationRepository(db)
        collection.update_many.return_value = MagicMock(modified_count=3)
        await repo.mark_all_read("user_abc")
        collection.update_many.assert_awaited_once()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && uv run pytest tests/services/test_notification_repo.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.notification_repo'`

- [ ] **Step 3: 实现 NotificationRepository**

```python
# backend/app/services/notification_repo.py
"""Notification CRUD repository — MongoDB persistence layer."""
from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.pagination import calc_skip
from app.models.notification import Notification

COLLECTION = "notifications"


class NotificationRepository:
    """MongoDB repository for Notification documents."""

    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._db = db

    def _collection(self):
        return self._db[COLLECTION]

    async def insert(self, notification: Notification) -> Notification:
        """Insert a new notification."""
        doc = notification.model_dump(by_alias=True)
        await self._collection().insert_one(doc)
        return notification

    async def list_by_user(
        self,
        user_id: str,
        *,
        page: int = 1,
        page_size: int = 20,
        read: bool | None = None,
        kind: str | None = None,
    ) -> dict:
        """List notifications for a user with pagination and optional filters."""
        query: dict = {"user_id": user_id}
        if read is not None:
            query["read"] = read
        if kind is not None:
            query["kind"] = kind

        total = await self._collection().count_documents(query)
        cursor = (
            self._collection()
            .find(query)
            .sort("created_at", -1)
            .skip(calc_skip(page, page_size))
            .limit(page_size)
        )
        items = await cursor.to_list(length=page_size)
        return {"total": total, "page": page, "page_size": page_size, "items": items}

    async def count_unread(self, user_id: str) -> int:
        """Count unread notifications for a user."""
        return await self._collection().count_documents({"user_id": user_id, "read": False})

    async def mark_read(self, user_id: str, notification_id: str) -> None:
        """Mark a single notification as read."""
        await self._collection().update_one(
            {"_id": notification_id, "user_id": user_id},
            {"$set": {"read": True}},
        )

    async def mark_all_read(self, user_id: str) -> None:
        """Mark all notifications as read for a user."""
        await self._collection().update_many(
            {"user_id": user_id, "read": False},
            {"$set": {"read": True}},
        )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && uv run pytest tests/services/test_notification_repo.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/services/notification_repo.py backend/tests/services/test_notification_repo.py
git commit -m "feat(notification): add NotificationRepository with CRUD operations"
```

---

### Task 3: WebSocket ConnectionManager

**Files:**
- Create: `backend/app/services/ws_manager.py`
- Test: `backend/tests/services/test_ws_manager.py`

- [ ] **Step 1: 写 WebSocketConnectionManager 测试**

```python
# backend/tests/services/test_ws_manager.py
"""Tests for WebSocketConnectionManager."""
import pytest
from unittest.mock import AsyncMock, MagicMock

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
        # Should not raise, should clean up the failed connection
        await self.manager.send_to_user("user_1", {"type": "test", "data": {}})
        assert "user_1" not in self.manager._connections

    async def test_send_to_unknown_user_does_nothing(self):
        # Should not raise
        await self.manager.send_to_user("unknown_user", {"type": "test", "data": {}})

    async def test_broadcast(self):
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        await self.manager.connect("user_1", ws1)
        await self.manager.connect("user_2", ws2)
        await self.manager.broadcast({"type": "test"})
        ws1.send_text.assert_awaited_once()
        ws2.send_text.assert_awaited_once()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && uv run pytest tests/services/test_ws_manager.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 WebSocketConnectionManager**

```python
# backend/app/services/ws_manager.py
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

        # Clean up broken connections
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
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd backend && uv run pytest tests/services/test_ws_manager.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/services/ws_manager.py backend/tests/services/test_ws_manager.py
git commit -m "feat(notification): add WebSocketConnectionManager with per-user dispatch"
```

---

### Task 4: WebSocket 端点

**Files:**
- Create: `backend/app/api/v1/ws.py`
- Test: `backend/tests/api/test_ws.py`

- [ ] **Step 1: 写 WebSocket 端点测试**

```python
# backend/tests/api/test_ws.py
"""Tests for WebSocket endpoint."""
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


class TestWebSocketEndpoint:
    async def test_ws_connect_with_valid_token(self, client):
        """Test that WebSocket connection accepts token via query param."""
        with patch("app.api.v1.ws.verify_ws_token") as mock_verify:
            mock_verify.return_value = "user_abc"
            with client.websocket_connect("/api/v1/ws?token=fake_token") as ws:
                # Should receive a ping within a reasonable time
                # For now just verify the connection was accepted
                pass

    async def test_ws_connect_rejects_invalid_token(self, client):
        """Test that invalid token is rejected."""
        with patch("app.api.v1.ws.verify_ws_token") as mock_verify:
            mock_verify.return_value = None
            with pytest.raises(Exception):
                with client.websocket_connect("/api/v1/ws?token=bad_token") as ws:
                    pass
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && uv run pytest tests/api/test_ws.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 WebSocket 端点**

```python
# backend/app/api/v1/ws.py
"""WebSocket endpoint for real-time notifications and task status updates."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from loguru import logger

from app.core.security import decode_access_token
from app.services.ws_manager import get_ws_manager

router = APIRouter(tags=["websocket"])

HEARTBEAT_INTERVAL = 30  # seconds
HEARTBEAT_TIMEOUT = 60   # seconds


def verify_ws_token(token: str) -> str | None:
    """Verify JWT token from query param. Returns user_id or None."""
    payload = decode_access_token(token)
    if payload is None:
        return None
    if payload.get("type") != "access":
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
        # Start heartbeat sender
        heartbeat_task = asyncio.create_task(
            _heartbeat_loop(websocket, user_id)
        )

        # Listen for client messages (pong responses)
        while True:
            data = await websocket.receive_text()
            # Client messages are not critical, just log
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
```

- [ ] **Step 4: 确认 `decode_access_token` 是否存在**

检查 `backend/app/core/security.py` 是否有 `decode_access_token` 函数。如果不存在，需要添加一个辅助函数来解码 JWT token（不依赖 FastAPI Header 的方式）。

查看 security.py 中的实现，`get_current_user` 从 Header 提取 token 后调用内部的 JWT 解码逻辑。需要提取出一个可复用的 `decode_access_token(token: str) -> dict | None` 函数。

如果 `decode_access_token` 不存在，在 `backend/app/core/security.py` 中添加：

```python
def decode_access_token(token: str) -> dict | None:
    """Decode and validate a JWT access token. Returns payload dict or None."""
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        if payload.get("type") != "access":
            return None
        return payload
    except Exception:
        return None
```

- [ ] **Step 5: 运行测试确认通过**

Run: `cd backend && uv run pytest tests/api/test_ws.py -v`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add backend/app/api/v1/ws.py backend/tests/api/test_ws.py
# 如果修改了 security.py:
git add backend/app/core/security.py
git commit -m "feat(notification): add WebSocket endpoint with JWT auth and heartbeat"
```

---

### Task 5: NotificationService（EventBus 桥接）

**Files:**
- Create: `backend/app/services/notification_service.py`
- Test: `backend/tests/services/test_notification_service.py`

- [ ] **Step 1: 写 NotificationService 测试**

```python
# backend/tests/services/test_notification_service.py
"""Tests for NotificationService — EventBus bridge."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from dataclasses import dataclass

from app.engine.events import TaskEvent
from app.models.notification import NotificationKind
from app.services.notification_service import NotificationService


@pytest.fixture
def mock_deps():
    event_bus = MagicMock()
    ws_manager = AsyncMock()
    notification_repo = AsyncMock()
    task_service = AsyncMock()

    service = NotificationService(
        event_bus=event_bus,
        ws_manager=ws_manager,
        notification_repo=notification_repo,
        task_service=task_service,
    )
    return service, event_bus, ws_manager, notification_repo, task_service


class TestNotificationService:
    def test_register_subscribes_to_event_bus(self, mock_deps):
        service, event_bus, *_ = mock_deps
        service.register()
        event_bus.subscribe.assert_called_once_with("*", service._on_event)

    async def test_task_event_pushes_status_update(self, mock_deps):
        service, _, ws_manager, _, task_service = mock_deps

        # Mock task lookup
        mock_task = MagicMock()
        mock_task.created_by = "user_abc"
        mock_task.workflow_id = "wf_xxx"
        task_service.get_task.return_value = mock_task

        event = TaskEvent(
            event_type="task.running",
            task_id="task_123",
            from_status="pending",
            to_status="running",
        )
        await service._on_event(event)

        ws_manager.send_to_user.assert_awaited_once()
        call_args = ws_manager.send_to_user.call_args
        assert call_args[0][0] == "user_abc"
        assert call_args[0][1]["type"] == "task_status"
        assert call_args[0][1]["data"]["task_id"] == "task_123"
        assert call_args[0][1]["data"]["status"] == "running"

    async def test_non_task_event_is_ignored(self, mock_deps):
        service, _, ws_manager, _, _ = mock_deps

        event = TaskEvent(event_type="workflow.started", task_id="")
        await service._on_event(event)

        ws_manager.send_to_user.assert_not_awaited()

    async def test_task_failed_creates_notification(self, mock_deps):
        service, _, ws_manager, notification_repo, task_service = mock_deps

        mock_task = MagicMock()
        mock_task.created_by = "user_abc"
        mock_task.workflow_id = "wf_xxx"
        mock_task.id = "task_123"
        task_service.get_task.return_value = mock_task

        event = TaskEvent(
            event_type="task.failed",
            task_id="task_123",
            from_status="running",
            to_status="failed",
        )
        await service._on_event(event)

        # Should push task_status AND notification
        assert ws_manager.send_to_user.await_count == 2
        notification_repo.insert.assert_awaited_once()

        # Check notification kind
        notif = notification_repo.insert.call_args[0][0]
        assert notif.kind == NotificationKind.TASK_FAILED

    async def test_task_completed_creates_notification(self, mock_deps):
        service, _, ws_manager, notification_repo, task_service = mock_deps

        mock_task = MagicMock()
        mock_task.created_by = "user_abc"
        mock_task.workflow_id = "wf_xxx"
        mock_task.id = "task_123"
        task_service.get_task.return_value = mock_task

        event = TaskEvent(
            event_type="task.completed",
            task_id="task_123",
            from_status="running",
            to_status="completed",
        )
        await service._on_event(event)

        notif = notification_repo.insert.call_args[0][0]
        assert notif.kind == NotificationKind.TASK_COMPLETED

    async def test_task_waiting_human_creates_notification(self, mock_deps):
        service, _, ws_manager, notification_repo, task_service = mock_deps

        mock_task = MagicMock()
        mock_task.created_by = "user_abc"
        mock_task.workflow_id = "wf_xxx"
        mock_task.id = "task_123"
        task_service.get_task.return_value = mock_task

        event = TaskEvent(
            event_type="task.waiting_human",
            task_id="task_123",
            from_status="running",
            to_status="waiting_human",
        )
        await service._on_event(event)

        notif = notification_repo.insert.call_args[0][0]
        assert notif.kind == NotificationKind.TASK_WAITING_HUMAN

    async def test_task_running_does_not_create_notification(self, mock_deps):
        service, _, _, notification_repo, task_service = mock_deps

        mock_task = MagicMock()
        mock_task.created_by = "user_abc"
        mock_task.workflow_id = "wf_xxx"
        task_service.get_task.return_value = mock_task

        event = TaskEvent(
            event_type="task.running",
            task_id="task_123",
            from_status="pending",
            to_status="running",
        )
        await service._on_event(event)

        notification_repo.insert.assert_not_awaited()

    async def test_empty_created_by_skips_push(self, mock_deps):
        service, _, ws_manager, notification_repo, task_service = mock_deps

        mock_task = MagicMock()
        mock_task.created_by = ""
        task_service.get_task.return_value = mock_task

        event = TaskEvent(
            event_type="task.running",
            task_id="task_123",
            from_status="pending",
            to_status="running",
        )
        await service._on_event(event)

        ws_manager.send_to_user.assert_not_awaited()
        notification_repo.insert.assert_not_awaited()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && uv run pytest tests/services/test_notification_service.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 NotificationService**

```python
# backend/app/services/notification_service.py
"""NotificationService — bridges EventBus task events to WebSocket pushes and persistent notifications."""
from __future__ import annotations

from loguru import logger

from app.engine.events import Event, TaskEvent, get_event_bus
from app.models.notification import Notification, NotificationKind
from app.services.notification_repo import NotificationRepository
from app.services.task_service import TaskService
from app.services.ws_manager import WebSocketConnectionManager

# Task events that trigger persistent notifications
NOTIFY_EVENTS: dict[str, NotificationKind] = {
    "task.failed": NotificationKind.TASK_FAILED,
    "task.waiting_human": NotificationKind.TASK_WAITING_HUMAN,
    "task.completed": NotificationKind.TASK_COMPLETED,
}

# Notification titles per kind
_NOTIFICATION_TITLES: dict[NotificationKind, str] = {
    NotificationKind.TASK_FAILED: "任务执行失败",
    NotificationKind.TASK_WAITING_HUMAN: "任务等待审批",
    NotificationKind.TASK_COMPLETED: "任务执行完成",
}


class NotificationService:
    """Subscribes to EventBus, pushes task_status to WS, persists notifications."""

    def __init__(
        self,
        event_bus=None,
        ws_manager: WebSocketConnectionManager | None = None,
        notification_repo: NotificationRepository | None = None,
        task_service=None,
    ) -> None:
        self._event_bus = event_bus or get_event_bus()
        self._ws_manager = ws_manager
        self._notification_repo = notification_repo
        self._task_service = task_service

    def _get_ws_manager(self) -> WebSocketConnectionManager:
        if self._ws_manager is None:
            from app.services.ws_manager import get_ws_manager
            self._ws_manager = get_ws_manager()
        return self._ws_manager

    def _get_repo(self) -> NotificationRepository:
        if self._notification_repo is None:
            from app.db.mongodb import get_database
            self._notification_repo = NotificationRepository(get_database())
        return self._notification_repo

    def _get_task_service(self):
        if self._task_service is None:
            self._task_service = TaskService
        return self._task_service

    def register(self) -> None:
        """Subscribe to all EventBus events and filter for task-related ones."""
        self._event_bus.subscribe("*", self._on_event, handler_name="notification_service")
        logger.info("notification_service_registered")

    async def _on_event(self, event: Event) -> None:
        """Handle an EventBus event — route to task status push / notification creation."""
        # Only handle TaskEvent instances with task-related event types
        if not isinstance(event, TaskEvent):
            return
        if not event.task_id:
            return

        task_service = self._get_task_service()
        task = await task_service.get_task(event.task_id)
        if task is None:
            return

        user_id = task.created_by
        if not user_id:
            return

        ws_manager = self._get_ws_manager()

        # 1. Push task_status to user's WebSocket (transient)
        await ws_manager.send_to_user(user_id, {
            "type": "task_status",
            "data": {
                "task_id": event.task_id,
                "status": event.to_status,
                "from_status": event.from_status,
                "workflow_id": task.workflow_id,
                "updated_at": event.timestamp.isoformat(),
            },
        })

        # 2. If this event warrants a persistent notification
        kind = NOTIFY_EVENTS.get(event.event_type)
        if kind is not None:
            notification = Notification(
                user_id=user_id,
                kind=kind,
                title=_NOTIFICATION_TITLES[kind],
                body=self._build_body(event, task),
                related_task_id=event.task_id,
                related_workflow_id=task.workflow_id,
            )
            await self._get_repo().insert(notification)

            # Push notification to user's WebSocket
            await ws_manager.send_to_user(user_id, {
                "type": "notification",
                "data": notification.model_dump(mode="json"),
            })

    def _build_body(self, event: TaskEvent, task) -> str:
        """Build human-readable notification body from event context."""
        kind = NOTIFY_EVENTS.get(event.event_type)
        if kind == NotificationKind.TASK_FAILED:
            error_msg = ""
            if hasattr(task, "error") and task.error:
                error_msg = task.error.get("error_message", "") if isinstance(task.error, dict) else getattr(task.error, "error_message", "")
            return f"任务 {event.task_id} 执行失败" + (f": {error_msg}" if error_msg else "")
        elif kind == NotificationKind.TASK_WAITING_HUMAN:
            return f"任务 {event.task_id} 等待人工审批"
        elif kind == NotificationKind.TASK_COMPLETED:
            return f"任务 {event.task_id} 已完成"
        return f"任务 {event.task_id} 状态更新"
```

- [ ] **Step 4: 确认 TaskService.get_task 方法存在**

检查 `backend/app/services/task_service.py` 中是否有 `get_task(task_id)` 方法。TaskService 使用静态方法模式，确认方法签名是 `async def get_task(task_id: str)` 或类似。如果方法名不同（如 `find_by_id`），调整 `_on_event` 中的调用。

- [ ] **Step 5: 运行测试确认通过**

Run: `cd backend && uv run pytest tests/services/test_notification_service.py -v`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add backend/app/services/notification_service.py backend/tests/services/test_notification_service.py
git commit -m "feat(notification): add NotificationService bridging EventBus to WebSocket and MongoDB"
```

---

### Task 6: 通知 REST API

**Files:**
- Create: `backend/app/api/v1/notifications.py`
- Test: `backend/tests/api/test_notifications.py`

- [ ] **Step 1: 写通知 API 测试**

```python
# backend/tests/api/test_notifications.py
"""Tests for notification REST API endpoints."""
import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from app.main import app


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    return TestClient(app)


@pytest.fixture
def override_auth():
    """Override get_current_user to return a test user."""
    from app.core.security import get_current_user
    from app.schemas.user import UserResponse

    user = UserResponse(
        id="user_test",
        username="testuser",
        email="test@test.com",
        role="admin",
        permissions=[],
        is_active=True,
    )
    app.dependency_overrides[get_current_user] = lambda: user
    yield user
    app.dependency_overrides.clear()


class TestNotificationAPI:
    async def test_list_notifications(self, client, override_auth):
        with patch("app.api.v1.notifications.NotificationRepository") as MockRepo:
            repo_instance = AsyncMock()
            MockRepo.return_value = repo_instance
            repo_instance.list_by_user.return_value = {
                "total": 0, "page": 1, "page_size": 20, "items": []
            }
            resp = client.get("/api/v1/notifications")
            assert resp.status_code == 200
            data = resp.json()
            assert data["total"] == 0
            assert data["items"] == []

    async def test_unread_count(self, client, override_auth):
        with patch("app.api.v1.notifications.NotificationRepository") as MockRepo:
            repo_instance = AsyncMock()
            MockRepo.return_value = repo_instance
            repo_instance.count_unread.return_value = 5
            resp = client.get("/api/v1/notifications/unread-count")
            assert resp.status_code == 200
            assert resp.json()["count"] == 5

    async def test_mark_read(self, client, override_auth):
        with patch("app.api.v1.notifications.NotificationRepository") as MockRepo:
            repo_instance = AsyncMock()
            MockRepo.return_value = repo_instance
            repo_instance.mark_read.return_value = None
            resp = client.patch("/api/v1/notifications/notif_xxx/read")
            assert resp.status_code == 200

    async def test_mark_all_read(self, client, override_auth):
        with patch("app.api.v1.notifications.NotificationRepository") as MockRepo:
            repo_instance = AsyncMock()
            MockRepo.return_value = repo_instance
            repo_instance.mark_all_read.return_value = None
            resp = client.patch("/api/v1/notifications/read-all")
            assert resp.status_code == 200
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd backend && uv run pytest tests/api/test_notifications.py -v`
Expected: FAIL

- [ ] **Step 3: 实现通知 REST API**

```python
# backend/app/api/v1/notifications.py
"""Notification REST API endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.core.security import get_current_user
from app.db.mongodb import get_database
from app.schemas.notification import NotificationListResponse, UnreadCountResponse
from app.schemas.user import UserResponse
from app.services.notification_repo import NotificationRepository

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=NotificationListResponse)
async def list_notifications(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    read: bool | None = Query(default=None),
    kind: str | None = Query(default=None),
    current_user: UserResponse = Depends(get_current_user),
):
    """List notifications for the current user with pagination."""
    repo = NotificationRepository(get_database())
    result = await repo.list_by_user(
        current_user.id,
        page=page,
        page_size=page_size,
        read=read,
        kind=kind,
    )
    return NotificationListResponse(**result)


@router.get("/unread-count", response_model=UnreadCountResponse)
async def unread_count(
    current_user: UserResponse = Depends(get_current_user),
):
    """Get unread notification count for the current user."""
    repo = NotificationRepository(get_database())
    count = await repo.count_unread(current_user.id)
    return UnreadCountResponse(count=count)


@router.patch("/{notification_id}/read")
async def mark_read(
    notification_id: str,
    current_user: UserResponse = Depends(get_current_user),
):
    """Mark a single notification as read."""
    repo = NotificationRepository(get_database())
    await repo.mark_read(current_user.id, notification_id)
    return {"ok": True}


@router.patch("/read-all")
async def mark_all_read(
    current_user: UserResponse = Depends(get_current_user),
):
    """Mark all notifications as read for the current user."""
    repo = NotificationRepository(get_database())
    await repo.mark_all_read(current_user.id)
    return {"ok": True}
```

- [ ] **Step 4: 注册路由**

在 `backend/app/api/v1/router.py` 中添加：

```python
from app.api.v1.notifications import router as notifications_router
# ...
api_v1_router.include_router(notifications_router)
```

同时在 `router.py` 中也需要注册 ws 路由（在 Task 4 已创建的 ws.py 中）：

```python
from app.api.v1.ws import router as ws_router
# ...
api_v1_router.include_router(ws_router)
```

- [ ] **Step 5: 运行测试确认通过**

Run: `cd backend && uv run pytest tests/api/test_notifications.py -v`
Expected: PASS

- [ ] **Step 6: 添加 MongoDB 索引**

在 `backend/app/db/indexes.py` 中添加 notifications 集合索引（读取现有文件了解索引创建模式后追加）：

```python
# 添加到 indexes.py 的索引初始化逻辑中
await db["notifications"].create_index(
    [("user_id", 1), ("created_at", -1)],
)
await db["notifications"].create_index(
    [("user_id", 1), ("read", 1)],
)
```

- [ ] **Step 7: 在 lifespan 中初始化 NotificationService**

修改 `backend/app/main.py`，在 lifespan 的 startup 部分添加：

```python
# After existing startup code, before yield:
from app.services.notification_service import NotificationService
notification_service = NotificationService()
notification_service.register()
```

- [ ] **Step 8: 提交**

```bash
git add backend/app/api/v1/notifications.py backend/tests/api/test_notifications.py backend/app/api/v1/router.py backend/app/db/indexes.py backend/app/main.py
git commit -m "feat(notification): add notification REST API, register routes and indexes"
```

---

### Task 7: 前端 WebSocket Client

**Files:**
- Modify: `frontend/src/lib/ws-client.ts`

- [ ] **Step 1: 替换空壳 WsClient 实现**

```typescript
// frontend/src/lib/ws-client.ts

type MessageHandler = (data: unknown) => void

const MAX_RECONNECT_DELAY = 30_000
const BASE_RECONNECT_DELAY = 1_000

export class WsClient {
  private ws: WebSocket | null = null
  private reconnectDelay = BASE_RECONNECT_DELAY
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private listeners = new Map<string, Set<MessageHandler>>()
  private disposed = false

  connect(): void {
    if (this.disposed) return
    if (this.ws?.readyState === WebSocket.OPEN) return

    // Import dynamically to avoid circular dependency at module level
    const { useAuthStore } = require('../stores/auth-store')
    const token = useAuthStore.getState().accessToken
    if (!token) return

    const wsBase = import.meta.env.VITE_API_BASE_URL?.replace(/^http/, 'ws') ?? `ws://${window.location.host}`
    const url = `${wsBase}/api/v1/ws?token=${token}`

    this.ws = new WebSocket(url)

    this.ws.onopen = () => {
      this.reconnectDelay = BASE_RECONNECT_DELAY
    }

    this.ws.onmessage = (event: MessageEvent) => {
      try {
        const msg = JSON.parse(event.data)
        if (msg.type === 'ping') {
          this.ws?.send(JSON.stringify({ type: 'pong' }))
          return
        }
        if (msg.type === 'auth_expired') {
          // Token expired — disconnect and let App.tsx handle re-auth
          this.disconnect()
          return
        }
        this.emit(msg.type, msg.data)
      } catch {
        // Ignore malformed messages
      }
    }

    this.ws.onclose = () => {
      this.ws = null
      this.scheduleReconnect()
    }

    this.ws.onerror = () => {
      // onclose will fire after onerror
    }
  }

  on(type: string, handler: MessageHandler): () => void {
    if (!this.listeners.has(type)) {
      this.listeners.set(type, new Set())
    }
    this.listeners.get(type)!.add(handler)
    return () => {
      this.listeners.get(type)?.delete(handler)
    }
  }

  disconnect(): void {
    this.disposed = true
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
    this.ws?.close()
    this.ws = null
  }

  /** Resume the client after disconnect — resets disposed flag. */
  resume(): void {
    this.disposed = false
  }

  get connected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN
  }

  private emit(type: string, data: unknown): void {
    const handlers = this.listeners.get(type)
    if (handlers) {
      for (const handler of handlers) {
        try {
          handler(data)
        } catch {
          // Don't let handler errors break the client
        }
      }
    }
  }

  private scheduleReconnect(): void {
    if (this.disposed) return
    if (this.reconnectTimer) return

    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null
      this.connect()
    }, this.reconnectDelay)

    // Exponential backoff with cap
    this.reconnectDelay = Math.min(this.reconnectDelay * 2, MAX_RECONNECT_DELAY)
  }
}

export const wsClient = new WsClient()
```

- [ ] **Step 2: 确认 Vite 环境变量名**

检查 `frontend/.env` 或 `frontend/vite.config.ts` 中的 API base URL 变量名，确保 `import.meta.env.VITE_API_BASE_URL` 正确。如果不存在此变量，可能需要使用 `window.location` 动态构造。

- [ ] **Step 3: 确认 auth store 中 token 字段名**

检查 `frontend/src/stores/auth-store.ts` 中的 accessToken 字段名（可能是 `accessToken` 或 `token`），确保 `useAuthStore.getState().accessToken` 正确。

- [ ] **Step 4: 提交**

```bash
git add frontend/src/lib/ws-client.ts
git commit -m "feat(notification): implement WebSocket client with auto-reconnect"
```

---

### Task 8: 前端 Notification Store + API Service

**Files:**
- Create: `frontend/src/services/notifications-api.ts`
- Modify: `frontend/src/stores/notification-store.ts`

- [ ] **Step 1: 实现 notifications API service**

```typescript
// frontend/src/services/notifications-api.ts
import apiClient from './api-client'

export interface NotificationItem {
  id: string
  user_id: string
  kind: 'task_failed' | 'task_waiting_human' | 'task_completed'
  title: string
  body: string
  related_task_id: string | null
  related_workflow_id: string | null
  read: boolean
  created_at: string
}

export interface NotificationListResponse {
  total: number
  page: number
  page_size: number
  items: NotificationItem[]
}

export const notificationsApi = {
  list(params?: { page?: number; page_size?: number; read?: boolean; kind?: string }) {
    return apiClient.get<NotificationListResponse>('/notifications', { params }).then((r) => r.data)
  },

  unreadCount() {
    return apiClient.get<{ count: number }>('/notifications/unread-count').then((r) => r.data)
  },

  markRead(id: string) {
    return apiClient.patch(`/notifications/${id}/read`).then((r) => r.data)
  },

  markAllRead() {
    return apiClient.patch('/notifications/read-all').then((r) => r.data)
  },
}

// TanStack Query key factory
export const notificationKeys = {
  all: ['notifications'] as const,
  list: (filters?: Record<string, unknown>) => [...notificationKeys.all, 'list', filters] as const,
  unreadCount: () => [...notificationKeys.all, 'unread-count'] as const,
}
```

- [ ] **Step 2: 替换 notification store**

```typescript
// frontend/src/stores/notification-store.ts
import { create } from 'zustand'
import { notificationsApi, type NotificationItem } from '../services/notifications-api'

interface NotificationState {
  notifications: NotificationItem[]
  unreadCount: number
  loading: boolean

  /** Load initial data from REST API */
  loadFromApi: () => Promise<void>
  /** Load only the unread count */
  loadUnreadCount: () => Promise<void>
  /** Add a notification received via WebSocket */
  addNotification: (notification: NotificationItem) => void
  /** Mark a single notification as read */
  markAsRead: (id: string) => Promise<void>
  /** Mark all notifications as read */
  markAllAsRead: () => Promise<void>
}

export const useNotificationStore = create<NotificationState>((set, get) => ({
  notifications: [],
  unreadCount: 0,
  loading: false,

  loadFromApi: async () => {
    set({ loading: true })
    try {
      const [listResult, countResult] = await Promise.all([
        notificationsApi.list({ page_size: 20 }),
        notificationsApi.unreadCount(),
      ])
      set({
        notifications: listResult.items,
        unreadCount: countResult.count,
        loading: false,
      })
    } catch {
      set({ loading: false })
    }
  },

  loadUnreadCount: async () => {
    try {
      const result = await notificationsApi.unreadCount()
      set({ unreadCount: result.count })
    } catch {
      // Silently ignore
    }
  },

  addNotification: (notification: NotificationItem) => {
    set((state) => ({
      notifications: [notification, ...state.notifications].slice(0, 50),
      unreadCount: state.unreadCount + 1,
    }))
  },

  markAsRead: async (id: string) => {
    // Optimistic update
    set((state) => ({
      notifications: state.notifications.map((n) =>
        n.id === id ? { ...n, read: true } : n,
      ),
      unreadCount: Math.max(0, state.unreadCount - (state.notifications.find((n) => n.id === id && !n.read) ? 1 : 0)),
    }))
    try {
      await notificationsApi.markRead(id)
    } catch {
      // Revert on failure — reload from API
      await get().loadFromApi()
    }
  },

  markAllAsRead: async () => {
    set((state) => ({
      notifications: state.notifications.map((n) => ({ ...n, read: true })),
      unreadCount: 0,
    }))
    try {
      await notificationsApi.markAllRead()
    } catch {
      await get().loadFromApi()
    }
  },
}))
```

- [ ] **Step 3: 提交**

```bash
git add frontend/src/services/notifications-api.ts frontend/src/stores/notification-store.ts
git commit -m "feat(notification): implement notification API service and Zustand store"
```

---

### Task 9: 前端通知中心 UI + Header 集成

**Files:**
- Create: `frontend/src/components/notification-center.tsx`
- Modify: `frontend/src/features/layout/header.tsx`

- [ ] **Step 1: 实现 NotificationCenter 组件**

```tsx
// frontend/src/components/notification-center.tsx
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Badge, Popover, List, Button, Typography, Empty } from 'antd'
import { BellOutlined, CheckOutlined } from '@ant-design/icons'
import { useNotificationStore } from '../stores/notification-store'
import type { NotificationItem } from '../services/notifications-api'

const { Text } = Typography

const KIND_COLORS: Record<string, string> = {
  task_failed: '#EF4444',
  task_waiting_human: '#F59E0B',
  task_completed: '#22C55E',
}

const KIND_LABELS: Record<string, string> = {
  task_failed: '失败',
  task_waiting_human: '待审批',
  task_completed: '已完成',
}

function NotificationItemRow({ item }: { item: NotificationItem }) {
  const navigate = useNavigate()
  const markAsRead = useNotificationStore((s) => s.markAsRead)

  const handleClick = () => {
    if (!item.read) {
      markAsRead(item.id)
    }
    if (item.related_task_id) {
      navigate(`/tasks?highlight=${item.related_task_id}`)
    }
  }

  return (
    <div
      className="px-3 py-2.5 cursor-pointer hover:bg-gray-50 transition-colors border-b border-gray-50 last:border-b-0"
      onClick={handleClick}
    >
      <div className="flex items-start gap-2">
        <span
          className="mt-1.5 w-2 h-2 rounded-full shrink-0"
          style={{ backgroundColor: KIND_COLORS[item.kind] ?? '#94A3B8' }}
        />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <Text strong className="text-sm leading-tight">{item.title}</Text>
            <Text type="secondary" className="text-xs shrink-0">
              {KIND_LABELS[item.kind]}
            </Text>
          </div>
          <Text type="secondary" className="text-xs block truncate mt-0.5">
            {item.body}
          </Text>
          <Text type="secondary" className="text-[11px] mt-1">
            {new Date(item.created_at).toLocaleString()}
          </Text>
        </div>
        {!item.read && (
          <span className="mt-1 w-2 h-2 rounded-full bg-blue-500 shrink-0" />
        )}
      </div>
    </div>
  )
}

export default function NotificationCenter() {
  const [open, setOpen] = useState(false)
  const { notifications, unreadCount, loadFromApi, markAllAsRead } = useNotificationStore()

  useEffect(() => {
    if (open) {
      loadFromApi()
    }
  }, [open, loadFromApi])

  const content = (
    <div className="w-80">
      <div className="flex items-center justify-between px-3 py-2 border-b border-gray-100">
        <Text strong className="text-sm">通知中心</Text>
        {unreadCount > 0 && (
          <Button type="link" size="small" icon={<CheckOutlined />} onClick={() => markAllAsRead()}>
            全部已读
          </Button>
        )}
      </div>
      <div className="max-h-80 overflow-y-auto">
        {notifications.length === 0 ? (
          <Empty description="暂无通知" image={Empty.PRESENTED_IMAGE_SIMPLE} className="py-6" />
        ) : (
          notifications.map((item) => (
            <NotificationItemRow key={item.id} item={item} />
          ))
        )}
      </div>
    </div>
  )

  return (
    <Popover
      content={content}
      trigger="click"
      open={open}
      onOpenChange={setOpen}
      placement="bottomRight"
      arrow={false}
      overlayInnerStyle={{ padding: 0 }}
    >
      <Badge count={unreadCount} size="small" color="#F97316" offset={[-2, 2]}>
        <Button
          type="text"
          icon={<BellOutlined />}
          className="!text-[#64748B] hover:!text-[#0F172A]"
        />
      </Badge>
    </Popover>
  )
}
```

- [ ] **Step 2: 修改 Header 集成 NotificationCenter**

替换 `header.tsx` 中硬编码的 Badge + BellOutlined 按钮部分。

将：
```tsx
<Badge count={3} size="small" color="#F97316" offset={[-2, 2]}>
  <Button
    type="text"
    icon={<BellOutlined />}
    className="!text-[#64748B] hover:!text-[#0F172A]"
  />
</Badge>
```

替换为：
```tsx
<NotificationCenter />
```

并在 header.tsx 顶部添加 import：
```tsx
import NotificationCenter from '../../components/notification-center'
```

移除不再使用的 `BellOutlined` import（如果 header 中其他地方不用的话）。

- [ ] **Step 3: 提交**

```bash
git add frontend/src/components/notification-center.tsx frontend/src/features/layout/header.tsx
git commit -m "feat(notification): add NotificationCenter component integrated in header"
```

---

### Task 10: useTaskRealtime Hook + App 集成 + 轮询移除

**Files:**
- Create: `frontend/src/hooks/use-task-realtime.ts`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/pages/tasks-page.tsx`
- Modify: `frontend/src/pages/workflow-detail-page.tsx`

- [ ] **Step 1: 实现 useTaskRealtime hook**

```typescript
// frontend/src/hooks/use-task-realtime.ts
import { useEffect } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { wsClient } from '../lib/ws-client'
import { useNotificationStore } from '../stores/notification-store'
import { taskKeys } from '../services/tasks-api'
import type { NotificationItem } from '../services/notifications-api'

/**
 * Global hook that bridges WebSocket events to TanStack Query and Notification Store.
 * Call once in App root.
 */
export function useTaskRealtime() {
  const queryClient = useQueryClient()

  useEffect(() => {
    // Task status changes → invalidate related queries
    const unsubStatus = wsClient.on('task_status', (data: any) => {
      // Invalidate the list for the new status
      queryClient.invalidateQueries({
        queryKey: taskKeys.list({ status: data.status }),
      })
      // Invalidate the specific task detail
      queryClient.invalidateQueries({
        queryKey: taskKeys.detail(data.task_id),
      })
      // Also invalidate the old status list (task moved out of it)
      if (data.from_status && data.from_status !== data.status) {
        queryClient.invalidateQueries({
          queryKey: taskKeys.list({ status: data.from_status }),
        })
      }
    })

    // Notification → add to store
    const unsubNotif = wsClient.on('notification', (data: unknown) => {
      useNotificationStore.getState().addNotification(data as NotificationItem)
    })

    return () => {
      unsubStatus()
      unsubNotif()
    }
  }, [queryClient])
}
```

- [ ] **Step 2: 确认 taskKeys 导出**

检查 `frontend/src/services/tasks-api.ts` 中 `taskKeys` 的导出和结构。确认：
- `taskKeys.list({ status })` — 看板列表的 query key
- `taskKeys.detail(task_id)` — 任务详情的 query key

如果结构不同，调整 hook 中的 query key 构造。

- [ ] **Step 3: 修改 App.tsx 集成 wsClient 和 useTaskRealtime**

在 `App.tsx` 中添加：

```typescript
import { useTaskRealtime } from './hooks/use-task-realtime'
import { wsClient } from './lib/ws-client'
import { useAuthStore } from './stores/auth-store'
```

在 App 组件内部添加：

```typescript
// Connect WebSocket when authenticated
const isAuthenticated = useAuthStore((s) => !!s.accessToken)

useEffect(() => {
  if (isAuthenticated) {
    wsClient.resume()
    wsClient.connect()
  } else {
    wsClient.disconnect()
  }
}, [isAuthenticated])

// Bridge WS events to TanStack Query
useTaskRealtime()

// Load initial notification data
useEffect(() => {
  if (isAuthenticated) {
    useNotificationStore.getState().loadFromApi()
  }
}, [isAuthenticated])
```

- [ ] **Step 4: 移除 tasks-page.tsx 中的轮询**

在 `frontend/src/pages/tasks-page.tsx` 中：

1. 看板列表查询 — 移除 `refetchInterval: 5_000`：

找到类似这样的代码：
```typescript
const boardQueries = useQueries({
  queries: BOARD_STATUSES.map((status) => ({
    queryKey: taskKeys.list({ status, page: 1, page_size: 50 }),
    queryFn: () => tasksApi.list({ status, page: 1, page_size: 50 }),
    refetchInterval: 5_000,
  })),
})
```

移除 `refetchInterval: 5_000`。

2. 活跃任务详情 — 移除 `refetchInterval: 5_000` 和 `staleTime: 3_000`。

3. Drawer 条件轮询 — 移除 `refetchInterval` 回调函数。

- [ ] **Step 5: 移除 workflow-detail-page.tsx 中的轮询**

在 `frontend/src/pages/workflow-detail-page.tsx` 中，找到 `pollTaskStatus()` 函数（使用 `setTimeout` 循环轮询，2 秒间隔，最多 60 次）。

替换为：初始加载一次任务状态，后续由 `useTaskRealtime` hook 的 WebSocket 事件触发自动刷新。

具体修改方式取决于 `pollTaskStatus` 的使用上下文，核心思路是：
- 保留初始 HTTP 请求获取任务状态
- 移除 `setTimeout` 轮询循环
- 任务完成后由 WebSocket `task_status` 事件触发 `invalidateQueries`

- [ ] **Step 6: 提交**

```bash
git add frontend/src/hooks/use-task-realtime.ts frontend/src/App.tsx frontend/src/pages/tasks-page.tsx frontend/src/pages/workflow-detail-page.tsx
git commit -m "feat(notification): add useTaskRealtime hook, remove all task polling"
```

---

### Task 11: 最终验证 + 集成测试

- [ ] **Step 1: 运行全部后端测试**

Run: `cd backend && uv run pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 2: 运行前端 lint**

Run: `cd frontend && npx eslint src/lib/ws-client.ts src/stores/notification-store.ts src/components/notification-center.tsx src/hooks/use-task-realtime.ts src/services/notifications-api.ts --no-error-on-unmatched-pattern`
Expected: No errors

- [ ] **Step 3: 验证文件完整性**

确认所有新建文件都存在：

```bash
# Backend
ls backend/app/models/notification.py
ls backend/app/schemas/notification.py
ls backend/app/services/notification_repo.py
ls backend/app/services/ws_manager.py
ls backend/app/services/notification_service.py
ls backend/app/api/v1/notifications.py
ls backend/app/api/v1/ws.py

# Frontend
ls frontend/src/services/notifications-api.ts
ls frontend/src/hooks/use-task-realtime.ts
ls frontend/src/components/notification-center.tsx
```

- [ ] **Step 4: 验证轮询已移除**

搜索确认前端不再有 `refetchInterval` 轮询 task 相关数据：

```bash
grep -r "refetchInterval" frontend/src/pages/tasks-page.tsx frontend/src/pages/workflow-detail-page.tsx
```

Expected: 无输出（或仅剩非 task 相关的轮询）

```bash
grep -r "pollTaskStatus" frontend/src/
```

Expected: 无输出

- [ ] **Step 5: 最终提交（如有修复）**

```bash
git add -A
git commit -m "fix: notification service integration fixes"
```
