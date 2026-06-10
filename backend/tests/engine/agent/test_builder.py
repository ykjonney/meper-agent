"""Tests for the Agent builder — Skill declaration and tool resolution."""
import pytest
from unittest.mock import patch

from app.engine.agent.builder import (
    _resolve_tools,
    _resolve_builtin_tools,
    _make_skill_loader,
    _make_skill_file_loader,
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
    async def test_with_tool_ids_returns_both_tools(self) -> None:
        docs = [{"_id": "tool_001", "name": "my-skill"}]
        agent = {"tool_ids": ["tool_001"]}
        with patch("app.services.tool_service.ToolService.get_tools_by_ids", return_value=docs):
            tools = await _resolve_tools(agent)
            assert len(tools) == 2
            assert tools[0].name == "load_skill"
            assert tools[1].name == "load_skill_file"

    @pytest.mark.asyncio
    async def test_tools_are_structured_tools(self) -> None:
        from langchain_core.tools import StructuredTool

        docs = [{"_id": "tool_001", "name": "my-skill"}]
        agent = {"tool_ids": ["tool_001"]}
        with patch("app.services.tool_service.ToolService.get_tools_by_ids", return_value=docs):
            tools = await _resolve_tools(agent)
            assert isinstance(tools[0], StructuredTool)
            assert isinstance(tools[1], StructuredTool)


# ---------------------------------------------------------------------------
# _make_skill_loader (load_skill)
# ---------------------------------------------------------------------------


class TestMakeSkillLoader:
    """_make_skill_loader / load_skill tests."""

    @pytest.mark.asyncio
    async def test_skill_found(self) -> None:
        mock_doc = {
            "_id": "tool_001",
            "name": "my-skill",
            "instructions": "Do something useful.",
            "files": [],
        }
        with patch("app.services.tool_service.ToolService.find_by_name", return_value=mock_doc):
            tool_fn = _make_skill_loader()
            result = await tool_fn.ainvoke({"skill_name": "my-skill"})
            assert "Do something useful" in result

    @pytest.mark.asyncio
    async def test_skill_returns_instructions_only(self) -> None:
        """load_skill should return ONLY instructions, not auxiliary files."""
        mock_doc = {
            "_id": "tool_001",
            "name": "dir-skill",
            "instructions": "Main instructions.",
            "files": [
                {"path": "SKILL.md", "content": "# Skill", "size": 7},
                {"path": "steps/step-01.md", "content": "# Step 1", "size": 8},
            ],
        }
        with patch("app.services.tool_service.ToolService.find_by_name", return_value=mock_doc):
            tool_fn = _make_skill_loader()
            result = await tool_fn.ainvoke({"skill_name": "dir-skill"})
            # Only instructions, NOT file content
            assert result == "Main instructions."
            assert "steps/step-01.md" not in result
            assert "# Step 1" not in result

    @pytest.mark.asyncio
    async def test_skill_not_found(self) -> None:
        with patch("app.services.tool_service.ToolService.find_by_name", return_value=None):
            tool_fn = _make_skill_loader()
            result = await tool_fn.ainvoke({"skill_name": "nope"})
            assert "not found" in result

    @pytest.mark.asyncio
    async def test_skill_no_content(self) -> None:
        mock_doc = {
            "_id": "tool_001",
            "name": "empty-skill",
            "instructions": "",
            "files": [],
        }
        with patch("app.services.tool_service.ToolService.find_by_name", return_value=mock_doc):
            tool_fn = _make_skill_loader()
            result = await tool_fn.ainvoke({"skill_name": "empty-skill"})
            assert "no content" in result

    @pytest.mark.asyncio
    async def test_whitelist_allows_bound_skill(self) -> None:
        mock_doc = {
            "_id": "tool_001",
            "name": "my-skill",
            "instructions": "Bound skill content.",
            "files": [],
        }
        with patch("app.services.tool_service.ToolService.find_by_name", return_value=mock_doc):
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
        mock_doc = {
            "_id": "tool_001",
            "name": "big-skill",
            "instructions": "x" * 60_000,
            "files": [],
        }
        with patch("app.services.tool_service.ToolService.find_by_name", return_value=mock_doc):
            tool_fn = _make_skill_loader()
            result = await tool_fn.ainvoke({"skill_name": "big-skill"})
            assert "[truncated" in result
            assert len(result) < 60_000


# ---------------------------------------------------------------------------
# _make_skill_file_loader (load_skill_file)
# ---------------------------------------------------------------------------


class TestMakeSkillFileLoader:
    """_make_skill_file_loader / load_skill_file tests."""

    @pytest.mark.asyncio
    async def test_file_found(self) -> None:
        mock_doc = {
            "_id": "tool_001",
            "name": "dir-skill",
            "instructions": "Main.",
            "files": [
                {"path": "SKILL.md", "content": "# Skill", "size": 7},
                {"path": "steps/step-01.md", "content": "# Step 1", "size": 8},
            ],
        }
        with patch("app.services.tool_service.ToolService.find_by_name", return_value=mock_doc):
            tool_fn = _make_skill_file_loader()
            result = await tool_fn.ainvoke({
                "skill_name": "dir-skill",
                "file_path": "steps/step-01.md",
            })
            assert "# Step 1" in result

    @pytest.mark.asyncio
    async def test_file_not_found(self) -> None:
        mock_doc = {
            "_id": "tool_001",
            "name": "dir-skill",
            "instructions": "Main.",
            "files": [
                {"path": "SKILL.md", "content": "# Skill", "size": 7},
            ],
        }
        with patch("app.services.tool_service.ToolService.find_by_name", return_value=mock_doc):
            tool_fn = _make_skill_file_loader()
            result = await tool_fn.ainvoke({
                "skill_name": "dir-skill",
                "file_path": "nonexistent.md",
            })
            assert "not found" in result

    @pytest.mark.asyncio
    async def test_skill_not_found(self) -> None:
        with patch("app.services.tool_service.ToolService.find_by_name", return_value=None):
            tool_fn = _make_skill_file_loader()
            result = await tool_fn.ainvoke({
                "skill_name": "nope",
                "file_path": "any.md",
            })
            assert "not found" in result

    @pytest.mark.asyncio
    async def test_whitelist_rejects_unbound(self) -> None:
        tool_fn = _make_skill_file_loader(allowed_names={"other"})
        result = await tool_fn.ainvoke({
            "skill_name": "my-skill",
            "file_path": "any.md",
        })
        assert "not available" in result

    @pytest.mark.asyncio
    async def test_file_empty(self) -> None:
        mock_doc = {
            "_id": "tool_001",
            "name": "dir-skill",
            "instructions": "Main.",
            "files": [
                {"path": "empty.md", "content": "", "size": 0},
            ],
        }
        with patch("app.services.tool_service.ToolService.find_by_name", return_value=mock_doc):
            tool_fn = _make_skill_file_loader()
            result = await tool_fn.ainvoke({
                "skill_name": "dir-skill",
                "file_path": "empty.md",
            })
            assert "empty" in result


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
            assert "load_skill_file" in result


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
            assert len(tools) == 2
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
            assert len(tools) == 2
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
    """_resolve_builtin_tools tests."""

    def test_empty_config_returns_empty(self) -> None:
        """When builtin_config is empty, no built-in tools are injected."""
        result = _resolve_builtin_tools({"builtin_config": []})
        assert result == []

    def test_missing_config_returns_empty(self) -> None:
        """When builtin_config key is missing, returns empty list."""
        result = _resolve_builtin_tools({})
        assert result == []

    def test_whitelist_returns_matching_tools(self) -> None:
        """Only whitelisted tools are returned."""
        result = _resolve_builtin_tools({"builtin_config": ["bash", "read"]})
        assert len(result) == 2
        names = {t.name for t in result}
        assert names == {"bash", "read"}

    def test_invalid_names_are_ignored(self) -> None:
        """Invalid tool names in builtin_config are silently skipped."""
        result = _resolve_builtin_tools({"builtin_config": ["bash", "nonexistent_tool"]})
        assert len(result) == 1
        assert result[0].name == "bash"

    def test_partial_whitelist(self) -> None:
        """Only a subset of built-in tools can be enabled."""
        result = _resolve_builtin_tools({"builtin_config": ["write"]})
        assert len(result) == 1
        assert result[0].name == "write"

    def test_all_tools_enabled(self) -> None:
        """All built-in tools returned when fully whitelisted."""
        result = _resolve_builtin_tools({"builtin_config": ["bash", "read", "write"]})
        assert len(result) == 3
