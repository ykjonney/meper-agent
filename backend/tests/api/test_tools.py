"""API tests for /api/v1/tools endpoints (mock-based).

Uses ``unittest.mock`` to mock ToolService so tests run without MongoDB.
"""
from inspect import signature
from unittest.mock import AsyncMock, patch

import pytest
from app.core.security import get_current_user
from app.main import app
from app.schemas.user import UserResponse, UserStatus
from app.services.tool_service import ToolService
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def auth_admin():
    user = UserResponse(
        id="user_01HTEST",
        username="admin",
        email="admin@example.com",
        role="admin",
        status=UserStatus.ACTIVE,
        created_at="2026-01-01T00:00:00",
        updated_at="2026-01-01T00:00:00",
        permissions=[],
    )
    app.dependency_overrides[get_current_user] = lambda: user
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def auth_viewer():
    user = UserResponse(
        id="user_02HTEST",
        username="viewer",
        email="viewer@example.com",
        role="viewer",
        status=UserStatus.ACTIVE,
        created_at="2026-01-01T00:00:00",
        updated_at="2026-01-01T00:00:00",
        permissions=[],
    )
    app.dependency_overrides[get_current_user] = lambda: user
    yield
    app.dependency_overrides.clear()


def _fake_doc(tool_id: str = "tool_01HTEST", name: str = "Test Tool") -> dict:
    return {
        "_id": tool_id,
        "name": name,
        "description": "A test tool",
        "input_schema": {"type": "object", "properties": {"x": {"type": "string"}}},
        "output_schema": {"type": "string"},
        "instructions": "## Usage\nTest.",
        "source": "markdown",
        "source_file": "test.md",
        "version": 1,
        "tags": [],
        "created_at": "2026-01-01T00:00:00",
        "updated_at": "2026-01-01T00:00:00",
    }


_VALID_SKILL_MD = (
    b"---\n"
    b"name: query-device\n"
    b"description: Query device status\n"
    b"---\n\n"
    b"# Body\n\nQuery device.\n"
)


# ---------------------------------------------------------------------------
# GET /tools
# ---------------------------------------------------------------------------


class TestListTools:
    """GET /api/v1/tools."""

    def test_list_returns_tools(self, client: TestClient, auth_admin):
        items = [_fake_doc(), _fake_doc("tool_02", "Another")]
        with (
            patch.object(ToolService, "list_tools", new_callable=AsyncMock) as mock_list,
            patch("app.api.v1.tools.list_skill_files", return_value=[]),
        ):
            mock_list.return_value = (items, 2)
            resp = client.get("/api/v1/tools")

        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["total"] == 2
        assert len(data["items"]) == 2
        assert data["items"][0]["id"].startswith("tool_")

    def test_list_with_pagination_params(self, client: TestClient, auth_admin):
        with patch.object(ToolService, "list_tools", new_callable=AsyncMock) as mock_list:
            mock_list.return_value = ([], 0)
            client.get("/api/v1/tools?page=2&page_size=10")
        # Check call args
        call_kwargs = mock_list.call_args.kwargs
        assert call_kwargs.get("page") == 2 or mock_list.call_args.args[0] == 2 or mock_list.call_args[1].get("page") == 2

    def test_list_with_name_filter(self, client: TestClient, auth_admin):
        with patch.object(ToolService, "list_tools", new_callable=AsyncMock) as mock_list:
            mock_list.return_value = ([], 0)
            client.get("/api/v1/tools?name=device")
        assert mock_list.call_args.kwargs.get("name") == "device" or "device" in str(mock_list.call_args)

    def test_list_no_auth(self, client: TestClient):
        resp = client.get("/api/v1/tools")
        assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# GET /tools/{tool_id}
# ---------------------------------------------------------------------------


