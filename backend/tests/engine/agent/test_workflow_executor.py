"""Tests for the workflow task tools — 8 task management tools with mocked services."""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from app.engine.agent.workflow_executor import (
    _TASK_TOOLS,
    cancel_task,
    dispatch_workflow,
    propose_workflow,
    task_intervene,
    task_list,
    task_query,
    update_task_variables,
)

# Fake Task document returned by TaskService
_FAKE_TASK = {
    "_id": "task_20260611_120000",
    "workflow_id": "wf_quality_report",
    "status": "pending",
    "created_by": "agent",
    "created_by_type": "agent",
    "version": 1,
    "input": {"product_name": "Widget-A"},
    "timeline": [
        {
            "timestamp": datetime.now(UTC),
            "event_type": "created",
            "data": {"workflow_id": "wf_quality_report"},
            "actor": "agent",
        }
    ],
    "created_at": datetime.now(UTC),
    "updated_at": datetime.now(UTC),
}

_FAKE_TASK_RUNNING = {**_FAKE_TASK, "status": "running", "version": 2}
_FAKE_TASK_WAITING = {**_FAKE_TASK, "status": "waiting_human", "version": 2}


@pytest.fixture(autouse=True)
def _mock_services():
    """Mock TaskService."""
    with patch("app.engine.agent.workflow_executor.TaskService") as mock_task:
        # Task service mocks
        mock_task.get_task = AsyncMock(return_value=_FAKE_TASK)
        mock_task.list_tasks = AsyncMock(return_value=([_FAKE_TASK], 1))
        mock_task.transition_task = AsyncMock(return_value=_FAKE_TASK_RUNNING)
        mock_task.update_variables = AsyncMock(
            return_value={**_FAKE_TASK, "version": 2}
        )

        yield


class TestTaskQuery:
    """task_query tool."""

    @pytest.mark.asyncio
    async def test_query_returns_status(self):
        """Should return task status with type field."""
        result = await task_query.ainvoke({"task_id": "task_20260611_120000"})
        import json

        data = json.loads(result)
        assert data["type"] == "task_result"
        assert data["status"] == "pending"
        assert data["task_id"] == "task_20260611_120000"

    @pytest.mark.asyncio
    async def test_query_not_found(self):
        """Should handle unknown task."""
        with patch(
            "app.engine.agent.workflow_executor.TaskService.get_task",
            AsyncMock(return_value=None),
        ):
            result = await task_query.ainvoke({"task_id": "nonexistent"})
            import json

            data = json.loads(result)
            assert "error" in data


class TestTaskList:
    """task_list tool."""

    @pytest.mark.asyncio
    async def test_list_all(self):
        """Should return paginated task list."""
        result = await task_list.ainvoke({})
        assert "items" in result
        assert "total" in result

    @pytest.mark.asyncio
    async def test_list_with_filter(self):
        """Should filter by status."""
        result = await task_list.ainvoke({"status": "pending"})
        assert "items" in result

    @pytest.mark.asyncio
    async def test_list_invalid_status(self):
        """Should return error for invalid status."""
        result = await task_list.ainvoke({"status": "invalid_status"})
        assert "error" in result


class TestTaskIntervene:
    """task_intervene tool."""

    @pytest.mark.asyncio
    async def test_approve(self):
        """Should approve a waiting_human task."""
        result = await task_intervene.ainvoke(
            {
                "task_id": "task_001",
                "action": "approve",
                "reason": "Looks good",
            }
        )
        assert "approve" in result

    @pytest.mark.asyncio
    async def test_cancel(self):
        """Should cancel a task."""
        result = await task_intervene.ainvoke(
            {
                "task_id": "task_001",
                "action": "cancel",
                "reason": "No longer needed",
            }
        )
        assert "cancel" in result

    @pytest.mark.asyncio
    async def test_invalid_action(self):
        """Should return error for unknown action."""
        result = await task_intervene.ainvoke(
            {
                "task_id": "task_001",
                "action": "unknown_action",
            }
        )
        assert "error" in result


