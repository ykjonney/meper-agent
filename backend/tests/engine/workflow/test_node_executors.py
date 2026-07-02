"""Node executor unit tests — all external dependencies mocked."""
from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.engine.workflow.node_executor import (
    AgentNodeExecutor,
    EndNodeExecutor,
    GatewayNodeExecutor,
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

    # ── file 类型 StartNodeExecutor 集成 ──

    @pytest.mark.asyncio
    async def test_file_type_valid_single(self) -> None:
        """file 类型正常解析 → 输出包含文件元信息 dict。"""
        from unittest.mock import AsyncMock, patch

        from app.models.file_library import FileConsumerKind, FileRef

        fake_ref = FileRef(
            id="file_OK",
            owner_user_id="user_X",
            storage_key="user_X/files/file_OK",
            name="data.csv",
            size=512,
            mime_type="text/csv",
            sha256="deadbeef",
            origin_kind=FileConsumerKind.USER_LIBRARY,
            origin_id="user_X",
        )
        config = {
            "output_variables": [
                {
                    "name": "dataset",
                    "type": "file",
                    "constraints": {"required": True},
                },
            ],
        }
        executor = StartNodeExecutor("start_1", config)
        with patch("app.engine.workflow.file_validator._get_file_service") as mock_svc:
            mock_svc.return_value.get = AsyncMock(return_value=fake_ref)
            result = await executor.execute({"input": {"dataset": "file_OK"}})
        assert result.success
        out = result.output["dataset"]
        assert out["file_id"] == "file_OK"
        assert out["name"] == "data.csv"
        assert out["size"] == 512

    @pytest.mark.asyncio
    async def test_file_type_required_missing(self) -> None:
        """file 类型 required=True 但未传入 → 必填变量缺失。"""
        config = {
            "output_variables": [
                {
                    "name": "document",
                    "type": "file",
                    "constraints": {"required": True},
                },
            ],
        }
        executor = StartNodeExecutor("start_1", config)
        result = await executor.execute({"input": {}})
        assert not result.success
        assert "document" in result.error_message
        assert "必填变量缺失" in result.error_message

    @pytest.mark.asyncio
    async def test_file_type_validation_error(self) -> None:
        """file 类型验证失败（文件不存在）→ NodeResult 失败。"""
        from unittest.mock import AsyncMock, patch

        config = {
            "output_variables": [
                {
                    "name": "attachment",
                    "type": "file",
                },
            ],
        }
        executor = StartNodeExecutor("start_1", config)
        with patch("app.engine.workflow.file_validator._get_file_service") as mock_svc:
            mock_svc.return_value.get = AsyncMock(return_value=None)
            result = await executor.execute({"input": {"attachment": "file_GONE"}})
        assert not result.success
        assert "attachment" in result.error_message
        assert "不存在" in result.error_message

    @pytest.mark.asyncio
    async def test_file_type_multiple(self) -> None:
        """file 类型 multiple=True → 输出为 list[dict]。"""
        from unittest.mock import AsyncMock, patch

        from app.models.file_library import FileConsumerKind, FileRef

        f1 = FileRef(id="f1", owner_user_id="u", storage_key="u/files/f1", name="a.pdf",
                     size=100, mime_type="application/pdf", sha256="h1",
                     origin_kind=FileConsumerKind.USER_LIBRARY, origin_id="u")
        f2 = FileRef(id="f2", owner_user_id="u", storage_key="u/files/f2", name="b.pdf",
                     size=200, mime_type="application/pdf", sha256="h2",
                     origin_kind=FileConsumerKind.USER_LIBRARY, origin_id="u")
        config = {
            "output_variables": [
                {
                    "name": "files",
                    "type": "file",
                    "constraints": {"multiple": True},
                },
            ],
        }
        executor = StartNodeExecutor("start_1", config)
        with patch("app.engine.workflow.file_validator._get_file_service") as mock_svc:
            mock_svc.return_value.get = AsyncMock(side_effect=[f1, f2])
            result = await executor.execute({"input": {"files": ["f1", "f2"]}})
        assert result.success
        out = result.output["files"]
        assert isinstance(out, list)
        assert len(out) == 2
        assert out[0]["file_id"] == "f1"
        assert out[1]["file_id"] == "f2"


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


class TestAgentNodeExecutorWithTaskWorkspace:
    """Story 4-15: AgentNodeExecutor sets up a per-task workspace, registers
    output files, and resets the workspace context on completion.
    """

    @pytest.mark.asyncio
    @patch("app.db.mongodb.get_database", new_callable=MagicMock)
    @patch("app.engine.agent.builder.build_agent_graph", new_callable=AsyncMock)
    @patch("app.engine.tool.workspace.WorkspaceManager")
    @patch("app.engine.agent.builtin_tools.set_workspace_context")
    @patch("app.engine.agent.builtin_tools.reset_workspace_context")
    @patch("app.services.file_service.FileService")
    async def test_workspace_context_set_and_reset_around_invoke(
        self,
        mock_file_svc_cls: MagicMock,
        mock_reset: MagicMock,
        mock_set: MagicMock,
        mock_ws_mgr: MagicMock,
        mock_build: AsyncMock,
        mock_db: MagicMock
    ) -> None:
        """set_workspace_context is called with the task workspace; reset is
        called in the finally block, even on success."""
        mock_collection = MagicMock()
        mock_collection.find_one = AsyncMock(
            return_value={"_id": "agent_xxx", "prompt_slots": {"role": "R", "task": "T"}}
        )
        mock_db.return_value.__getitem__ = lambda self, key: mock_collection

        mock_graph = MagicMock()
        mock_graph.ainvoke = AsyncMock(
            return_value={"messages": [{"role": "assistant", "content": "done"}]}
        )
        mock_build.return_value = mock_graph

        # Output dir does not exist → no files to register.
        mock_ws = MagicMock()
        mock_ws.output_dir.exists.return_value = False
        mock_ws_mgr.create_task_workspace.return_value = mock_ws
        # Mock file_refs().find() to return empty
        mock_file_svc = MagicMock()
        mock_file_svc._file_refs.return_value.find.return_value.to_list = AsyncMock(return_value=[])
        mock_file_svc_cls.return_value = mock_file_svc

        executor = AgentNodeExecutor(
            "agent_1", {"agent_id": "agent_xxx"}
        )
        result = await executor.execute({"system": {"task_id": "task_1", "user_id": "user_alice"}})

        assert result.success
        # Workspace was created with the right identity.
        mock_ws_mgr.create_task_workspace.assert_called_once_with(
            "user_alice", "task_1"
        )
        # set_workspace_context was called with the task workspace.
        mock_set.assert_called_once_with(mock_ws)
        # reset_workspace_context was called with the token returned by set.
        mock_reset.assert_called_once_with(mock_set.return_value)

    @pytest.mark.asyncio
    @patch("app.db.mongodb.get_database", new_callable=MagicMock)
    @patch("app.engine.agent.builder.build_agent_graph", new_callable=AsyncMock)
    @patch("app.engine.tool.workspace.WorkspaceManager")
    @patch("app.engine.agent.builtin_tools.set_workspace_context")
    @patch("app.engine.agent.builtin_tools.reset_workspace_context")
    @patch("app.services.file_service.FileService")
    async def test_new_files_in_output_registered(
        self,
        mock_file_svc_cls: MagicMock,
        mock_reset: MagicMock,
        mock_set: MagicMock,
        mock_ws_mgr: MagicMock,
        mock_build: AsyncMock,
        mock_db: MagicMock,
        tmp_path: Path
    ) -> None:
        """Files newer than node_start_ts are registered as file_refs.

        The ainvoke callback writes the file *during* the graph call so
        its mtime > node_start_ts; if we wrote it before, mtime would be
        before node_start_ts and the file would be skipped (covered by
        test_old_files_in_output_skipped).
        """
        mock_collection = MagicMock()
        mock_collection.find_one = AsyncMock(
            return_value={"_id": "agent_xxx", "prompt_slots": {"role": "R", "task": "T"}}
        )
        mock_db.return_value.__getitem__ = lambda self, key: mock_collection

        out_dir = tmp_path / "output"
        out_dir.mkdir()

        async def _ainvoke(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
            # File written *during* the graph call → mtime > node_start_ts.
            (out_dir / "report.pdf").write_bytes(b"%PDF-1.4 fake content")
            return {"messages": [{"role": "assistant", "content": "ok"}]}

        mock_graph = MagicMock()
        mock_graph.ainvoke = _ainvoke
        mock_build.return_value = mock_graph

        mock_ws = MagicMock()
        mock_ws.output_dir = out_dir
        mock_ws_mgr.create_task_workspace.return_value = mock_ws

        # Stub FileService to record a create() call.
        mock_fref = MagicMock()
        mock_fref.id = "file_abc"
        mock_fref.name = "report.pdf"
        mock_fref.size = 21
        mock_fref.mime_type = "application/pdf"
        mock_fref.storage_key = "user_alice/files/file_abc"
        mock_file_svc = MagicMock()
        mock_file_svc._file_refs.return_value.find.return_value.to_list = AsyncMock(return_value=[])
        mock_file_svc.create = AsyncMock(return_value=mock_fref)
        mock_file_svc_cls.return_value = mock_file_svc

        executor = AgentNodeExecutor(
            "agent_1", {"agent_id": "agent_xxx"}
        )
        result = await executor.execute({"system": {"task_id": "task_2", "user_id": "user_alice"}})

        assert result.success
        # File was registered.
        mock_file_svc.create.assert_awaited_once()
        kwargs = mock_file_svc.create.await_args.kwargs
        assert kwargs["owner_user_id"] == "user_alice"
        assert kwargs["origin_id"] == "task_2"
        assert kwargs["filename"] == "report.pdf"
        # Output includes the file_id for downstream consumption.
        assert len(result.output["files"]) == 1
        assert result.output["files"][0]["file_id"] == "file_abc"
        assert result.output["files"][0]["name"] == "report.pdf"

    @pytest.mark.asyncio
    @patch("app.db.mongodb.get_database", new_callable=MagicMock)
    @patch("app.engine.agent.builder.build_agent_graph", new_callable=AsyncMock)
    @patch("app.engine.tool.workspace.WorkspaceManager")
    @patch("app.engine.agent.builtin_tools.set_workspace_context")
    @patch("app.engine.agent.builtin_tools.reset_workspace_context")
    @patch("app.services.file_service.FileService")
    async def test_old_files_in_output_skipped(
        self,
        mock_file_svc_cls: MagicMock,
        mock_reset: MagicMock,
        mock_set: MagicMock,
        mock_ws_mgr: MagicMock,
        mock_build: AsyncMock,
        mock_db: MagicMock,
        tmp_path: Path
    ) -> None:
        """Files with mtime before node_start_ts are NOT registered."""
        import os
        import time

        mock_collection = MagicMock()
        mock_collection.find_one = AsyncMock(
            return_value={"_id": "agent_xxx", "prompt_slots": {"role": "R", "task": "T"}}
        )
        mock_db.return_value.__getitem__ = lambda self, key: mock_collection

        mock_graph = MagicMock()
        mock_graph.ainvoke = AsyncMock(
            return_value={"messages": [{"role": "assistant", "content": "ok"}]}
        )
        mock_build.return_value = mock_graph

        out_dir = tmp_path / "output"
        out_dir.mkdir()
        old_file = out_dir / "old.txt"
        old_file.write_text("from previous run")
        # Force mtime to far in the past (before node_start_ts).
        old_mtime = time.time() - 10**6
        os.utime(old_file, (old_mtime, old_mtime))

        mock_ws = MagicMock()
        mock_ws.output_dir = out_dir
        mock_ws_mgr.create_task_workspace.return_value = mock_ws

        mock_file_svc = MagicMock()
        mock_file_svc._file_refs.return_value.find.return_value.to_list = AsyncMock(return_value=[])
        mock_file_svc.create = AsyncMock()
        mock_file_svc_cls.return_value = mock_file_svc

        executor = AgentNodeExecutor(
            "agent_1", {"agent_id": "agent_xxx"}
        )
        result = await executor.execute({"system": {"task_id": "task_1", "user_id": "user_alice"}})

        assert result.success
        # create() must not have been called.
        mock_file_svc.create.assert_not_called()
        # Output files list is empty.
        assert result.output["files"] == []

    @pytest.mark.asyncio
    @patch("app.db.mongodb.get_database", new_callable=MagicMock)
    @patch("app.engine.agent.builder.build_agent_graph", new_callable=AsyncMock)
    @patch("app.engine.tool.workspace.WorkspaceManager")
    @patch("app.engine.agent.builtin_tools.set_workspace_context")
    @patch("app.engine.agent.builtin_tools.reset_workspace_context")
    @patch("app.services.file_service.FileService")
    async def test_duplicate_sha256_not_reregistered(
        self,
        mock_file_svc_cls: MagicMock,
        mock_reset: MagicMock,
        mock_set: MagicMock,
        mock_ws_mgr: MagicMock,
        mock_build: AsyncMock,
        mock_db: MagicMock,
        tmp_path: Path
    ) -> None:
        """Files whose sha256 already exists in file_refs are skipped."""
        import hashlib

        mock_collection = MagicMock()
        mock_collection.find_one = AsyncMock(
            return_value={"_id": "agent_xxx", "prompt_slots": {"role": "R", "task": "T"}}
        )
        mock_db.return_value.__getitem__ = lambda self, key: mock_collection

        mock_graph = MagicMock()
        mock_graph.ainvoke = AsyncMock(
            return_value={"messages": [{"role": "assistant", "content": "ok"}]}
        )
        mock_build.return_value = mock_graph

        out_dir = tmp_path / "output"
        out_dir.mkdir()
        new_file = out_dir / "duplicate.bin"
        new_file.write_bytes(b"same content")
        existing_sha = hashlib.sha256(b"same content").hexdigest()

        mock_ws = MagicMock()
        mock_ws.output_dir = out_dir
        mock_ws_mgr.create_task_workspace.return_value = mock_ws

        # Pre-existing file_ref with same sha256 → must be skipped.
        mock_file_svc = MagicMock()
        mock_file_svc._file_refs.return_value.find.return_value.to_list = AsyncMock(
            return_value=[{"sha256": existing_sha}]
        )
        mock_file_svc.create = AsyncMock()
        mock_file_svc_cls.return_value = mock_file_svc

        executor = AgentNodeExecutor(
            "agent_1", {"agent_id": "agent_xxx"}
        )
        result = await executor.execute({"system": {"task_id": "task_1", "user_id": "user_alice"}})

        assert result.success
        mock_file_svc.create.assert_not_called()
        assert result.output["files"] == []

    @pytest.mark.asyncio
    @patch("app.db.mongodb.get_database", new_callable=MagicMock)
    @patch("app.engine.agent.builder.build_agent_graph", new_callable=AsyncMock)
    @patch("app.engine.tool.workspace.WorkspaceManager")
    @patch("app.engine.agent.builtin_tools.set_workspace_context")
    @patch("app.engine.agent.builtin_tools.reset_workspace_context")
    @patch("app.services.file_service.FileService")
    async def test_reset_workspace_context_called_on_exception(
        self,
        mock_file_svc_cls: MagicMock,
        mock_reset: MagicMock,
        mock_set: MagicMock,
        mock_ws_mgr: MagicMock,
        mock_build: AsyncMock,
        mock_db: MagicMock
    ) -> None:
        """reset_workspace_context is called even when ainvoke raises."""
        mock_collection = MagicMock()
        mock_collection.find_one = AsyncMock(
            return_value={"_id": "agent_xxx", "prompt_slots": {"role": "R", "task": "T"}}
        )
        mock_db.return_value.__getitem__ = lambda self, key: mock_collection

        mock_graph = MagicMock()

        async def _always_fail(*_args: Any, **_kwargs: Any) -> None:
            raise RuntimeError("graph failure")

        mock_graph.ainvoke = _always_fail
        mock_build.return_value = mock_graph

        mock_ws = MagicMock()
        mock_ws.output_dir.exists.return_value = False
        mock_ws_mgr.create_task_workspace.return_value = mock_ws
        mock_file_svc = MagicMock()
        mock_file_svc_cls.return_value = mock_file_svc

        executor = AgentNodeExecutor(
            "agent_1",
            {"agent_id": "agent_xxx", "max_retry": 0}
        )
        result = await executor.execute({"system": {"task_id": "task_1", "user_id": "user_alice"}})

        assert not result.success
        # Context was still reset.
        mock_reset.assert_called_once()

    @pytest.mark.asyncio
    async def test_missing_task_id_and_user_id_returns_error(self) -> None:
        """Without task_id/user_id, executor fails fast with a clear error."""
        executor = AgentNodeExecutor("agent_1", {"agent_id": "agent_xxx"})
        result = await executor.execute({})
        assert not result.success
        assert "system.task_id" in result.error_message
        assert "system.user_id" in result.error_message

    @pytest.mark.asyncio
    async def test_missing_user_id_only_returns_error(self) -> None:
        """user_id missing alone still fails fast."""
        executor = AgentNodeExecutor(
            "agent_1", {"agent_id": "agent_xxx"}
        )
        result = await executor.execute({"system": {"task_id": "task_x"}})
        assert not result.success
        assert "system.user_id" in result.error_message


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
        mock_tool.ainvoke = AsyncMock(side_effect=TimeoutError())
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
            side_effect=[TimeoutError(), {"data": "ok"}],
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
        mock_tool.ainvoke = AsyncMock(side_effect=TimeoutError())
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

    # ── operator + 大小写不敏感 ──

    @pytest.mark.asyncio
    async def test_operator_case_insensitive_eq(self) -> None:
        """== 对字符串大小写不敏感：'APPROVE' 匹配 expected 'approve'。"""
        config = {
            "conditions": [
                {"expression": "{{ human_1.decision }}", "operator": "==", "expected": "approve", "target": "node_3"},
            ],
            "default_branch": "node_5",
        }
        executor = GatewayNodeExecutor("gw_1", config)
        result = await executor.execute({"human_1": {"decision": "APPROVE"}})
        assert result.success
        assert result.selected_branch == "node_3"

    @pytest.mark.asyncio
    async def test_operator_case_insensitive_ne(self) -> None:
        """!= 对字符串大小写不敏感：'Approve' != 'reject' → 命中。"""
        config = {
            "conditions": [
                {"expression": "{{ human_1.decision }}", "operator": "!=", "expected": "reject", "target": "node_3"},
            ],
            "default_branch": "node_5",
        }
        executor = GatewayNodeExecutor("gw_1", config)
        result = await executor.execute({"human_1": {"decision": "Approve"}})
        assert result.success
        assert result.selected_branch == "node_3"

    @pytest.mark.asyncio
    async def test_operator_gt(self) -> None:
        config = {
            "conditions": [
                {"expression": "{{ node_1.count }}", "operator": ">", "expected": 10, "target": "node_3"},
            ],
            "default_branch": "node_5",
        }
        executor = GatewayNodeExecutor("gw_1", config)
        result = await executor.execute({"node_1": {"count": 42}})
        assert result.selected_branch == "node_3"
        result_miss = await executor.execute({"node_1": {"count": 5}})
        assert result_miss.selected_branch == "node_5"

    @pytest.mark.asyncio
    async def test_operator_lt(self) -> None:
        config = {
            "conditions": [
                {"expression": "{{ node_1.count }}", "operator": "<", "expected": 10, "target": "node_3"},
            ],
            "default_branch": "node_5",
        }
        executor = GatewayNodeExecutor("gw_1", config)
        result = await executor.execute({"node_1": {"count": 5}})
        assert result.selected_branch == "node_3"

    @pytest.mark.asyncio
    async def test_operator_gte_and_lte(self) -> None:
        config = {
            "conditions": [
                {"expression": "{{ node_1.count }}", "operator": ">=", "expected": 10, "target": "node_3"},
                {"expression": "{{ node_1.count }}", "operator": "<=", "expected": 10, "target": "node_4"},
            ],
            "default_branch": "node_5",
        }
        executor = GatewayNodeExecutor("gw_1", config)
        # count == 10 → 第一个 >= 命中（first-match-wins）
        result = await executor.execute({"node_1": {"count": 10}})
        assert result.selected_branch == "node_3"

    @pytest.mark.asyncio
    async def test_operator_default_back_compat(self) -> None:
        """condition 不带 operator 字段，行为同 ==（向后兼容）。"""
        config = {
            "conditions": [
                {"expression": "{{ node_1.status }}", "expected": "ok", "target": "node_3"},
            ],
            "default_branch": "node_5",
        }
        executor = GatewayNodeExecutor("gw_1", config)
        result = await executor.execute({"node_1": {"status": "ok"}})
        assert result.selected_branch == "node_3"
        # 大小写不敏感同样生效（默认 == 走同一逻辑）
        result_ci = await executor.execute({"node_1": {"status": "OK"}})
        assert result_ci.selected_branch == "node_3"

    # ── contains / not_contains（字符串子串 + 列表元素，大小写不敏感）──

    @pytest.mark.asyncio
    async def test_operator_contains_string_substring(self) -> None:
        """contains：字符串子串匹配，大小写不敏感。"""
        config = {
            "conditions": [
                {"expression": "{{ node_1.text }}", "operator": "contains", "expected": "heavy", "target": "node_3"},
            ],
            "default_branch": "node_5",
        }
        executor = GatewayNodeExecutor("gw_1", config)
        # 子串 + 大小写不敏感：actual 含 "HEAVY"，expected "heavy" 命中
        result = await executor.execute({"node_1": {"text": "weight=HEAVY, ok"}})
        assert result.selected_branch == "node_3"
        # 不含子串 → 走 fallback
        result_miss = await executor.execute({"node_1": {"text": "light"}})
        assert result_miss.selected_branch == "node_5"

    @pytest.mark.asyncio
    async def test_operator_not_contains_string(self) -> None:
        """not_contains：不含子串时命中。"""
        config = {
            "conditions": [
                {"expression": "{{ node_1.text }}", "operator": "not_contains", "expected": "error", "target": "node_3"},
            ],
            "default_branch": "node_5",
        }
        executor = GatewayNodeExecutor("gw_1", config)
        result = await executor.execute({"node_1": {"text": "all good"}})
        assert result.selected_branch == "node_3"
        result_miss = await executor.execute({"node_1": {"text": "has ERROR here"}})
        assert result_miss.selected_branch == "node_5"

    @pytest.mark.asyncio
    async def test_operator_contains_list_element(self) -> None:
        """contains：actual 为列表时做元素包含（等值）。"""
        config = {
            "conditions": [
                {"expression": "{{ node_1.tags }}", "operator": "contains", "expected": "vip", "target": "node_3"},
            ],
            "default_branch": "node_5",
        }
        executor = GatewayNodeExecutor("gw_1", config)
        result = await executor.execute({"node_1": {"tags": ["new", "vip", "active"]}})
        assert result.selected_branch == "node_3"
        result_miss = await executor.execute({"node_1": {"tags": ["new", "normal"]}})
        assert result_miss.selected_branch == "node_5"

    @pytest.mark.asyncio
    async def test_operator_contains_type_mismatch_no_match(self) -> None:
        """contains：actual 类型不匹配（非 str/list）时视为不包含，不抛错。"""
        config = {
            "conditions": [
                {"expression": "{{ node_1.count }}", "operator": "contains", "expected": "5", "target": "node_3"},
            ],
            "default_branch": "node_5",
        }
        executor = GatewayNodeExecutor("gw_1", config)
        # actual 是 int，类型不匹配 → 不包含 → 走 fallback（不抛异常）
        result = await executor.execute({"node_1": {"count": 42}})
        assert result.selected_branch == "node_5"


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
            mock_engine_instance.execute_task = AsyncMock(side_effect=TimeoutError())
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
