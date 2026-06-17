"""Tests for ToolService — CRUD operations."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.errors import ConflictError
from app.engine.tool.skill_parser import ParsedSkill


def _make_parsed(
    name: str = "test-tool",
    description: str = "A test tool",
) -> ParsedSkill:
    return ParsedSkill(
        name=name,
        description=description,
        input_schema={"type": "object", "properties": {"x": {"type": "string"}}},
        output_schema={"type": "string"},
        instructions="## Usage\nTest.",
    )


class TestCreateTool:
    """ToolService.create_tool_from_parsed tests."""

    @pytest.mark.asyncio
    async def test_create_success(self) -> None:
        parsed = _make_parsed()
        mock_col = AsyncMock()
        mock_col.find_one = AsyncMock(return_value=None)
        mock_col.insert_one = AsyncMock()

        with (
            patch("app.services.tool_service.ToolService._collection", return_value=mock_col),
            patch("app.services.tool_service.materialize_skill") as mock_mat,
        ):
            from app.services.tool_service import ToolService

            doc = await ToolService.create_tool_from_parsed(parsed, source_file="test.md")

        assert doc["name"] == "test-tool"
        assert doc["description"] == "A test tool"
        assert doc["version"] == 1
        assert doc["source"] == "markdown"
        assert doc["source_file"] == "test.md"
        assert doc["_id"].startswith("tool_")
        # No files field stored in MongoDB
        assert "files" not in doc
        mock_col.insert_one.assert_called_once()
        # materialize_skill should be called with the skill name
        mock_mat.assert_called_once()
        assert mock_mat.call_args[0][0] == "test-tool"

    @pytest.mark.asyncio
    async def test_create_name_conflict(self) -> None:
        parsed = _make_parsed(name="existing-tool")
        mock_col = AsyncMock()
        mock_col.find_one = AsyncMock(return_value={"_id": "tool_existing", "name": "existing-tool"})

        with patch("app.services.tool_service.ToolService._collection", return_value=mock_col):
            from app.services.tool_service import ToolService

            with pytest.raises(ConflictError) as exc_info:
                await ToolService.create_tool_from_parsed(parsed)
            assert "existing-tool" in str(exc_info.value)


class TestGetTool:
    """ToolService.get_tool tests."""

    @pytest.mark.asyncio
    async def test_found(self) -> None:
        mock_col = AsyncMock()
        mock_col.find_one = AsyncMock(return_value={"_id": "tool_123", "name": "test"})

        with patch("app.services.tool_service.ToolService._collection", return_value=mock_col):
            from app.services.tool_service import ToolService

            doc = await ToolService.get_tool("tool_123")
        assert doc is not None
        assert doc["name"] == "test"

    @pytest.mark.asyncio
    async def test_not_found(self) -> None:
        mock_col = AsyncMock()
        mock_col.find_one = AsyncMock(return_value=None)

        with patch("app.services.tool_service.ToolService._collection", return_value=mock_col):
            from app.services.tool_service import ToolService

            assert await ToolService.get_tool("tool_missing") is None


class TestListTools:
    """ToolService.list_tools tests."""

    @pytest.mark.asyncio
    async def test_basic_list(self) -> None:
        mock_col = MagicMock()
        mock_col.count_documents = AsyncMock(return_value=1)
        mock_cursor = MagicMock()
        mock_cursor.sort.return_value = mock_cursor
        mock_cursor.skip.return_value = mock_cursor
        mock_cursor.limit.return_value = mock_cursor
        mock_cursor.to_list = AsyncMock(return_value=[{"_id": "tool_1", "name": "a"}])
        mock_col.find.return_value = mock_cursor

        with patch("app.services.tool_service.ToolService._collection", return_value=mock_col):
            from app.services.tool_service import ToolService

            items, total = await ToolService.list_tools()
        assert total == 1
        assert len(items) == 1


class TestUpdateTool:
    """ToolService.update_tool tests."""

    @pytest.mark.asyncio
    async def test_update_tags(self) -> None:
        existing = {"_id": "tool_1", "name": "test", "version": 1, "tags": []}
        mock_col = AsyncMock()
        mock_col.find_one = AsyncMock(
            side_effect=[existing, {**existing, "version": 2, "tags": ["a"]}]
        )
        mock_col.update_one = AsyncMock()

        with patch("app.services.tool_service.ToolService._collection", return_value=mock_col):
            from app.services.tool_service import ToolService

            result = await ToolService.update_tool("tool_1", tags=["a"])
        assert result is not None
        # version should be incremented in the update call
        update_call = mock_col.update_one.call_args
        assert update_call[0][1]["$set"]["version"] == 2

    @pytest.mark.asyncio
    async def test_update_not_found(self) -> None:
        mock_col = AsyncMock()
        mock_col.find_one = AsyncMock(return_value=None)

        with patch("app.services.tool_service.ToolService._collection", return_value=mock_col):
            from app.services.tool_service import ToolService

            result = await ToolService.update_tool("tool_missing")
        assert result is None


class TestDeleteTool:
    """ToolService.delete_tool tests."""

    @pytest.mark.asyncio
    async def test_delete_success(self) -> None:
        mock_col = AsyncMock()
        mock_col.find_one = AsyncMock(return_value={"_id": "tool_1", "name": "test"})
        mock_col.delete_one = AsyncMock(return_value=MagicMock(deleted_count=1))

        mock_agents = MagicMock()
        mock_agents_cursor = MagicMock()
        mock_agents_cursor.to_list = AsyncMock(return_value=[])
        mock_agents.find.return_value = mock_agents_cursor

        mock_db = {"tools": mock_col, "agents": mock_agents}
        with (
            patch("app.services.tool_service.ToolService._collection", return_value=mock_col),
            patch("app.services.tool_service.get_database", return_value=mock_db),
            patch("app.services.tool_service.delete_skill_dir") as mock_del_dir,
        ):
            from app.services.tool_service import ToolService

            result = await ToolService.delete_tool("tool_1")
        assert result is True
        # Disk cleanup should be called
        mock_del_dir.assert_called_once_with("test")

    @pytest.mark.asyncio
    async def test_delete_not_found(self) -> None:
        mock_col = AsyncMock()
        mock_col.find_one = AsyncMock(return_value=None)

        with patch("app.services.tool_service.ToolService._collection", return_value=mock_col):
            from app.services.tool_service import ToolService

            result = await ToolService.delete_tool("tool_missing")
        assert result is False

    @pytest.mark.asyncio
    async def test_delete_referenced_by_agent(self) -> None:
        mock_col = AsyncMock()
        mock_col.find_one = AsyncMock(return_value={"_id": "tool_1", "name": "test"})

        mock_agents = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(
            return_value=[{"_id": "agent_1", "name": "My Agent"}]
        )
        mock_agents.find.return_value = mock_cursor

        mock_db = {"tools": mock_col, "agents": mock_agents}
        with (
            patch("app.services.tool_service.ToolService._collection", return_value=mock_col),
            patch("app.services.tool_service.get_database", return_value=mock_db),
        ):
            from app.services.tool_service import ToolService

            with pytest.raises(ConflictError) as exc_info:
                await ToolService.delete_tool("tool_1")
            assert "My Agent" in str(exc_info.value)


class TestFindByName:
    """ToolService.find_by_name tests."""

    @pytest.mark.asyncio
    async def test_found(self) -> None:
        mock_col = AsyncMock()
        mock_col.find_one = AsyncMock(return_value={"_id": "tool_1", "name": "test"})

        with patch("app.services.tool_service.ToolService._collection", return_value=mock_col):
            from app.services.tool_service import ToolService

            doc = await ToolService.find_by_name("test")
        assert doc is not None

    @pytest.mark.asyncio
    async def test_not_found(self) -> None:
        mock_col = AsyncMock()
        mock_col.find_one = AsyncMock(return_value=None)

        with patch("app.services.tool_service.ToolService._collection", return_value=mock_col):
            from app.services.tool_service import ToolService

            assert await ToolService.find_by_name("missing") is None


class TestGetToolFiles:
    """ToolService.get_tool_files tests."""

    @pytest.mark.asyncio
    async def test_returns_file_tree_from_disk(self) -> None:
        mock_col = AsyncMock()
        mock_col.find_one = AsyncMock(
            return_value={"_id": "tool_1", "name": "my-skill"}
        )

        disk_files = [
            {"path": "SKILL.md", "size": 100},
            {"path": "scripts/search.py", "size": 200},
        ]

        with (
            patch("app.services.tool_service.ToolService._collection", return_value=mock_col),
            patch("app.services.tool_service.list_skill_files", return_value=disk_files),
        ):
            from app.services.tool_service import ToolService

            tree = await ToolService.get_tool_files("tool_1")

        assert tree is not None
        # Should have root-level nodes
        assert len(tree) == 2  # SKILL.md + scripts/

    @pytest.mark.asyncio
    async def test_tool_not_found(self) -> None:
        mock_col = AsyncMock()
        mock_col.find_one = AsyncMock(return_value=None)

        with patch("app.services.tool_service.ToolService._collection", return_value=mock_col):
            from app.services.tool_service import ToolService

            result = await ToolService.get_tool_files("missing")
        assert result is None


class TestGetToolFileContent:
    """ToolService.get_tool_file_content tests."""

    @pytest.mark.asyncio
    async def test_reads_from_disk(self) -> None:
        mock_col = AsyncMock()
        mock_col.find_one = AsyncMock(
            return_value={"_id": "tool_1", "name": "my-skill"}
        )

        with (
            patch("app.services.tool_service.ToolService._collection", return_value=mock_col),
            patch("app.services.tool_service.read_skill_file", return_value="file content"),
        ):
            from app.services.tool_service import ToolService

            result = await ToolService.get_tool_file_content("tool_1", "scripts/search.py")

        assert result is not None
        assert result["content"] == "file content"
        assert result["path"] == "scripts/search.py"

    @pytest.mark.asyncio
    async def test_file_not_on_disk(self) -> None:
        mock_col = AsyncMock()
        mock_col.find_one = AsyncMock(
            return_value={"_id": "tool_1", "name": "my-skill"}
        )

        with (
            patch("app.services.tool_service.ToolService._collection", return_value=mock_col),
            patch("app.services.tool_service.read_skill_file", return_value=None),
        ):
            from app.services.tool_service import ToolService

            result = await ToolService.get_tool_file_content("tool_1", "nonexistent.py")
        assert result is None


class TestUpdateToolFile:
    """ToolService.update_tool_file tests."""

    @pytest.mark.asyncio
    async def test_writes_to_disk(self) -> None:
        doc = {"_id": "tool_1", "name": "my-skill"}
        mock_col = AsyncMock()
        mock_col.find_one = AsyncMock(return_value=doc)
        mock_col.update_one = AsyncMock()

        # Create a mock Path that supports / operator
        mock_file_path = MagicMock()
        mock_file_path.parent = MagicMock()

        mock_base_path = MagicMock()
        mock_base_path.__truediv__ = MagicMock(return_value=mock_file_path)

        with (
            patch("app.services.tool_service.ToolService._collection", return_value=mock_col),
            patch("app.services.tool_service.read_skill_file", return_value="old content"),
            patch("app.services.tool_service.get_skill_base_path", return_value=mock_base_path),
        ):
            from app.services.tool_service import ToolService

            result = await ToolService.update_tool_file(
                "tool_1", "scripts/search.py", "new content"
            )

        assert result is not None
        assert result["content"] == "new content"
        assert result["path"] == "scripts/search.py"
        # Disk write should happen
        mock_file_path.write_text.assert_called_once_with("new content", encoding="utf-8")

    @pytest.mark.asyncio
    async def test_tool_not_found(self) -> None:
        mock_col = AsyncMock()
        mock_col.find_one = AsyncMock(return_value=None)

        with patch("app.services.tool_service.ToolService._collection", return_value=mock_col):
            from app.services.tool_service import ToolService

            result = await ToolService.update_tool_file("missing", "SKILL.md", "content")
        assert result is None
