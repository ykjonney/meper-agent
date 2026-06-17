"""Node executor unit tests — all external dependencies mocked."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.engine.workflow.node_executor import (
    AgentNodeExecutor,
    EndNodeExecutor,
    GatewayNodeExecutor,
    NodeResult,
    ParallelNodeExecutor,
    StartNodeExecutor,
    SubflowNodeExecutor,
    ToolNodeExecutor,
    get_node_executor,
)


# ── StartNodeExecutor ──


class TestStartNodeExecutor:
    @pytest.mark.asyncio
    async def test_input_mapping(self) -> None:
        config = {"input_mapping": {"user": "{{ input.user_name }}"}}
        executor = StartNodeExecutor("start_1", config)
        result = await executor.execute({"input": {"user_name": "Alice"}})
        assert result.success
        assert result.output == {"user": "Alice"}

    @pytest.mark.asyncio
    async def test_output_variables(self) -> None:
        config = {
            "output_variables": [
                {"name": "query", "type": "text", "required": True, "default": ""},
            ],
        }
        executor = StartNodeExecutor("start_1", config)
        result = await executor.execute({"input": {"query": "hello"}})
        assert result.success
        assert result.output["query"] == "hello"

    @pytest.mark.asyncio
    async def test_output_variables_default(self) -> None:
        config = {
            "output_variables": [
                {"name": "query", "type": "text", "default": "fallback"},
            ],
        }
        executor = StartNodeExecutor("start_1", config)
        result = await executor.execute({"input": {}})
        assert result.success
        assert result.output["query"] == "fallback"

    @pytest.mark.asyncio
    async def test_passthrough_fallback(self) -> None:
        executor = StartNodeExecutor("start_1", {})
        result = await executor.execute({"input": {"user": "Alice"}})
        assert result.success
        assert result.output == {"input": {"user": "Alice"}}

    @pytest.mark.asyncio
    async def test_required_missing_from_input_fails(self) -> None:
        """必填变量未提供且无默认值 → 失败。"""
        config = {
            "output_variables": [
                {"name": "query", "type": "text", "required": True},
            ],
        }
        executor = StartNodeExecutor("start_1", config)
        result = await executor.execute({"input": {}})
        assert not result.success
        assert "必填变量缺失" in result.error_message
        assert "query" in result.error_message

    @pytest.mark.asyncio
    async def test_required_empty_string_fails(self) -> None:
        """必填变量传入空字符串 → 视为缺失。"""
        config = {
            "output_variables": [
                {"name": "query", "type": "text", "required": True},
            ],
        }
        executor = StartNodeExecutor("start_1", config)
        result = await executor.execute({"input": {"query": ""}})
        assert not result.success
        assert "query" in result.error_message

    @pytest.mark.asyncio
    async def test_required_satisfied_by_default_value(self) -> None:
        """必填变量未传入但有 constraints.default_value → 通过。"""
        config = {
            "output_variables": [
                {
                    "name": "query",
                    "type": "text",
                    "constraints": {"required": True, "default_value": "fallback"},
                },
            ],
        }
        executor = StartNodeExecutor("start_1", config)
        result = await executor.execute({"input": {}})
        assert result.success
        assert result.output["query"] == "fallback"

    @pytest.mark.asyncio
    async def test_required_from_constraints_frontend_schema(self) -> None:
        """前端实际保存格式：required 在 constraints 里，default_value 也在 constraints 里。"""
        config = {
            "output_variables": [
                {
                    "name": "user_name",
                    "type": "text",
                    "label": "用户名",
                    "constraints": {"required": True, "max_length": 100},
                },
                {
                    "name": "mode",
                    "type": "text",
                    "constraints": {"required": False, "default_value": "fast"},
                },
            ],
        }
        executor = StartNodeExecutor("start_1", config)
        # 缺 user_name → 失败
        result = await executor.execute({"input": {"mode": "slow"}})
        assert not result.success
        assert "user_name" in result.error_message
        # mode 有默认值，不会出现在缺失列表
        assert "mode" not in result.error_message

    @pytest.mark.asyncio
    async def test_optional_missing_succeeds_with_none(self) -> None:
        """可选变量缺失 → 成功，值为 None。"""
        config = {
            "output_variables": [
                {"name": "extra", "type": "text"},
            ],
        }
        executor = StartNodeExecutor("start_1", config)
        result = await executor.execute({"input": {}})
        assert result.success
        assert result.output["extra"] is None

    @pytest.mark.asyncio
    async def test_file_type_no_required_field(self) -> None:
        """file 类型无 required 字段 → 默认 optional，缺失也成功。"""
        config = {
            "output_variables": [
                {
                    "name": "attachment",
                    "type": "file",
                    "constraints": {"allowed_extensions": [".pdf"], "max_size_mb": 10},
                },
            ],
        }
        executor = StartNodeExecutor("start_1", config)
        result = await executor.execute({"input": {}})
        assert result.success
        assert result.output["attachment"] is None

    @pytest.mark.asyncio
    async def test_legacy_top_level_default_still_works(self) -> None:
        """旧 schema：顶层 default 字段仍能识别（向后兼容）。"""
        config = {
            "output_variables": [
                {"name": "query", "type": "text", "default": "legacy_fallback"},
            ],
        }
        executor = StartNodeExecutor("start_1", config)
        result = await executor.execute({"input": {}})
        assert result.success
        assert result.output["query"] == "legacy_fallback"


# ── EndNodeExecutor ──


class TestEndNodeExecutor:
    @pytest.mark.asyncio
    async def test_output_mapping(self) -> None:
        config = {"output_mapping": {"result": "{{ node_1.status }}"}}
        executor = EndNodeExecutor("end_1", config)
        result = await executor.execute({"node_1": {"status": "ok"}})
        assert result.success
        assert result.output == {"result": "ok"}

    @pytest.mark.asyncio
    async def test_default_output(self) -> None:
        executor = EndNodeExecutor("end_1", {})
        result = await executor.execute({})
        assert result.success
        assert result.output == {"status": "completed"}


# ── AgentNodeExecutor ──


class TestAgentNodeExecutor:
    @pytest.mark.asyncio
    async def test_missing_agent_id(self) -> None:
        executor = AgentNodeExecutor("agent_1", {})
        result = await executor.execute({})
        assert not result.success
        assert "agent_id" in result.error_message

    @pytest.mark.asyncio
    @patch("app.db.mongodb.get_database", new_callable=MagicMock)
    @patch("app.engine.agent.builder.build_agent_graph", new_callable=AsyncMock)
    async def test_agent_not_found(self, mock_build: AsyncMock, mock_db: MagicMock) -> None:
        mock_collection = MagicMock()
        mock_collection.find_one = AsyncMock(return_value=None)
        mock_db.return_value.__getitem__ = lambda self, key: mock_collection

        executor = AgentNodeExecutor("agent_1", {"agent_id": "agent_xxx"})
        result = await executor.execute({})
        assert not result.success
        assert "不存在" in result.error_message

    @pytest.mark.asyncio
    @patch("app.db.mongodb.get_database", new_callable=MagicMock)
    @patch("app.engine.agent.builder.build_agent_graph", new_callable=AsyncMock)
    async def test_normal_execution(self, mock_build: AsyncMock, mock_db: MagicMock) -> None:
        mock_collection = MagicMock()
        mock_collection.find_one = AsyncMock(
            return_value={"_id": "agent_xxx", "prompt_slots": {"role": "R", "task": "T"}},
        )
        mock_db.return_value.__getitem__ = lambda self, key: mock_collection

        mock_graph = AsyncMock()
        mock_graph.ainvoke = AsyncMock(return_value={"messages": [{"role": "assistant", "content": "response text"}]})
        mock_build.return_value = mock_graph

        executor = AgentNodeExecutor("agent_1", {"agent_id": "agent_xxx"})
        result = await executor.execute({})
        assert result.success
        assert result.output["response"] == "response text"

    @pytest.mark.asyncio
    @patch("app.db.mongodb.get_database", new_callable=MagicMock)
    @patch("app.engine.agent.builder.build_agent_graph", new_callable=AsyncMock)
    async def test_timeout(self, mock_build: AsyncMock, mock_db: MagicMock) -> None:
        mock_collection = MagicMock()
        mock_collection.find_one = AsyncMock(
            return_value={"_id": "agent_xxx", "prompt_slots": {"role": "R", "task": "T"}},
        )
        mock_db.return_value.__getitem__ = lambda self, key: mock_collection

        mock_graph = AsyncMock()
        mock_graph.ainvoke = AsyncMock(side_effect=asyncio.TimeoutError())
        mock_build.return_value = mock_graph

        executor = AgentNodeExecutor("agent_1", {"agent_id": "agent_xxx", "timeout_ms": 100})
        result = await executor.execute({})
        assert not result.success
        assert "超时" in result.error_message

    @pytest.mark.asyncio
    @patch("app.db.mongodb.get_database", new_callable=MagicMock)
    @patch("app.engine.agent.builder.build_agent_graph", new_callable=AsyncMock)
    async def test_retry_success(self, mock_build: AsyncMock, mock_db: MagicMock) -> None:
        mock_collection = MagicMock()
        mock_collection.find_one = AsyncMock(
            return_value={"_id": "agent_xxx", "prompt_slots": {"role": "R", "task": "T"}},
        )
        mock_db.return_value.__getitem__ = lambda self, key: mock_collection

        mock_graph = AsyncMock()
        mock_graph.ainvoke = AsyncMock(
            side_effect=[
                Exception("LLM error"),
                {"messages": [{"role": "assistant", "content": "ok"}]},
            ],
        )
        mock_build.return_value = mock_graph

        executor = AgentNodeExecutor(
            "agent_1",
            {"agent_id": "agent_xxx", "max_retry": 1, "retry_delay_ms": 10},
        )
        result = await executor.execute({})
        assert result.success
        assert result.output["response"] == "ok"

    @pytest.mark.asyncio
    @patch("app.db.mongodb.get_database", new_callable=MagicMock)
    @patch("app.engine.agent.builder.build_agent_graph", new_callable=AsyncMock)
    async def test_retry_exhausted(self, mock_build: AsyncMock, mock_db: MagicMock) -> None:
        mock_collection = MagicMock()
        mock_collection.find_one = AsyncMock(
            return_value={"_id": "agent_xxx", "prompt_slots": {"role": "R", "task": "T"}},
        )
        mock_db.return_value.__getitem__ = lambda self, key: mock_collection

        mock_graph = AsyncMock()
        mock_graph.ainvoke = AsyncMock(side_effect=Exception("persistent error"))
        mock_build.return_value = mock_graph

        executor = AgentNodeExecutor(
            "agent_1",
            {"agent_id": "agent_xxx", "max_retry": 2, "retry_delay_ms": 10},
        )
        result = await executor.execute({})
        assert not result.success
        assert "persistent error" in result.error_message

    @pytest.mark.asyncio
    @patch("app.db.mongodb.get_database", new_callable=MagicMock)
    @patch("app.engine.agent.builder.build_agent_graph", new_callable=AsyncMock)
    async def test_llm_exception(self, mock_build: AsyncMock, mock_db: MagicMock) -> None:
        mock_collection = MagicMock()
        mock_collection.find_one = AsyncMock(
            return_value={"_id": "agent_xxx", "prompt_slots": {"role": "R", "task": "T"}},
        )
        mock_db.return_value.__getitem__ = lambda self, key: mock_collection

        mock_graph = AsyncMock()
        mock_graph.ainvoke = AsyncMock(side_effect=RuntimeError("LLM crashed"))
        mock_build.return_value = mock_graph

        executor = AgentNodeExecutor("agent_1", {"agent_id": "agent_xxx"})
        result = await executor.execute({})
        assert not result.success
        assert "LLM crashed" in result.error_message


# ── ToolNodeExecutor ──


class TestToolNodeExecutor:
    @pytest.mark.asyncio
    async def test_missing_tool_id(self) -> None:
        executor = ToolNodeExecutor("tool_1", {})
        result = await executor.execute({})
        assert not result.success
        assert "tool_id" in result.error_message

    @pytest.mark.asyncio
    @patch("app.db.mongodb.get_database", new_callable=MagicMock)
    async def test_tool_not_found(self, mock_db: MagicMock) -> None:
        mock_collection = MagicMock()
        mock_collection.find_one = AsyncMock(return_value=None)
        mock_db.return_value.__getitem__ = lambda self, key: mock_collection

        executor = ToolNodeExecutor("tool_1", {"tool_id": "tool_xxx"})
        result = await executor.execute({})
        assert not result.success
        assert "不存在" in result.error_message

    @pytest.mark.asyncio
    @patch("app.db.mongodb.get_database", new_callable=MagicMock)
    async def test_non_mcp_tool(self, mock_db: MagicMock) -> None:
        mock_collection = MagicMock()
        mock_collection.find_one = AsyncMock(
            return_value={"_id": "tool_xxx", "name": "my_tool", "source": "markdown", "description": "desc", "instructions": "do stuff"},
        )
        mock_db.return_value.__getitem__ = lambda self, key: mock_collection

        executor = ToolNodeExecutor("tool_1", {"tool_id": "tool_xxx"})
        result = await executor.execute({})
        assert result.success
        assert result.output["tool_name"] == "my_tool"
        assert result.output["note"] == "工具的完整执行由 Agent 推理循环处理"

    @pytest.mark.asyncio
    @patch("app.engine.tool.mcp_tool_cache.get_mcp_tools_cached", new_callable=AsyncMock)
    @patch("app.db.mongodb.get_database", new_callable=MagicMock)
    async def test_mcp_normal(self, mock_db: MagicMock, mock_cache: AsyncMock) -> None:
        mock_collection = MagicMock()
        mock_collection.find_one = AsyncMock(
            return_value={"_id": "tool_xxx", "name": "my_tool", "source": "mcp", "mcp_connection_id": "conn_1"},
        )
        mock_db.return_value.__getitem__ = lambda self, key: mock_collection

        mock_tool = MagicMock()
        mock_tool.name = "my_tool"
        mock_tool.ainvoke = AsyncMock(return_value={"data": "result"})
        mock_cache.return_value = [mock_tool]

        executor = ToolNodeExecutor("tool_1", {"tool_id": "tool_xxx"})
        result = await executor.execute({})
        assert result.success
        assert result.output["result"] == {"data": "result"}

    @pytest.mark.asyncio
    @patch("app.engine.tool.mcp_tool_cache.get_mcp_tools_cached", new_callable=AsyncMock)
    @patch("app.db.mongodb.get_database", new_callable=MagicMock)
    async def test_mcp_timeout(self, mock_db: MagicMock, mock_cache: AsyncMock) -> None:
        mock_collection = MagicMock()
        mock_collection.find_one = AsyncMock(
            return_value={"_id": "tool_xxx", "name": "my_tool", "source": "mcp", "mcp_connection_id": "conn_1"},
        )
        mock_db.return_value.__getitem__ = lambda self, key: mock_collection

        mock_tool = MagicMock()
        mock_tool.name = "my_tool"
        mock_tool.ainvoke = AsyncMock(side_effect=asyncio.TimeoutError())
        mock_cache.return_value = [mock_tool]

        executor = ToolNodeExecutor("tool_1", {"tool_id": "tool_xxx", "timeout_ms": 100})
        result = await executor.execute({})
        assert not result.success
        assert "超时" in result.error_message

    @pytest.mark.asyncio
    @patch("app.engine.tool.mcp_tool_cache.get_mcp_tools_cached", new_callable=AsyncMock)
    @patch("app.db.mongodb.get_database", new_callable=MagicMock)
    async def test_mcp_retry_success(self, mock_db: MagicMock, mock_cache: AsyncMock) -> None:
        mock_collection = MagicMock()
        mock_collection.find_one = AsyncMock(
            return_value={"_id": "tool_xxx", "name": "my_tool", "source": "mcp", "mcp_connection_id": "conn_1"},
        )
        mock_db.return_value.__getitem__ = lambda self, key: mock_collection

        mock_tool = MagicMock()
        mock_tool.name = "my_tool"
        mock_tool.ainvoke = AsyncMock(
            side_effect=[asyncio.TimeoutError(), {"data": "ok"}],
        )
        mock_cache.return_value = [mock_tool]

        executor = ToolNodeExecutor(
            "tool_1",
            {"tool_id": "tool_xxx", "timeout_ms": 100, "retry_policy": {"max_retries": 1, "backoff_ms": 10}},
        )
        result = await executor.execute({})
        assert result.success
        assert result.output["result"] == {"data": "ok"}

    @pytest.mark.asyncio
    @patch("app.engine.tool.mcp_tool_cache.get_mcp_tools_cached", new_callable=AsyncMock)
    @patch("app.db.mongodb.get_database", new_callable=MagicMock)
    async def test_mcp_retry_exhausted(self, mock_db: MagicMock, mock_cache: AsyncMock) -> None:
        mock_collection = MagicMock()
        mock_collection.find_one = AsyncMock(
            return_value={"_id": "tool_xxx", "name": "my_tool", "source": "mcp", "mcp_connection_id": "conn_1"},
        )
        mock_db.return_value.__getitem__ = lambda self, key: mock_collection

        mock_tool = MagicMock()
        mock_tool.name = "my_tool"
        mock_tool.ainvoke = AsyncMock(side_effect=asyncio.TimeoutError())
        mock_cache.return_value = [mock_tool]

        executor = ToolNodeExecutor(
            "tool_1",
            {"tool_id": "tool_xxx", "timeout_ms": 100, "retry_policy": {"max_retries": 2, "backoff_ms": 10}},
        )
        result = await executor.execute({})
        assert not result.success
        assert "超时" in result.error_message

    @pytest.mark.asyncio
    @patch("app.db.mongodb.get_database", new_callable=MagicMock)
    async def test_mcp_missing_connection_id(self, mock_db: MagicMock) -> None:
        mock_collection = MagicMock()
        mock_collection.find_one = AsyncMock(
            return_value={"_id": "tool_xxx", "name": "my_tool", "source": "mcp"},
        )
        mock_db.return_value.__getitem__ = lambda self, key: mock_collection

        executor = ToolNodeExecutor("tool_1", {"tool_id": "tool_xxx"})
        result = await executor.execute({})
        assert not result.success
        assert "connection_id" in result.error_message


# ── GatewayNodeExecutor ──


class TestGatewayNodeExecutor:
    @pytest.mark.asyncio
    async def test_condition_match(self) -> None:
        config = {
            "conditions": [
                {"expression": "{{ node_1.status }}", "expected": "ok", "target": "node_3"},
            ],
            "default_branch": "node_5",
        }
        executor = GatewayNodeExecutor("gw_1", config)
        result = await executor.execute({"node_1": {"status": "ok"}})
        assert result.success
        assert result.selected_branch == "node_3"

    @pytest.mark.asyncio
    async def test_no_match_fallback(self) -> None:
        config = {
            "conditions": [
                {"expression": "{{ node_1.status }}", "expected": "ok", "target": "node_3"},
            ],
            "default_branch": "node_5",
        }
        executor = GatewayNodeExecutor("gw_1", config)
        result = await executor.execute({"node_1": {"status": "fail"}})
        assert result.success
        assert result.selected_branch == "node_5"

    @pytest.mark.asyncio
    async def test_condition_exception_continues(self) -> None:
        config = {
            "conditions": [
                {"expression": "{{ bad_expr }}", "expected": "ok", "target": "node_3"},
                {"expression": "{{ node_1.status }}", "expected": "ok", "target": "node_4"},
            ],
            "default_branch": "node_5",
        }
        executor = GatewayNodeExecutor("gw_1", config)
        result = await executor.execute({"node_1": {"status": "ok"}})
        assert result.success
        assert result.selected_branch == "node_4"

    @pytest.mark.asyncio
    async def test_type_comparison_int(self) -> None:
        config = {
            "conditions": [
                {"expression": "{{ node_1.count }}", "expected": 42, "target": "node_3"},
            ],
            "default_branch": "node_5",
        }
        executor = GatewayNodeExecutor("gw_1", config)
        result = await executor.execute({"node_1": {"count": 42}})
        assert result.success
        assert result.selected_branch == "node_3"

    @pytest.mark.asyncio
    async def test_bool_condition(self) -> None:
        config = {
            "conditions": [
                {"expression": "{{ node_1.flag }}", "expected": True, "target": "node_3"},
            ],
            "default_branch": "node_5",
        }
        executor = GatewayNodeExecutor("gw_1", config)
        result = await executor.execute({"node_1": {"flag": True}})
        assert result.success
        assert result.selected_branch == "node_3"


# ── ParallelNodeExecutor ──


class TestParallelNodeExecutor:
    @pytest.mark.asyncio
    async def test_branches_parsing(self) -> None:
        config = {
            "branches": [
                {"id": "b1", "start_node": "node_a"},
                {"id": "b2", "start_node": "node_b"},
            ],
        }
        executor = ParallelNodeExecutor("par_1", config)
        result = await executor.execute({})
        assert result.success
        assert result.output["branches"] == ["b1", "b2"]
        assert result.output["start_nodes"] == {"b1": "node_a", "b2": "node_b"}

    @pytest.mark.asyncio
    async def test_join_strategy_config(self) -> None:
        config = {
            "branches": [{"id": "b1", "start_node": "node_a"}],
            "join_strategy": "any",
        }
        executor = ParallelNodeExecutor("par_1", config)
        result = await executor.execute({})
        assert result.output["join_strategy"] == "any"

    @pytest.mark.asyncio
    async def test_join_count_config(self) -> None:
        config = {
            "branches": [{"id": "b1", "start_node": "node_a"}],
            "join_strategy": "n-of-m",
            "join_count": 2,
        }
        executor = ParallelNodeExecutor("par_1", config)
        result = await executor.execute({})
        assert result.output["join_count"] == 2


# ── SubflowNodeExecutor ──


class TestSubflowNodeExecutor:
    @pytest.mark.asyncio
    async def test_missing_workflow_id(self) -> None:
        executor = SubflowNodeExecutor("sub_1", {})
        result = await executor.execute({})
        assert not result.success
        assert "workflow_id" in result.error_message

    @pytest.mark.asyncio
    @patch("app.db.mongodb.get_database", new_callable=MagicMock)
    async def test_workflow_not_found(self, mock_db: MagicMock) -> None:
        mock_collection = MagicMock()
        mock_collection.find_one = AsyncMock(return_value=None)
        mock_db.return_value.__getitem__ = lambda self, key: mock_collection

        executor = SubflowNodeExecutor("sub_1", {"workflow_id": "wf_xxx"})
        result = await executor.execute({})
        assert not result.success
        assert "不存在" in result.error_message

    @pytest.mark.asyncio
    @patch("app.db.mongodb.get_database", new_callable=MagicMock)
    async def test_normal_subflow(self, mock_db: MagicMock) -> None:
        mock_wf_collection = MagicMock()
        mock_wf_collection.find_one = AsyncMock(return_value={"_id": "wf_xxx", "nodes": [], "edges": []})
        mock_db.return_value.__getitem__ = lambda self, key: mock_wf_collection

        with patch("app.engine.workflow.engine.WorkflowEngine") as mock_engine_cls:
            mock_pool = MagicMock()
            mock_pool.get_all.return_value = {"end_1": {"status": "done"}}
            mock_engine_instance = MagicMock()
            mock_engine_instance._pool = mock_pool
            mock_engine_instance.execute_task = AsyncMock(return_value={"end_1": {"status": "done"}})
            mock_engine_cls.return_value = mock_engine_instance

            executor = SubflowNodeExecutor("sub_1", {"workflow_id": "wf_xxx"})
            result = await executor.execute({})
            assert result.success
            assert "child_task_id" in result.output
            assert result.output["workflow_id"] == "wf_xxx"

    @pytest.mark.asyncio
    @patch("app.db.mongodb.get_database", new_callable=MagicMock)
    async def test_subflow_timeout(self, mock_db: MagicMock) -> None:
        mock_wf_collection = MagicMock()
        mock_wf_collection.find_one = AsyncMock(return_value={"_id": "wf_xxx", "nodes": [], "edges": []})
        mock_db.return_value.__getitem__ = lambda self, key: mock_wf_collection

        with patch("app.engine.workflow.engine.WorkflowEngine") as mock_engine_cls:
            mock_engine_instance = MagicMock()
            mock_engine_instance._pool = None
            mock_engine_instance.execute_task = AsyncMock(side_effect=asyncio.TimeoutError())
            mock_engine_cls.return_value = mock_engine_instance

            executor = SubflowNodeExecutor("sub_1", {"workflow_id": "wf_xxx", "timeout_ms": 100})
            result = await executor.execute({})
            assert not result.success
            assert "超时" in result.error_message

    @pytest.mark.asyncio
    @patch("app.db.mongodb.get_database", new_callable=MagicMock)
    async def test_subflow_failure(self, mock_db: MagicMock) -> None:
        mock_wf_collection = MagicMock()
        mock_wf_collection.find_one = AsyncMock(return_value={"_id": "wf_xxx", "nodes": [], "edges": []})
        mock_db.return_value.__getitem__ = lambda self, key: mock_wf_collection

        with patch("app.engine.workflow.engine.WorkflowEngine") as mock_engine_cls:
            mock_engine_instance = MagicMock()
            mock_engine_instance.execute_task = AsyncMock(side_effect=RuntimeError("child error"))
            mock_engine_cls.return_value = mock_engine_instance

            executor = SubflowNodeExecutor("sub_1", {"workflow_id": "wf_xxx"})
            result = await executor.execute({})
            assert not result.success
            assert "child error" in result.error_message


# ── Factory ──


class TestGetNodeExecutor:
    def test_start_type(self) -> None:
        executor = get_node_executor("start", "n1", {})
        assert isinstance(executor, StartNodeExecutor)

    def test_end_type(self) -> None:
        executor = get_node_executor("end", "n1", {})
        assert isinstance(executor, EndNodeExecutor)

    def test_agent_type(self) -> None:
        executor = get_node_executor("agent", "n1", {})
        assert isinstance(executor, AgentNodeExecutor)

    def test_unknown_type_raises(self) -> None:
        with pytest.raises(ValueError, match="未知的节点类型"):
            get_node_executor("unknown", "n1", {})
