"""Tests for the Agent builder — Skill declaration and tool resolution."""
import pytest
from unittest.mock import patch

from app.engine.agent.builder import (
    _resolve_tools,
    _resolve_builtin_tools,
    _make_skill_loader,
    build_skill_declaration,
)


# ---------------------------------------------------------------------------
# _resolve_tools
# ---------------------------------------------------------------------------


class TestResolveTools:
    """_resolve_tools tests."""

    @pytest.mark.asyncio
    async def test_empty_tool_ids_returns_empty_list(self) -> None:
        agent = {"tool_ids": []}
        result = await _resolve_tools(agent)
        assert result == []

    @pytest.mark.asyncio
    async def test_missing_tool_ids_returns_empty_list(self) -> None:
        agent = {}
        result = await _resolve_tools(agent)
        assert result == []

    @pytest.mark.asyncio
    async def test_invalid_tool_ids_returns_empty_list(self) -> None:
        """When tool_ids don't match any docs, don't inject useless tools."""
        agent = {"tool_ids": ["tool_999"]}
        with patch("app.services.tool_service.ToolService.get_tools_by_ids", return_value=[]):
            result = await _resolve_tools(agent)
            assert result == []

    @pytest.mark.asyncio
    async def test_with_tool_ids_returns_load_skill_tool(self) -> None:
        docs = [{"_id": "tool_001", "name": "my-skill"}]
        agent = {"tool_ids": ["tool_001"]}
        with patch("app.services.tool_service.ToolService.get_tools_by_ids", return_value=docs):
            tools = await _resolve_tools(agent)
            assert len(tools) == 1
            assert tools[0].name == "load_skill"

    @pytest.mark.asyncio
    async def test_tools_are_structured_tools(self) -> None:
        from langchain_core.tools import StructuredTool

        docs = [{"_id": "tool_001", "name": "my-skill"}]
        agent = {"tool_ids": ["tool_001"]}
        with patch("app.services.tool_service.ToolService.get_tools_by_ids", return_value=docs):
            tools = await _resolve_tools(agent)
            assert isinstance(tools[0], StructuredTool)


# ---------------------------------------------------------------------------
# _make_skill_loader (load_skill)
# ---------------------------------------------------------------------------


class TestMakeSkillLoader:
    """_make_skill_loader / load_skill tests."""

    @pytest.mark.asyncio
    async def test_skill_found(self) -> None:
        with patch("app.engine.tool.skill_fs.read_skill_file", return_value="Do something useful."):
            tool_fn = _make_skill_loader()
            result = await tool_fn.ainvoke({"skill_name": "my-skill"})
            assert "Do something useful" in result
            assert "Skill base path:" in result

    @pytest.mark.asyncio
    async def test_skill_returns_instructions_only(self) -> None:
        """load_skill should return ONLY instructions + path hint, not auxiliary files."""
        with patch("app.engine.tool.skill_fs.read_skill_file", return_value="Main instructions."):
            tool_fn = _make_skill_loader()
            result = await tool_fn.ainvoke({"skill_name": "dir-skill"})
            # Instructions + path hint, NOT file content
            assert "Main instructions." in result
            assert "Skill base path:" in result

    @pytest.mark.asyncio
    async def test_skill_not_found(self) -> None:
        with patch("app.engine.tool.skill_fs.read_skill_file", return_value=None):
            tool_fn = _make_skill_loader()
            result = await tool_fn.ainvoke({"skill_name": "nope"})
            assert "not found" in result

    @pytest.mark.asyncio
    async def test_skill_no_content(self) -> None:
        with patch("app.engine.tool.skill_fs.read_skill_file", return_value=""):
            tool_fn = _make_skill_loader()
            result = await tool_fn.ainvoke({"skill_name": "empty-skill"})
            assert "no content" in result

    @pytest.mark.asyncio
    async def test_whitelist_allows_bound_skill(self) -> None:
        with patch("app.engine.tool.skill_fs.read_skill_file", return_value="Bound skill content."):
            tool_fn = _make_skill_loader(allowed_names={"my-skill"})
            result = await tool_fn.ainvoke({"skill_name": "my-skill"})
            assert "Bound skill content" in result

    @pytest.mark.asyncio
    async def test_whitelist_rejects_unbound_skill(self) -> None:
        tool_fn = _make_skill_loader(allowed_names={"other-skill"})
        result = await tool_fn.ainvoke({"skill_name": "my-skill"})
        assert "not available" in result

    @pytest.mark.asyncio
    async def test_content_truncation(self) -> None:
        big_content = "x" * 60_000
        with patch("app.engine.tool.skill_fs.read_skill_file", return_value=big_content):
            tool_fn = _make_skill_loader()
            result = await tool_fn.ainvoke({"skill_name": "big-skill"})
            assert "[truncated" in result
            assert len(result) < 60_000


# ---------------------------------------------------------------------------
# build_skill_declaration
# ---------------------------------------------------------------------------


