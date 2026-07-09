"""Tests for TaskService.create_task — workflow 模板存在性校验."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.core.errors import ValidationError
from app.services.task_service import TaskService


class TestCreateTaskWorkflowValidation:
    """create_task 应校验 workflow 模板存在，避免指向已删除模板的僵尸 task。"""

    @pytest.mark.asyncio
    async def test_empty_workflow_id_raises(self) -> None:
        """workflow_id 为空 → TASK_MISSING_WORKFLOW_ID。"""
        with pytest.raises(ValidationError) as exc_info:
            await TaskService.create_task(workflow_id="", input_data={})
        assert exc_info.value.code == "TASK_MISSING_WORKFLOW_ID"

    @pytest.mark.asyncio
    async def test_nonexistent_workflow_raises(self) -> None:
        """workflow 模板不存在 → WORKFLOW_NOT_FOUND，不创建 task。"""
        mock_collection = MagicMock()
        mock_collection.find_one = AsyncMock(return_value=None)  # 模板查不到

        mock_db = MagicMock()
        mock_db.__getitem__ = MagicMock(return_value=mock_collection)

        with patch("app.services.task_service.get_database", return_value=mock_db):
            with pytest.raises(ValidationError) as exc_info:
                await TaskService.create_task(
                    workflow_id="wf_notexist",
                    input_data={},
                )
            assert exc_info.value.code == "WORKFLOW_NOT_FOUND"
            # 验证查询条件是按 _id 查 workflows 集合
            mock_collection.find_one.assert_called_once_with(
                {"_id": "wf_notexist"}, {"_id": 1}
            )

    @pytest.mark.asyncio
    async def test_existing_workflow_proceeds_to_insert(self) -> None:
        """workflow 模板存在 → 校验通过，继续走 insert 流程。"""
        mock_workflow_collection = MagicMock()
        mock_workflow_collection.find_one = AsyncMock(
            return_value={"_id": "wf_exist"}  # 模板存在
        )
        mock_task_collection = MagicMock()
        mock_task_collection.insert_one = AsyncMock(
            return_value=MagicMock(inserted_id="task_new")
        )
        mock_task_collection.find_one = AsyncMock(
            return_value={"_id": "task_new", "status": "pending"}
        )

        def get_collection(name):
            return mock_workflow_collection if name == "workflows" else mock_task_collection

        mock_db = MagicMock()
        mock_db.__getitem__ = MagicMock(side_effect=get_collection)

        # event_bus.publish 是 async，mock 成可 await 的
        mock_event_bus = MagicMock()
        mock_event_bus.publish = AsyncMock()

        with (
            patch("app.services.task_service.get_database", return_value=mock_db),
            patch("app.services.task_service.TaskService._write_audit_log", new_callable=AsyncMock),
            patch("app.services.task_service.get_event_bus", return_value=mock_event_bus),
        ):
            result = await TaskService.create_task(
                workflow_id="wf_exist",
                input_data={"query": "hello"},
                created_by="user_1",
            )
            # 校验通过后应触发 insert
            assert mock_task_collection.insert_one.called
            assert result["_id"] == "task_new"
