"""Tests for WorkflowService — delete 同步清理 registry 等行为."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


class TestWorkflowDelete:
    """delete() 删除模板时应同步清理 workflow_registry，避免孤儿索引 404。"""

    @pytest.mark.asyncio
    async def test_delete_removes_registry_entry(self) -> None:
        """删除 workflow 模板时，同步删除 registry 里对应的索引条目。"""
        from app.services.workflow_service import WorkflowService

        with (
            patch(
                "app.services.workflow_service.WorkflowService._collection",
                return_value=type(
                    "C",
                    (),
                    {"delete_one": AsyncMock(return_value=type("R", (), {"deleted_count": 1})())},
                )(),
            ),
            patch(
                "app.services.workflow_registry_service.WorkflowRegistryService.delete_by_workflow_id",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_reg_delete,
        ):
            result = await WorkflowService.delete("wf_test123")
            assert result is True
            # 关键断言：registry 清理被调用，传入同一个 workflow_id
            mock_reg_delete.assert_called_once_with("wf_test123")

    @pytest.mark.asyncio
    async def test_delete_not_found_does_not_touch_registry(self) -> None:
        """模板不存在（deleted_count=0）时，不应触发 registry 清理。"""
        from app.services.workflow_service import WorkflowService

        with (
            patch(
                "app.services.workflow_service.WorkflowService._collection",
                return_value=type(
                    "C",
                    (),
                    {"delete_one": AsyncMock(return_value=type("R", (), {"deleted_count": 0})())},
                )(),
            ),
            patch(
                "app.services.workflow_registry_service.WorkflowRegistryService.delete_by_workflow_id",
                new_callable=AsyncMock,
            ) as mock_reg_delete,
        ):
            result = await WorkflowService.delete("wf_notexist")
            assert result is False
            mock_reg_delete.assert_not_called()


class TestRegistryDeleteByWorkflowId:
    """WorkflowRegistryService.delete_by_workflow_id 按 workflow_id 删除索引。"""

    @pytest.mark.asyncio
    async def test_delete_by_workflow_id(self) -> None:
        from app.services.workflow_registry_service import WorkflowRegistryService

        mock_result = type("R", (), {"deleted_count": 1})()
        with patch(
            "app.services.workflow_registry_service.WorkflowRegistryService._collection",
            return_value=type("C", (), {"delete_many": AsyncMock(return_value=mock_result)})(),
        ) as mock_collection_fn:
            result = await WorkflowRegistryService.delete_by_workflow_id("wf_test123")
            assert result is True
            # 验证 delete_many 的查询条件是 {"workflow_id": "wf_test123"}
            mock_collection = mock_collection_fn.return_value
            mock_collection.delete_many.assert_called_once_with({"workflow_id": "wf_test123"})

    @pytest.mark.asyncio
    async def test_delete_by_workflow_id_none_existent(self) -> None:
        """registry 里没有对应条目时返回 False，不报错。"""
        from app.services.workflow_registry_service import WorkflowRegistryService

        mock_result = type("R", (), {"deleted_count": 0})()
        with patch(
            "app.services.workflow_registry_service.WorkflowRegistryService._collection",
            return_value=type("C", (), {"delete_many": AsyncMock(return_value=mock_result)})(),
        ):
            result = await WorkflowRegistryService.delete_by_workflow_id("wf_none")
            assert result is False