class TestBuildSkillDeclaration:
    """build_skill_declaration tests."""

    @pytest.mark.asyncio
    async def test_empty_tool_ids(self) -> None:
        result = await build_skill_declaration([])
        assert result == ""

    @pytest.mark.asyncio
    async def test_no_matching_docs(self) -> None:
        with patch("app.services.tool_service.ToolService.get_tools_by_ids", return_value=[]):
            result = await build_skill_declaration(["tool_999"])
            assert result == ""

    @pytest.mark.asyncio
    async def test_single_skill(self) -> None:
        docs = [{"_id": "tool_001", "name": "web-search", "description": "Search the web"}]
        with patch("app.services.tool_service.ToolService.get_tools_by_ids", return_value=docs):
            result = await build_skill_declaration(["tool_001"])
            assert "## Available Skills" in result
            assert "**web-search**" in result
            assert "Search the web" in result
            assert "load_skill" in result

    @pytest.mark.asyncio
    async def test_multiple_skills(self) -> None:
        docs = [
            {"_id": "t1", "name": "skill-a", "description": "Desc A"},
            {"_id": "t2", "name": "skill-b", "description": "Desc B"},
        ]
        with patch("app.services.tool_service.ToolService.get_tools_by_ids", return_value=docs):
            result = await build_skill_declaration(["t1", "t2"])
            assert "**skill-a**" in result
            assert "**skill-b**" in result
            assert "load_skill" in result


# ---------------------------------------------------------------------------
# _resolve_tools — skill_ids backward compat
# ---------------------------------------------------------------------------


class TestResolveToolsSkillIds:
    """_resolve_tools reads from skill_ids with fallback to tool_ids."""

    @pytest.mark.asyncio
    async def test_skill_ids_takes_precedence(self) -> None:
        """When both skill_ids and tool_ids are present, skill_ids wins."""
        agent = {"skill_ids": ["skill_001"], "tool_ids": ["tool_001"]}
        docs = [{"_id": "skill_001", "name": "my-skill"}]
        with patch("app.services.tool_service.ToolService.get_tools_by_ids", return_value=docs):
            tools = await _resolve_tools(agent)
            assert len(tools) == 1
            # Should have fetched skill_001, not tool_001
            from app.services.tool_service import ToolService

            ToolService.get_tools_by_ids.assert_called_once_with(["skill_001"])

    @pytest.mark.asyncio
    async def test_falls_back_to_tool_ids(self) -> None:
        """When skill_ids is empty, fall back to tool_ids."""
        agent = {"skill_ids": [], "tool_ids": ["tool_001"]}
        docs = [{"_id": "tool_001", "name": "legacy-skill"}]
        with patch("app.services.tool_service.ToolService.get_tools_by_ids", return_value=docs):
            tools = await _resolve_tools(agent)
            assert len(tools) == 1
            assert tools[0].name == "load_skill"

    @pytest.mark.asyncio
    async def test_both_empty_returns_empty(self) -> None:
        """When both skill_ids and tool_ids are empty, returns empty list."""
        agent = {"skill_ids": [], "tool_ids": []}
        result = await _resolve_tools(agent)
        assert result == []


# ---------------------------------------------------------------------------
# _resolve_builtin_tools
# ---------------------------------------------------------------------------


class TestResolveBuiltinTools:
    """_resolve_builtin_tools tests.

    Task management tools (task_query, task_list, etc.) are always
    included as built-in tools regardless of builtin_config.
    """

    def _task_tool_names(self) -> set[str]:
        return {
            "propose_workflow", "dispatch_workflow",
            "task_query", "task_list", "task_intervene",
            "cancel_task", "update_task_variables",
        }

    def test_empty_config_returns_task_tools_only(self) -> None:
        """When builtin_config is empty, only task tools are injected."""
        result = _resolve_builtin_tools({"builtin_config": []})
        names = {t.name for t in result}
        assert names == self._task_tool_names()

    def test_missing_config_returns_task_tools_only(self) -> None:
        """When builtin_config key is missing, only task tools are returned."""
        result = _resolve_builtin_tools({})
        names = {t.name for t in result}
        assert names == self._task_tool_names()

    def test_whitelist_returns_base_plus_task_tools(self) -> None:
        """Whitelisted base tools + all task tools are returned."""
        result = _resolve_builtin_tools({"builtin_config": ["bash", "read"]})
        names = {t.name for t in result}
        assert names == {"bash", "read"} | self._task_tool_names()

    def test_invalid_names_are_ignored(self) -> None:
        """Invalid tool names in builtin_config are silently skipped."""
        result = _resolve_builtin_tools({"builtin_config": ["bash", "nonexistent_tool"]})
        names = {t.name for t in result}
        assert names == {"bash"} | self._task_tool_names()

    def test_partial_whitelist(self) -> None:
        """Only a subset of base built-in tools can be enabled."""
        result = _resolve_builtin_tools({"builtin_config": ["write"]})
        names = {t.name for t in result}
        assert names == {"write"} | self._task_tool_names()

    def test_all_base_tools_enabled(self) -> None:
        """All base tools + task tools returned when fully whitelisted."""
        result = _resolve_builtin_tools({"builtin_config": ["bash", "read", "write"]})
        names = {t.name for t in result}
        assert names == {"bash", "read", "write"} | self._task_tool_names()


# ---------------------------------------------------------------------------
# dispatch_workflow — tool presence in builtin tools
# ---------------------------------------------------------------------------


class TestDispatchWorkflowPresence:
    """dispatch_workflow is injected as a task tool."""

    def _task_tool_names(self) -> set[str]:
        return {
            "propose_workflow", "dispatch_workflow",
            "task_query", "task_list", "task_intervene",
            "cancel_task", "update_task_variables",
        }

    def test_dispatch_workflow_is_in_task_tools(self) -> None:
        """dispatch_workflow should be in the resolved task tools."""
        from app.engine.agent.workflow_executor import _TASK_TOOLS

        names = {t.name for t in _TASK_TOOLS}
        assert "dispatch_workflow" in names

    def test_dispatch_workflow_is_builtin_tool(self) -> None:
        """dispatch_workflow should be part of the default builtin tools."""
        result = _resolve_builtin_tools({"builtin_config": []})
        names = {t.name for t in result}
        assert "dispatch_workflow" in names
