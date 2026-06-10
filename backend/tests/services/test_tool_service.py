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

        with patch("app.services.tool_service.ToolService._collection", return_value=mock_col):
            from app.services.tool_service import ToolService

            doc = await ToolService.create_tool_from_parsed(parsed, source_file="test.md")

        assert doc["name"] == "test-tool"
        assert doc["description"] == "A test tool"
        assert doc["status"] == "draft"
        assert doc["version"] == 1
        assert doc["source"] == "markdown"
        assert doc["source_file"] == "test.md"
        assert doc["_id"].startswith("tool_")
        mock_col.insert_one.assert_called_once()

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
        # Motor's find() returns a *synchronous* cursor; only count_documents
        # and cursor.to_list() are awaitable. So mock the collection with
        # MagicMock (sync) and attach AsyncMock only to the async methods.
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
    async def test_update_status_and_tags(self) -> None:
        existing = {"_id": "tool_1", "name": "test", "version": 1, "status": "draft", "tags": []}
        mock_col = AsyncMock()
        mock_col.find_one = AsyncMock(
            side_effect=[existing, {**existing, "status": "active", "version": 2, "tags": ["a"]}]
        )
        mock_col.update_one = AsyncMock()

        with patch("app.services.tool_service.ToolService._collection", return_value=mock_col):
            from app.services.tool_service import ToolService

            result = await ToolService.update_tool("tool_1", status="active", tags=["a"])
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

        # Mock agents collection — no references.
        # find() returns a sync cursor; to_list() is awaitable.
        mock_agents = MagicMock()
        mock_agents_cursor = MagicMock()
        mock_agents_cursor.to_list = AsyncMock(return_value=[])
        mock_agents.find.return_value = mock_agents_cursor

        mock_db = {"tools": mock_col, "agents": mock_agents}
        with (
            patch("app.services.tool_service.ToolService._collection", return_value=mock_col),
            patch("app.services.tool_service.get_database", return_value=mock_db),
        ):
            from app.services.tool_service import ToolService

            result = await ToolService.delete_tool("tool_1")
        assert result is True

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

        # find() is sync in Motor; only to_list() is awaitable
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
