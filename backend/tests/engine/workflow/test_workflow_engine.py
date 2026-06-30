"""WorkflowEngine integration tests — mock TaskService and node executors."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.engine.workflow.engine import WorkflowEngine
from app.models.task import TaskStatus
from langchain_core.messages import AIMessage


def _make_workflow(nodes: list[dict], edges: list[dict]) -> dict:
    """Helper to create a workflow document."""
    return {"nodes": nodes, "edges": edges}


def _make_task(input_data: dict | None = None) -> dict:
    """Helper to create a task document."""
    return {
        "_id": "task_001",
        "input": input_data or {},
        "workflow_id": "wf_001",
        # Story 4-15: AgentNodeExecutor needs the task owner to set up a
        # per-task workspace; WorkflowEngine passes it through to the
        # executor constructor.
        "created_by": "user_test",
    }


def _make_node(node_id: str, node_type: str, config: dict | None = None) -> dict:
    """Helper to create a node."""
    return {"node_id": node_id, "type": node_type, "config": config or {}, "label": node_id}


def _make_edge(source: str, target: str, condition: str | None = None) -> dict:
    """Helper to create an edge."""
    edge: dict = {"source": source, "target": target}
    if condition:
        edge["condition"] = condition
    return edge


def _make_next_node(target: str, label: str = "", condition: str | None = None) -> dict:
    """Helper to create a next_nodes entry (new routing format)."""
    entry: dict = {"target": target, "label": label, "condition": None}
    if condition:
        entry["condition"] = condition
    return entry


@patch("app.engine.workflow.engine.TaskService", new_callable=MagicMock)
class TestWorkflowEngine:
    """Integration tests for WorkflowEngine."""

    async def test_start_to_end(self, mock_ts: MagicMock) -> None:
        """start → end simplest chain."""
        mock_ts.transition_task = AsyncMock()
        mock_ts.append_timeline_event = AsyncMock()

        wf = _make_workflow(
            nodes=[
                _make_node("start_1", "start"),
                _make_node("end_1", "end"),
            ],
            edges=[_make_edge("start_1", "end_1")],
        )
        engine = WorkflowEngine()
        result = await engine.execute_task(_make_task(), wf)
        assert "start_1" in result
        assert "end_1" in result
        mock_ts.transition_task.assert_called()

    async def test_start_agent_end(self, mock_ts: MagicMock) -> None:
        """start → agent → end chain."""
        mock_ts.transition_task = AsyncMock()
        mock_ts.append_timeline_event = AsyncMock()

        wf = _make_workflow(
            nodes=[
                _make_node("start_1", "start"),
                _make_node("agent_1", "agent", {"agent_id": "agent_xxx"}),
                _make_node("end_1", "end"),
            ],
            edges=[
                _make_edge("start_1", "agent_1"),
                _make_edge("agent_1", "end_1"),
            ],
        )

        # Mock build_agent_graph, get_database, WorkspaceManager (Story 4-15)
        # and FileService so the agent node's task-workspace setup and
        # output-file scan do not touch the real filesystem / MongoDB.
        with patch("app.engine.agent.builder.build_agent_graph", new_callable=AsyncMock) as mock_build, \
             patch("app.db.mongodb.get_database", new_callable=MagicMock) as mock_db, \
             patch("app.engine.tool.workspace.WorkspaceManager") as mock_ws_mgr, \
             patch("app.services.file_service.FileService") as mock_file_svc_cls:
            mock_collection = MagicMock()
            mock_collection.find_one = AsyncMock(return_value={
                "_id": "agent_xxx",
                "prompt_slots": {
                    "role": "You are a helpful assistant.",
                    "task": "Respond to the user.",
                },
            })
            mock_db.return_value.__getitem__ = lambda self, key: mock_collection

            # Story 4-15: provide a virtual task workspace whose output
            # directory reports as not existing → no files to register.
            mock_ws = MagicMock()
            mock_ws.output_dir.exists.return_value = False
            mock_ws_mgr.create_task_workspace.return_value = mock_ws

            # FileService is consulted to dedupe by sha256. With an empty
            # output/ the existing_docs query still runs — mock it.
            mock_file_svc = MagicMock()
            mock_file_svc._file_refs.return_value.find.return_value.to_list = AsyncMock(return_value=[])
            mock_file_svc_cls.return_value = mock_file_svc

            mock_graph = AsyncMock()
            mock_graph.ainvoke = AsyncMock(return_value={"messages": [{"role": "assistant", "content": "hi"}]})
            mock_build.return_value = mock_graph

            engine = WorkflowEngine()
            await engine.execute_task(_make_task(), wf)

    async def test_gateway_branching(self, mock_ts: MagicMock) -> None:
        """start → gateway → [agent_a | agent_b] conditional branch."""
        mock_ts.transition_task = AsyncMock()
        mock_ts.append_timeline_event = AsyncMock()

        wf = _make_workflow(
            nodes=[
                _make_node("start_1", "start"),
                _make_node("gw_1", "gateway", {
                    "conditions": [
                        {"expression": "{{ start_1.result }}", "expected": "go_a", "target": "agent_a"},
                    ],
                    "default_branch": "agent_b",
                }),
                _make_node("agent_a", "end"),
                _make_node("agent_b", "end"),
            ],
            edges=[
                _make_edge("start_1", "gw_1"),
            ],
        )
        engine = WorkflowEngine()
        result = await engine.execute_task(_make_task({"result": "go_a"}), wf)
        # Gateway should select agent_a branch
        assert "gw_1" in result

    async def test_parallel_execution(self, mock_ts: MagicMock) -> None:
        """start → parallel → [node_a, node_b] concurrent branches."""
        mock_ts.transition_task = AsyncMock()
        mock_ts.append_timeline_event = AsyncMock()

        wf = _make_workflow(
            nodes=[
                _make_node("start_1", "start"),
                _make_node("par_1", "parallel", {
                    "branches": [
                        {"id": "b1", "start_node": "node_a"},
                        {"id": "b2", "start_node": "node_b"},
                    ],
                    "join_strategy": "all",
                }),
                _make_node("node_a", "end"),
                _make_node("node_b", "end"),
            ],
            edges=[_make_edge("start_1", "par_1")],
        )
        engine = WorkflowEngine()
        result = await engine.execute_task(_make_task(), wf)
        assert "par_1" in result
        assert "node_a" in result
        assert "node_b" in result

    async def test_human_pause(self, mock_ts: MagicMock) -> None:
        """Human node triggers WorkflowPausedError."""
        mock_ts.transition_task = AsyncMock()
        mock_ts.append_timeline_event = AsyncMock()

        wf = _make_workflow(
            nodes=[
                _make_node("start_1", "start"),
                _make_node("human_1", "human", {
                    "title": "Approval",
                    "timeout_ms": 0,
                }),
            ],
            edges=[_make_edge("start_1", "human_1")],
        )
        engine = WorkflowEngine()
        result = await engine.execute_task(_make_task(), wf)
        # Should not raise — WorkflowPausedError is caught gracefully
        assert "start_1" in result

    async def test_node_failure_propagation(self, mock_ts: MagicMock) -> None:
        """Node failure raises WorkflowNodeError and transitions to failed."""
        mock_ts.transition_task = AsyncMock()
        mock_ts.append_timeline_event = AsyncMock()

        wf = _make_workflow(
            nodes=[
                _make_node("start_1", "start"),
                _make_node("agent_1", "agent", {"agent_id": ""}),  # Missing agent_id
                _make_node("end_1", "end"),
            ],
            edges=[
                _make_edge("start_1", "agent_1"),
                _make_edge("agent_1", "end_1"),
            ],
        )
        engine = WorkflowEngine()
        result = await engine.execute_task(_make_task(), wf)
        # Should catch WorkflowNodeError and mark task as failed
        assert result is not None

    async def test_find_start_nodes(self, mock_ts: MagicMock) -> None:
        """_find_start_nodes returns nodes with no incoming edges."""
        mock_ts.transition_task = AsyncMock()
        mock_ts.append_timeline_event = AsyncMock()

        wf = _make_workflow(
            nodes=[
                _make_node("start_1", "start"),
                _make_node("end_1", "end"),
            ],
            edges=[_make_edge("start_1", "end_1")],
        )
        engine = WorkflowEngine()
        await engine.execute_task(_make_task(), wf)
        assert engine._find_start_nodes() == ["start_1"]

    async def test_find_end_nodes(self, mock_ts: MagicMock) -> None:
        """_find_end_nodes returns nodes with no outgoing edges."""
        mock_ts.transition_task = AsyncMock()
        mock_ts.append_timeline_event = AsyncMock()

        wf = _make_workflow(
            nodes=[
                _make_node("start_1", "start"),
                _make_node("end_1", "end"),
            ],
            edges=[_make_edge("start_1", "end_1")],
        )
        engine = WorkflowEngine()
        await engine.execute_task(_make_task(), wf)
        assert engine._find_end_nodes() == ["end_1"]

    async def test_no_start_node_error(self, mock_ts: MagicMock) -> None:
        """Workflow without any start-type node should fail gracefully."""
        mock_ts.transition_task = AsyncMock()
        mock_ts.append_timeline_event = AsyncMock()

        # No node has type="start" — should raise "workflow has no start node"
        wf = _make_workflow(
            nodes=[_make_node("agent_1", "agent")],
            edges=[],
        )
        engine = WorkflowEngine()
        result = await engine.execute_task(_make_task(), wf)
        # Should return empty dict (error caught internally)
        assert result is not None

    async def test_start_to_end_via_next_nodes(self, mock_ts: MagicMock) -> None:
        """Start -> End using next_nodes instead of edges."""
        mock_ts.transition_task = AsyncMock()
        mock_ts.append_timeline_event = AsyncMock()

        wf = _make_workflow(
            nodes=[
                _make_node("start_1", "start", config={
                    "next_nodes": [_make_next_node("end_1")],
                }),
                _make_node("end_1", "end"),
            ],
            edges=[],  # No edges — routing via next_nodes
        )
        engine = WorkflowEngine()
        result = await engine.execute_task(_make_task(), wf)
        assert result is not None
        # Task should be marked COMPLETED
        mock_ts.transition_task.assert_called()
        last_call = mock_ts.transition_task.call_args
        assert last_call.kwargs.get("to_status") == TaskStatus.COMPLETED

    async def test_conditional_next_nodes(self, mock_ts: MagicMock) -> None:
        """Conditional routing via next_nodes with condition expressions."""
        mock_ts.transition_task = AsyncMock()
        mock_ts.append_timeline_event = AsyncMock()

        wf = _make_workflow(
            nodes=[
                _make_node("start_1", "start", config={
                    "next_nodes": [_make_next_node("agent_1")],
                }),
                _make_node("agent_1", "agent", config={
                    "agent_id": "test-agent",
                    "input_query": "hello",
                    "next_nodes": [
                        _make_next_node("end_1", label="成功"),
                        _make_next_node("end_2", label="失败", condition="{{ agent_1.status }} == 'error'"),
                    ],
                }),
                _make_node("end_1", "end"),
                _make_node("end_2", "end"),
            ],
            edges=[],
        )

        with patch(
            "app.engine.agent.builder.build_agent_graph",
            new_callable=AsyncMock,
        ) as mock_build:
            mock_graph = AsyncMock()
            mock_graph.invoke.return_value = {
                "messages": [AIMessage(content="result")],
            }
            mock_build.return_value = mock_graph

            engine = WorkflowEngine()
            result = await engine.execute_task(_make_task(), wf)

        assert result is not None


# Make all async tests work with pytest-asyncio
for attr_name in dir(TestWorkflowEngine):
    if attr_name.startswith("test_"):
        method = getattr(TestWorkflowEngine, attr_name)
        if asyncio.iscoroutinefunction(method):
            setattr(TestWorkflowEngine, attr_name, pytest.mark.asyncio(method))
