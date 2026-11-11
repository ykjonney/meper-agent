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
        """双目标都空 → TASK_TARGET_REQUIRED（互斥校验覆盖旧缺 workflow_id 语义）。"""
        with pytest.raises(ValidationError) as exc_info:
            await TaskService.create_task(workflow_id="", input_data={})
        assert exc_info.value.code == "TASK_TARGET_REQUIRED"

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
            # create_task triggers _start_workflow_execution → Celery dispatch;
            # mock it out so the test stays focused on the insert logic.
            patch("app.services.task_service.TaskService._start_workflow_execution"),
        ):
            result = await TaskService.create_task(
                workflow_id="wf_exist",
                input_data={"query": "hello"},
                created_by="user_1",
            )
            # 校验通过后应触发 insert
            assert mock_task_collection.insert_one.called
            assert result["_id"] == "task_new"


class TestCreateTaskAgentTarget:
    """create_task agent 分支：published 校验 + instruction 必填 + 互斥。"""

    @pytest.mark.asyncio
    async def test_both_targets_raises(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            await TaskService.create_task(workflow_id="wf_1", agent_id="agent_1", input_data={})
        assert exc_info.value.code == "TASK_TARGET_REQUIRED"

    @pytest.mark.asyncio
    async def test_agent_not_found_raises(self) -> None:
        mock_agents = MagicMock()
        mock_agents.find_one = AsyncMock(return_value=None)
        mock_db = MagicMock()
        mock_db.__getitem__ = MagicMock(return_value=mock_agents)

        with (
            patch("app.services.task_service.get_database", return_value=mock_db),
            pytest.raises(ValidationError) as exc_info,
        ):
            await TaskService.create_task(
                workflow_id="", agent_id="agent_x",
                input_data={"instruction": "做"},
            )
        assert exc_info.value.code == "AGENT_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_agent_not_published_raises(self) -> None:
        mock_agents = MagicMock()
        mock_agents.find_one = AsyncMock(return_value={"_id": "agent_1", "status": "draft"})
        mock_db = MagicMock()
        mock_db.__getitem__ = MagicMock(return_value=mock_agents)

        with (
            patch("app.services.task_service.get_database", return_value=mock_db),
            pytest.raises(ValidationError) as exc_info,
        ):
            await TaskService.create_task(
                workflow_id="", agent_id="agent_1",
                input_data={"instruction": "做"},
            )
        assert exc_info.value.code == "AGENT_NOT_PUBLISHED"

    @pytest.mark.asyncio
    async def test_missing_instruction_raises(self) -> None:
        mock_agents = MagicMock()
        mock_agents.find_one = AsyncMock(return_value={"_id": "agent_1", "status": "published"})
        mock_db = MagicMock()
        mock_db.__getitem__ = MagicMock(return_value=mock_agents)

        with (
            patch("app.services.task_service.get_database", return_value=mock_db),
            pytest.raises(ValidationError) as exc_info,
        ):
            await TaskService.create_task(
                workflow_id="", agent_id="agent_1", input_data={},
            )
        assert exc_info.value.code == "TASK_MISSING_INSTRUCTION"