class TestCancelTask:
    """cancel_task tool."""

    @pytest.mark.asyncio
    async def test_cancel_returns_result(self):
        """Should invoke intervene with cancel action."""
        result = await cancel_task.ainvoke(
            {"task_id": "task_001", "reason": "Cancelled"}
        )
        assert "cancel" in result or "task_id" in result


class TestUpdateTaskVariables:
    """update_task_variables tool."""

    @pytest.mark.asyncio
    async def test_update_variables(self):
        """Should update task variables."""
        result = await update_task_variables.ainvoke(
            {
                "task_id": "task_001",
                "variables": '{"checked_by": "Alice"}',
                "version": 1,
            }
        )
        assert "变量已更新" in result

    @pytest.mark.asyncio
    async def test_update_invalid_json(self):
        """Should handle invalid JSON."""
        result = await update_task_variables.ainvoke(
            {
                "task_id": "task_001",
                "variables": "not-json",
            }
        )
        assert "error" in result


class TestToolList:
    """_TASK_TOOLS export list."""

    def test_tool_count(self):
        """Should export 7 task management tools (propose_workflow + dispatch_workflow + 5)."""
        assert len(_TASK_TOOLS) == 7

    def test_tool_names(self):
        """Should contain all expected tool names."""
        names = {t.name for t in _TASK_TOOLS}
        expected = {
            "propose_workflow",
            "dispatch_workflow",
            "task_query",
            "task_list",
            "task_intervene",
            "cancel_task",
            "update_task_variables",
        }
        assert names == expected


# ---------------------------------------------------------------------------
# propose_workflow — shows a confirmation card
# ---------------------------------------------------------------------------


class TestProposeWorkflow:
    """propose_workflow tool — returns proposal info without creating a Task."""

    @pytest.mark.asyncio
    async def test_propose_not_found(self):
        """Should return error when workflow does not exist."""
        with patch(
            "app.services.workflow_registry_service.WorkflowRegistryService.get_by_name",
            return_value=None,
        ), patch(
            "app.services.workflow_registry_service.WorkflowRegistryService.get_by_workflow_id",
            return_value=None,
        ):
            result = await propose_workflow.ainvoke(
                {"workflow_name": "nonexistent"}
            )
            import json

            data = json.loads(result)
            assert "error" in data

    @pytest.mark.asyncio
    async def test_propose_success(self):
        """Should return proposal info with type field."""
        fake_entry = {
            "_id": "reg_001",
            "name": "data-pull",
            "description": "数据拉取工作流",
            "has_human_node": True,
        }
        with patch(
            "app.services.workflow_registry_service.WorkflowRegistryService.get_by_name",
            return_value=fake_entry,
        ):
            result = await propose_workflow.ainvoke(
                {"workflow_name": "data-pull", "params": {"source": "mysql_db"}}
            )
            import json

            data = json.loads(result)
            assert data["type"] == "workflow_proposal"
            assert data["workflow_name"] == "data-pull"
            assert data["workflow_description"] == "数据拉取工作流"
            assert data["input_preview"] == {"source": "mysql_db"}
            assert data["has_human_node"] is True

    @pytest.mark.asyncio
    async def test_propose_no_params(self):
        """Should work without params."""
        fake_entry = {
            "_id": "reg_001",
            "name": "data-pull",
            "description": "数据拉取工作流",
            "has_human_node": False,
        }
        with patch(
            "app.services.workflow_registry_service.WorkflowRegistryService.get_by_name",
            return_value=fake_entry,
        ):
            result = await propose_workflow.ainvoke(
                {"workflow_name": "data-pull"}
            )
            import json

            data = json.loads(result)
            assert data["type"] == "workflow_proposal"
            assert data["input_preview"] == {}

    @pytest.mark.asyncio
    async def test_propose_params_as_json_string(self):
        """LLM 有时会把 params 作为 JSON 字符串传入，应自动解析。"""
        fake_entry = {
            "_id": "reg_002",
            "name": "ui-designer",
            "description": "UI 设计工作流",
            "has_human_node": False,
        }
        with patch(
            "app.services.workflow_registry_service.WorkflowRegistryService.get_by_name",
            return_value=fake_entry,
        ):
            result = await propose_workflow.ainvoke({
                "workflow_name": "ui-designer",
                "params": '{"input": "设计一个现代简约的个人博客主题"}',
            })
            import json
            data = json.loads(result)
            assert data["type"] == "workflow_proposal"
            assert data["input_preview"] == {"input": "设计一个现代简约的个人博客主题"}

    @pytest.mark.asyncio
    async def test_propose_params_invalid_json_string(self):
        """非法 JSON 字符串应报 ValidationError，不应被吞掉。"""
        from pydantic import ValidationError
        fake_entry = {
            "_id": "reg_003",
            "name": "ui-designer",
            "description": "UI 设计工作流",
            "has_human_node": False,
        }
        with (
            patch(
                "app.services.workflow_registry_service.WorkflowRegistryService.get_by_name",
                return_value=fake_entry,
            ),
            pytest.raises(ValidationError),
        ):
            await propose_workflow.ainvoke({
                "workflow_name": "ui-designer",
                "params": "{not valid json}",
            })


