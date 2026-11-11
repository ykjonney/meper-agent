"""会话列表过滤：task_id 非空（含字段缺失）的会话不出现在列表。"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.services.session_service import SessionService


@pytest.mark.asyncio
async def test_list_excludes_task_sessions() -> None:
    captured: dict = {}

    class FakeCursor:
        def sort(self, *a):
            return self

        def skip(self, *a):
            return self

        def limit(self, *a):
            return self

        async def to_list(self, length):
            return []

    col = MagicMock()
    col.count_documents = AsyncMock(return_value=0)
    col.find = lambda q: (captured.update(q) or FakeCursor())

    with patch.object(SessionService, "_collection", return_value=col):
        await SessionService.list_sessions(user_id="u1", page=1, page_size=20)

    assert captured["task_id"] == {"$in": ["", None]}, \
        "必须用 $in ['', None]（$in 含 None 同时匹配字段缺失的旧文档）"
