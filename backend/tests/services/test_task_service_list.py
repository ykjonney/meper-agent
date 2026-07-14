"""Tests for TaskService.list_tasks - trigger_id / source 过滤透传."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.services.task_service import TaskService


def _mock_db_with_collection(collection: MagicMock) -> MagicMock:
    mock_db = MagicMock()
    mock_db.__getitem__ = MagicMock(return_value=collection)
    return mock_db


def _make_cursor() -> MagicMock:
    """模拟 find() 返回的 cursor 链: sort -> skip -> limit -> to_list."""
    cursor = MagicMock()
    cursor.sort = MagicMock(return_value=cursor)
    cursor.skip = MagicMock(return_value=cursor)
    cursor.limit = MagicMock(return_value=cursor)
    cursor.to_list = AsyncMock(return_value=[])
    return cursor


class TestListTasksFilters:
    """list_tasks 应把可选过滤参数透传到 MongoDB query。"""

    @pytest.mark.asyncio
    async def test_filter_by_trigger_id(self) -> None:
        """trigger_id 过滤 -> query 含 trigger_id。"""
        cursor = _make_cursor()
        collection = MagicMock()
        collection.find = MagicMock(return_value=cursor)
        collection.count_documents = AsyncMock(return_value=0)

        with patch(
            "app.services.task_service.get_database",
            return_value=_mock_db_with_collection(collection),
        ):
            await TaskService.list_tasks(trigger_id="trig_123")

        collection.find.assert_called_once()
        query = collection.find.call_args[0][0]
        assert query.get("trigger_id") == "trig_123"

    @pytest.mark.asyncio
    async def test_filter_by_source(self) -> None:
        """source 过滤 -> query 含 source。"""
        cursor = _make_cursor()
        collection = MagicMock()
        collection.find = MagicMock(return_value=cursor)
        collection.count_documents = AsyncMock(return_value=0)

        with patch(
            "app.services.task_service.get_database",
            return_value=_mock_db_with_collection(collection),
        ):
            await TaskService.list_tasks(source="trigger_scheduled")

        query = collection.find.call_args[0][0]
        assert query.get("source") == "trigger_scheduled"

    @pytest.mark.asyncio
    async def test_no_filters_empty_query(self) -> None:
        """不传过滤 -> query 为空 dict（不过滤）。"""
        cursor = _make_cursor()
        collection = MagicMock()
        collection.find = MagicMock(return_value=cursor)
        collection.count_documents = AsyncMock(return_value=0)

        with patch(
            "app.services.task_service.get_database",
            return_value=_mock_db_with_collection(collection),
        ):
            await TaskService.list_tasks()

        query = collection.find.call_args[0][0]
        assert query == {}

    @pytest.mark.asyncio
    async def test_combined_filters(self) -> None:
        """trigger_id + source + workflow_id 组合过滤。"""
        cursor = _make_cursor()
        collection = MagicMock()
        collection.find = MagicMock(return_value=cursor)
        collection.count_documents = AsyncMock(return_value=0)

        with patch(
            "app.services.task_service.get_database",
            return_value=_mock_db_with_collection(collection),
        ):
            await TaskService.list_tasks(
                workflow_id="wf_1",
                trigger_id="trig_1",
                source="trigger_scheduled",
            )

        query = collection.find.call_args[0][0]
        assert query == {
            "workflow_id": "wf_1",
            "trigger_id": "trig_1",
            "source": "trigger_scheduled",
        }