class TestGetTool:
    """GET /api/v1/tools/{tool_id}."""

    def test_get_existing(self, client: TestClient, auth_admin):
        with (
            patch.object(ToolService, "get_tool", new_callable=AsyncMock) as mock_get,
            patch("app.api.v1.tools.list_skill_files", return_value=[]),
        ):
            mock_get.return_value = _fake_doc()
            resp = client.get("/api/v1/tools/tool_01HTEST")

        assert resp.status_code == 200
        assert resp.json()["id"] == "tool_01HTEST"

    def test_get_not_found(self, client: TestClient, auth_admin):
        with patch.object(ToolService, "get_tool", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = None
            resp = client.get("/api/v1/tools/tool_missing")

        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /tools/upload
# ---------------------------------------------------------------------------


class TestUploadTools:
    """POST /api/v1/tools/upload."""

    def test_upload_single_file_success(self, client: TestClient, auth_admin):
        from app.engine.tool.skill_parser import ParsedSkill

        parsed = ParsedSkill(
            name="query-device",
            description="Query device status",
            input_schema={"type": "object", "properties": {}},
            output_schema={"type": "string"},
            instructions="# Body",
        )

        with (
            patch(
                "app.engine.tool.skill_parser.parse_skill_markdown",
                return_value=parsed,
            ),
            patch.object(
                ToolService, "create_tool_from_parsed", new_callable=AsyncMock
            ) as mock_create,
            patch("app.api.v1.tools.list_skill_files", return_value=[]),
        ):
            mock_create.return_value = _fake_doc(name="query-device")
            resp = client.post(
                "/api/v1/tools/upload",
                files={"files": ("device.md", _VALID_SKILL_MD, "text/markdown")},
            )

        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert len(data["created"]) == 1
        assert len(data["errors"]) == 0

    def test_upload_multiple_files(self, client: TestClient, auth_admin):
        from app.engine.tool.skill_parser import ParsedSkill, SkillParseError

        parsed = ParsedSkill(
            name="good-tool",
            description="Good",
            instructions="# Body",
        )

        def fake_parse(content, filename=""):
            if "bad" in filename:
                raise SkillParseError(filename, "Bad frontmatter")
            return parsed

        with (
            patch("app.engine.tool.skill_parser.parse_skill_markdown", side_effect=fake_parse),
            patch.object(
                ToolService, "create_tool_from_parsed", new_callable=AsyncMock
            ) as mock_create,
            patch("app.api.v1.tools.list_skill_files", return_value=[]),
        ):
            mock_create.return_value = _fake_doc(name="good-tool")
            resp = client.post(
                "/api/v1/tools/upload",
                files=[
                    ("files", ("good.md", _VALID_SKILL_MD, "text/markdown")),
                    ("files", ("bad.md", b"--- broken", "text/markdown")),
                ],
            )

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["created"]) == 1
        assert len(data["errors"]) == 1
        assert data["errors"][0]["filename"] == "bad.md"

    def test_upload_no_auth(self, client: TestClient):
        resp = client.post(
            "/api/v1/tools/upload",
            files={"files": ("device.md", _VALID_SKILL_MD, "text/markdown")},
        )
        assert resp.status_code in (401, 403)

    def test_upload_viewer_forbidden(self, client: TestClient, auth_viewer):
        resp = client.post(
            "/api/v1/tools/upload",
            files={"files": ("device.md", _VALID_SKILL_MD, "text/markdown")},
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# PUT /tools/{tool_id}
# ---------------------------------------------------------------------------


class TestUpdateTool:
    """PUT /api/v1/tools/{tool_id}."""

    def test_update_tags(self, client: TestClient, auth_admin):
        with (
            patch.object(ToolService, "update_tool", new_callable=AsyncMock) as mock_update,
            patch("app.api.v1.tools.list_skill_files", return_value=[]),
        ):
            mock_update.return_value = {**_fake_doc(), "version": 2, "tags": ["mes"]}
            resp = client.put(
                "/api/v1/tools/tool_01HTEST",
                json={"tags": ["mes"]},
            )

        assert resp.status_code == 200
        assert resp.json()["version"] == 2

    def test_update_not_found(self, client: TestClient, auth_admin):
        with patch.object(ToolService, "update_tool", new_callable=AsyncMock) as mock_update:
            mock_update.return_value = None
            resp = client.put(
                "/api/v1/tools/tool_missing",
                json={"tags": []},
            )

        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /tools/{tool_id}
# ---------------------------------------------------------------------------


class TestDeleteTool:
    """DELETE /api/v1/tools/{tool_id}."""

    def test_delete_success(self, client: TestClient, auth_admin):
        with patch.object(ToolService, "delete_tool", new_callable=AsyncMock) as mock_del:
            mock_del.return_value = True
            resp = client.delete("/api/v1/tools/tool_01HTEST")

        assert resp.status_code == 204

    def test_delete_not_found(self, client: TestClient, auth_admin):
        with patch.object(ToolService, "delete_tool", new_callable=AsyncMock) as mock_del:
            mock_del.return_value = False
            resp = client.delete("/api/v1/tools/tool_missing")

        assert resp.status_code == 404

    def test_delete_referenced(self, client: TestClient, auth_admin):
        from app.core.errors import ConflictError

        with patch.object(ToolService, "delete_tool", new_callable=AsyncMock) as mock_del:
            mock_del.side_effect = ConflictError(
                code="TOOL_IN_USE", message="被 Agent 引用"
            )
            resp = client.delete("/api/v1/tools/tool_01HTEST")

        assert resp.status_code == 409


# ---------------------------------------------------------------------------
# Contract tests — verify ToolService method signatures match the API calls
# ---------------------------------------------------------------------------


class TestServiceContracts:
    """Ensure the API calls ToolService with the right keywords."""

    def test_list_tools_signature(self) -> None:
        sig = signature(ToolService.list_tools)
        params = sig.parameters
        assert "page" in params
        assert "page_size" in params
        assert "name" in params
        assert "source" in params

    def test_create_tool_from_parsed_signature(self) -> None:
        sig = signature(ToolService.create_tool_from_parsed)
        params = sig.parameters
        assert "parsed" in params
        assert "source_file" in params

    def test_update_tool_signature(self) -> None:
        sig = signature(ToolService.update_tool)
        params = sig.parameters
        assert "tool_id" in params
        assert "tags" in params
