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


class TestUpdateEdgesCleanup:
    """update() 替换 nodes 时应同步清洗 edges——剔除两端节点已不存在的边。

    前端保存只发 nodes 不发 edges，若 $set 不清洗，DB 旧 edges 会残留
    对已删节点的引用（前端校验报「不存在的引用」、引擎复活陈旧边）。
    """

    @staticmethod
    def _mock_collection(existing_edges: list[dict], updated_doc: dict) -> type:
        return type(
            "C",
            (),
            {
                "find_one": AsyncMock(return_value={"edges": existing_edges}),
                "find_one_and_update": AsyncMock(return_value=updated_doc),
            },
        )()

    @pytest.mark.asyncio
    async def test_update_nodes_filters_dangling_edges(self) -> None:
        """nodes 替换后，引用已删节点的 edges 被剔除，保留两端都在的边。"""
        from app.services.workflow_service import WorkflowService

        mock_collection = self._mock_collection(
            existing_edges=[
                {"edge_id": "e1", "source": "a", "target": "b"},
                {"edge_id": "e2", "source": "a", "target": "ghost"},
                {"edge_id": "e3", "source": "ghost", "target": "b"},
            ],
            updated_doc={"_id": "wf1", "status": "draft", "nodes": []},
        )
        with patch(
            "app.services.workflow_service.WorkflowService._collection",
            return_value=mock_collection,
        ):
            await WorkflowService.update(
                "wf1",
                {"nodes": [{"node_id": "a"}, {"node_id": "b"}]},
            )

        set_payload = mock_collection.find_one_and_update.call_args.args[1]["$set"]
        assert set_payload["edges"] == [{"edge_id": "e1", "source": "a", "target": "b"}]

    @pytest.mark.asyncio
    async def test_update_without_nodes_leaves_edges_alone(self) -> None:
        """只改 name 等元数据时不应触碰 edges，也不额外读库。"""
        from app.services.workflow_service import WorkflowService

        mock_collection = self._mock_collection(
            existing_edges=[],
            updated_doc={"_id": "wf1", "status": "draft"},
        )
        with patch(
            "app.services.workflow_service.WorkflowService._collection",
            return_value=mock_collection,
        ):
            await WorkflowService.update("wf1", {"name": "新名字"})

        mock_collection.find_one.assert_not_called()
        set_payload = mock_collection.find_one_and_update.call_args.args[1]["$set"]
        assert "edges" not in set_payload

    @pytest.mark.asyncio
    async def test_update_explicit_edges_also_filtered(self) -> None:
        """显式传入 edges 时同样过滤（不读 DB 原值）。"""
        from app.services.workflow_service import WorkflowService

        mock_collection = self._mock_collection(
            existing_edges=[],
            updated_doc={"_id": "wf1", "status": "draft"},
        )
        with patch(
            "app.services.workflow_service.WorkflowService._collection",
            return_value=mock_collection,
        ):
            await WorkflowService.update(
                "wf1",
                {
                    "nodes": [{"node_id": "a"}],
                    "edges": [
                        {"source": "a", "target": "a"},
                        {"source": "a", "target": "ghost"},
                    ],
                },
            )

        mock_collection.find_one.assert_not_called()
        set_payload = mock_collection.find_one_and_update.call_args.args[1]["$set"]
        assert set_payload["edges"] == [{"source": "a", "target": "a"}]


class TestPublishValidationDanglingRefs:
    """发布校验应覆盖 gateway/parallel/agent 分支的悬空引用。

    与运行时 WorkflowValidator 的 DANGLING_NEXT_TARGET 覆盖面对齐，
    避免发布通过、执行时才被校验拦下。
    """

    @staticmethod
    def _base_doc(nodes: list[dict]) -> dict:
        # start→end 连通的基础结构，只叠加被测的悬空引用
        return {
            "nodes": [
                {
                    "node_id": "start",
                    "type": "start",
                    "label": "开始",
                    "config": {"next_nodes": [{"target": "end"}]},
                    "position": {"x": 0, "y": 0},
                },
                {
                    "node_id": "end",
                    "type": "end",
                    "label": "结束",
                    "config": {},
                    "position": {"x": 1, "y": 1},
                },
                *nodes,
            ],
            "edges": [],
        }

    @staticmethod
    def _publish_errors(doc: dict) -> list[str]:
        from app.core.errors import ValidationError
        from app.services.workflow_service import WorkflowService

        try:
            WorkflowService._validate_for_publish(doc)
        except ValidationError as e:
            details = e.details or {}
            return [err.get("message", "") for err in details.get("errors", [])]
        return []

    @pytest.mark.asyncio
    async def test_gateway_dangling_condition_and_default(self) -> None:
        """gateway conditions.target / default_branch 指向不存在节点时报错。"""
        doc = self._base_doc([
            {
                "node_id": "gw",
                "type": "gateway",
                "label": "网关",
                "config": {
                    "conditions": [{"target": "ghost", "expression": "x"}],
                    "default_branch": "ghost2",
                },
                "position": {"x": 2, "y": 2},
            },
        ])
        errors = self._publish_errors(doc)
        assert any("网关条件分支引用了不存在的目标节点 'ghost'" in m for m in errors)
        assert any("默认分支引用了不存在的目标节点 'ghost2'" in m for m in errors)

    @pytest.mark.asyncio
    async def test_parallel_dangling_branch(self) -> None:
        """parallel branches.start_node 指向不存在节点时报错。"""
        doc = self._base_doc([
            {
                "node_id": "par",
                "type": "parallel",
                "label": "并行",
                "config": {"branches": [{"start_node": "ghost", "label": "b1"}]},
                "position": {"x": 2, "y": 2},
            },
        ])
        errors = self._publish_errors(doc)
        assert any("并行分支引用了不存在的目标节点 'ghost'" in m for m in errors)

    @pytest.mark.asyncio
    async def test_agent_dangling_insufficient_branch(self) -> None:
        """agent insufficient_branch 指向不存在节点时报错。"""
        doc = self._base_doc([
            {
                "node_id": "ag",
                "type": "agent",
                "label": "助理",
                "config": {
                    "agent_id": "ag_x",
                    "input_query": "q",
                    "insufficient_branch": "ghost",
                },
                "position": {"x": 2, "y": 2},
            },
        ])
        errors = self._publish_errors(doc)
        assert any("信息不足分支引用了不存在的目标节点 'ghost'" in m for m in errors)

    @pytest.mark.asyncio
    async def test_valid_routing_passes(self) -> None:
        """所有分支引用都存在时不因新规则报错（可正常发布）。"""
        doc = self._base_doc([
            {
                "node_id": "gw",
                "type": "gateway",
                "label": "网关",
                "config": {
                    "conditions": [{"target": "end", "expression": "x"}],
                    "default_branch": "end",
                },
                "position": {"x": 2, "y": 2},
            },
        ])
        # 不抛 ValidationError 即通过
        from app.services.workflow_service import WorkflowService

        WorkflowService._validate_for_publish(doc)


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