# ---------------------------------------------------------------------------
# dispatch_workflow — creates a Task
# ---------------------------------------------------------------------------

_FAKE_WORKFLOW_ENTRY = {
    "_id": "reg_entry_001",
    "name": "数据拉取",
    "description": "数据拉取工作流",
    "workflow_id": "wf_data_pull",
    "has_human_node": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "source": {"type": "string", "description": "数据源名称"},
        },
        "required": ["source"],
    },
}


class TestDispatchWorkflow:
    """dispatch_workflow tool — creates Task directly."""

    @pytest.mark.asyncio
    async def test_dispatch_not_found(self):
        """Should return error when workflow does not exist."""
        with patch(
            "app.services.workflow_registry_service.WorkflowRegistryService.get_by_name",
            return_value=None,
        ), patch(
            "app.services.workflow_registry_service.WorkflowRegistryService.get_by_workflow_id",
            return_value=None,
        ):
            result = await dispatch_workflow.ainvoke(
                {"workflow_name": "nonexistent_workflow"}
            )
            assert "error" in result

    @pytest.mark.asyncio
    async def test_dispatch_success(self):
        """Should create a Task and return task_id."""
        with patch(
            "app.services.workflow_registry_service.WorkflowRegistryService.get_by_name",
            return_value=_FAKE_WORKFLOW_ENTRY,
        ), patch(
            "app.engine.agent.workflow_executor.TaskService.create_task",
            AsyncMock(return_value=_FAKE_TASK),
        ):
            result = await dispatch_workflow.ainvoke(
                {
                    "workflow_name": "数据拉取",
                    "params": {"source": "mysql_db"},
                }
            )
            import json

            data = json.loads(result)
            assert data["type"] == "task_created"
            assert "task_id" in data
            assert data["status"] == "pending"
            assert "数据拉取" in data.get("workflow_name", "")

    @pytest.mark.asyncio
    async def test_dispatch_no_params(self):
        """Should work without params."""
        with patch(
            "app.services.workflow_registry_service.WorkflowRegistryService.get_by_name",
            return_value=_FAKE_WORKFLOW_ENTRY,
        ), patch(
            "app.engine.agent.workflow_executor.TaskService.create_task",
            AsyncMock(return_value=_FAKE_TASK),
        ):
            result = await dispatch_workflow.ainvoke(
                {"workflow_name": "数据拉取"}
            )
            import json

            data = json.loads(result)
            assert "task_id" in data

    @pytest.mark.asyncio
    async def test_dispatch_has_human_node(self):
        """Should indicate human approval node presence."""
        with patch(
            "app.services.workflow_registry_service.WorkflowRegistryService.get_by_name",
            return_value=_FAKE_WORKFLOW_ENTRY,
        ), patch(
            "app.engine.agent.workflow_executor.TaskService.create_task",
            AsyncMock(return_value=_FAKE_TASK),
        ):
            result = await dispatch_workflow.ainvoke(
                {
                    "workflow_name": "数据拉取",
                    "params": {"source": "mysql_db"},
                }
            )
            import json

            data = json.loads(result)
            assert "has_human_node" in data
            assert data["has_human_node"] is True

    @pytest.mark.asyncio
    async def test_dispatch_params_as_json_string(self):
        """LLM 把 params 作为 JSON 字符串传入时，应自动解析后传给 TaskService。"""
        with patch(
            "app.services.workflow_registry_service.WorkflowRegistryService.get_by_name",
            return_value=_FAKE_WORKFLOW_ENTRY,
        ), patch(
            "app.engine.agent.workflow_executor.TaskService.create_task",
            AsyncMock(return_value=_FAKE_TASK),
        ) as mock_create:
            result = await dispatch_workflow.ainvoke({
                "workflow_name": "数据拉取",
                "params": '{"source": "mysql_db"}',
            })
            import json
            data = json.loads(result)
            assert "task_id" in data
            # 验证传给 TaskService 的 input_data 是已解析的 dict
            mock_create.assert_awaited_once()
            call_kwargs = mock_create.call_args.kwargs
            assert call_kwargs["input_data"] == {"source": "mysql_db"}

    @pytest.mark.asyncio
    async def test_dispatch_uses_real_user_id_from_workspace(self):
        """Regression: chat-triggered dispatch must set created_by to the real
        user_id (from workspace context), NOT the literal "agent".

        Otherwise task lifecycle notifications (e.g. task.waiting_human on a
        Human node) are addressed to a non-existent "agent" user and the real
        user never receives them.
        """
        from types import SimpleNamespace

        fake_workspace = SimpleNamespace(user_id="user_real_123", session_id="sess_1")
        with patch(
            "app.services.workflow_registry_service.WorkflowRegistryService.get_by_name",
            return_value=_FAKE_WORKFLOW_ENTRY,
        ), patch(
            "app.engine.agent.workflow_executor.TaskService.create_task",
            AsyncMock(return_value=_FAKE_TASK),
        ) as mock_create, patch(
            "app.engine.agent.builtin_tools._get_workspace",
            return_value=fake_workspace,
        ):
            await dispatch_workflow.ainvoke({"workflow_name": "数据拉取"})

            mock_create.assert_awaited_once()
            call_kwargs = mock_create.call_args.kwargs
            # created_by MUST be the real user, not "agent"
            assert call_kwargs["created_by"] == "user_real_123"

    @pytest.mark.asyncio
    async def test_dispatch_falls_back_to_agent_when_no_workspace(self):
        """When no workspace context is available (e.g. non-chat invocation),
        created_by falls back to "agent" so the tool still works."""
        with patch(
            "app.services.workflow_registry_service.WorkflowRegistryService.get_by_name",
            return_value=_FAKE_WORKFLOW_ENTRY,
        ), patch(
            "app.engine.agent.workflow_executor.TaskService.create_task",
            AsyncMock(return_value=_FAKE_TASK),
        ) as mock_create, patch(
            "app.engine.agent.builtin_tools._get_workspace",
            return_value=None,
        ):
            await dispatch_workflow.ainvoke({"workflow_name": "数据拉取"})

            mock_create.assert_awaited_once()
            call_kwargs = mock_create.call_args.kwargs
            assert call_kwargs["created_by"] == "agent"
