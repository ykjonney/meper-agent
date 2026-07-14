"""API tests for chat file upload in /api/v1/sessions endpoints (mock-based)."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.core.security import get_current_user
from app.main import app
from app.models.file_library import FileConsumerKind, FileRef
from app.schemas.user import UserResponse, UserStatus
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
    yield user
    app.dependency_overrides.clear()


def _fake_file_ref(
    file_id: str = "file_01HTEST",
    owner_user_id: str = "user_01HTEST",
    name: str = "report.txt",
) -> FileRef:
    return FileRef(
        id=file_id,
        owner_user_id=owner_user_id,
        storage_key=f"{owner_user_id}/files/{file_id}",
        name=name,
        size=100,
        mime_type="text/plain",
        sha256="abc123",
        origin_kind=FileConsumerKind.SESSION_MESSAGE,
        origin_id="session_TEST",
    )


# ---------------------------------------------------------------------------
# POST /sessions/{session_id}/files/upload
# ---------------------------------------------------------------------------


class TestUploadChatFile:
    """POST /api/v1/sessions/{session_id}/files/upload."""

    def test_upload_with_content(self, client: TestClient, auth_admin, tmp_path):
        from app.api.v1.sessions import _get_file_service

        fake_ref = _fake_file_ref()
        fake_msg = {
            "_id": "msg_TEST",
            "session_id": "session_TEST",
            "role": "user",
            "content": "请看这个文件",
            "timeline_entries": [],
            "file_ids": ["file_01HTEST"],
            "created_at": "2026-01-01T00:00:00",
        }

        mock_svc = AsyncMock()
        mock_svc.create = AsyncMock(return_value=fake_ref)
        mock_svc.add_usage = AsyncMock()

        # Mock session service
        session_doc = {
            "_id": "session_TEST",
            "user_id": "user_01HTEST",
            "agent_id": "agent_TEST",
            "title": "",
            "status": "active",
            "message_count": 0,
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:00:00",
        }

        # Use dependency_overrides for FastAPI Depends() injection
        app.dependency_overrides[_get_file_service] = lambda: mock_svc

        with (
            patch(
                "app.api.v1.sessions.SessionService.get_session",
                new_callable=AsyncMock,
                return_value=session_doc,
            ),
            patch(
                "app.api.v1.sessions.MessageService.add_message",
                new_callable=AsyncMock,
                return_value=fake_msg,
            ),
            patch(
                "app.engine.tool.workspace.WorkspaceManager.get_workspace",
            ) as mock_ws,
        ):
            # Setup workspace mock with tmp_path
            mock_workspace = MagicMock()
            mock_workspace.input_dir = tmp_path / "input"
            mock_workspace.input_dir.mkdir(parents=True, exist_ok=True)
            mock_ws.return_value = mock_workspace

            resp = client.post(
                "/api/v1/sessions/session_TEST/files/upload",
                data={"content": "请看这个文件"},
                files={"file": ("report.txt", b"hello world", "text/plain")},
            )

        app.dependency_overrides.clear()

        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["file"]["name"] == "report.txt"
        assert data["message"] is not None
        assert data["message"]["content"] == "请看这个文件"
        assert data["message"]["file_ids"] == ["file_01HTEST"]
        mock_svc.create.assert_called_once()
        mock_svc.add_usage.assert_called_once()

    def test_upload_without_content(self, client: TestClient, auth_admin, tmp_path):
        from app.api.v1.sessions import _get_file_service

        fake_ref = _fake_file_ref()

        mock_svc = AsyncMock()
        mock_svc.create = AsyncMock(return_value=fake_ref)
        mock_svc.add_usage = AsyncMock()

        session_doc = {
            "_id": "session_TEST",
            "user_id": "user_01HTEST",
            "agent_id": "agent_TEST",
            "title": "",
            "status": "active",
            "message_count": 0,
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:00:00",
        }

        app.dependency_overrides[_get_file_service] = lambda: mock_svc

        with (
            patch(
                "app.api.v1.sessions.SessionService.get_session",
                new_callable=AsyncMock,
                return_value=session_doc,
            ),
            patch(
                "app.engine.tool.workspace.WorkspaceManager.get_workspace",
            ) as mock_ws,
        ):
            mock_workspace = MagicMock()
            mock_workspace.input_dir = tmp_path / "input"
            mock_workspace.input_dir.mkdir(parents=True, exist_ok=True)
            mock_ws.return_value = mock_workspace

            resp = client.post(
                "/api/v1/sessions/session_TEST/files/upload",
                files={"file": ("report.txt", b"hello world", "text/plain")},
            )

        app.dependency_overrides.clear()

        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["file"]["name"] == "report.txt"
        assert data["message"] is None

    def test_upload_session_not_found(self, client: TestClient, auth_admin):
        from app.api.v1.sessions import _get_file_service

        mock_svc = AsyncMock()

        app.dependency_overrides[_get_file_service] = lambda: mock_svc

        with (
            patch(
                "app.api.v1.sessions.SessionService.get_session",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            resp = client.post(
                "/api/v1/sessions/session_NONEXIST/files/upload",
                files={"file": ("report.txt", b"hello", "text/plain")},
            )

        app.dependency_overrides.clear()

        assert resp.status_code == 404

    def test_upload_file_too_large(self, client: TestClient, auth_admin, tmp_path):
        from app.api.v1.sessions import _get_file_service

        mock_svc = AsyncMock()

        session_doc = {
            "_id": "session_TEST",
            "user_id": "user_01HTEST",
            "agent_id": "agent_TEST",
            "title": "",
            "status": "active",
            "message_count": 0,
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:00:00",
        }

        app.dependency_overrides[_get_file_service] = lambda: mock_svc

        with (
            patch(
                "app.api.v1.sessions.SessionService.get_session",
                new_callable=AsyncMock,
                return_value=session_doc,
            ),
            patch(
                "app.engine.tool.workspace.WorkspaceManager.get_workspace",
            ) as mock_ws,
        ):
            mock_workspace = MagicMock()
            mock_workspace.input_dir = tmp_path / "input"
            mock_workspace.input_dir.mkdir(parents=True, exist_ok=True)
            mock_ws.return_value = mock_workspace

            large_data = b"x" * (50 * 1024 * 1024 + 1)
            resp = client.post(
                "/api/v1/sessions/session_TEST/files/upload",
                files={"file": ("big.bin", large_data, "application/octet-stream")},
            )

        app.dependency_overrides.clear()

        assert resp.status_code == 413


# ---------------------------------------------------------------------------
# GET /sessions/{session_id} — messages include file_ids
# ---------------------------------------------------------------------------


class TestSessionDetailWithFiles:
    """GET /api/v1/sessions/{session_id} — file population in messages."""

    def test_session_detail_includes_files(self, client: TestClient, auth_admin):
        fake_ref = _fake_file_ref()
        session_doc = {
            "_id": "session_TEST",
            "user_id": "user_01HTEST",
            "agent_id": "agent_TEST",
            "title": "Test",
            "status": "active",
            "message_count": 1,
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:00:00",
        }
        messages = [
            {
                "_id": "msg_TEST",
                "session_id": "session_TEST",
                "role": "user",
                "content": "See attached",
                "timeline_entries": [],
                "file_ids": ["file_01HTEST"],
                "created_at": "2026-01-01T00:00:00",
            }
        ]

        mock_svc = AsyncMock()
        mock_svc.get = AsyncMock(return_value=fake_ref)

        with (
            patch(
                "app.api.v1.sessions.SessionService.get_session",
                new_callable=AsyncMock,
                return_value=session_doc,
            ),
            patch(
                "app.api.v1.sessions.MessageService.list_messages",
                new_callable=AsyncMock,
                return_value=messages,
            ),
            patch("app.api.v1.sessions._get_file_service", return_value=mock_svc),
        ):
            resp = client.get("/api/v1/sessions/session_TEST")

        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert len(data["messages"]) == 1
        msg = data["messages"][0]
        assert msg["file_ids"] == ["file_01HTEST"]
        assert len(msg["files"]) == 1
        assert msg["files"][0]["name"] == "report.txt"

    def test_session_detail_empty_files(self, client: TestClient, auth_admin):
        session_doc = {
            "_id": "session_TEST",
            "user_id": "user_01HTEST",
            "agent_id": "agent_TEST",
            "title": "Test",
            "status": "active",
            "message_count": 1,
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:00:00",
        }
        messages = [
            {
                "_id": "msg_TEST",
                "session_id": "session_TEST",
                "role": "user",
                "content": "Hello",
                "timeline_entries": [],
                "file_ids": [],
                "created_at": "2026-01-01T00:00:00",
            }
        ]

        with (
            patch(
                "app.api.v1.sessions.SessionService.get_session",
                new_callable=AsyncMock,
                return_value=session_doc,
            ),
            patch(
                "app.api.v1.sessions.MessageService.list_messages",
                new_callable=AsyncMock,
                return_value=messages,
            ),
        ):
            resp = client.get("/api/v1/sessions/session_TEST")

        assert resp.status_code == 200
        data = resp.json()
        msg = data["messages"][0]
        assert msg["file_ids"] == []
        assert msg["files"] == []


# ---------------------------------------------------------------------------
# Security: upload whitelist & path traversal (问题 4 & 5)
# ---------------------------------------------------------------------------


class TestUploadSecurity:
    """会话上传的安全校验：文件类型白名单 + 文件名路径穿越。"""

    def _setup(self, tmp_path):
        """返回 (mock_svc, session_doc)，并配置依赖覆盖。"""
        from app.api.v1.sessions import _get_file_service

        mock_svc = AsyncMock()
        mock_svc.create = AsyncMock(return_value=_fake_file_ref())
        mock_svc.add_usage = AsyncMock()
        app.dependency_overrides[_get_file_service] = lambda: mock_svc

        session_doc = {
            "_id": "session_TEST",
            "user_id": "user_01HTEST",
            "agent_id": "agent_TEST",
            "title": "",
            "status": "active",
            "message_count": 0,
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:00:00",
        }
        return mock_svc, session_doc, tmp_path / "input"

    @staticmethod
    def _post(client, filename, payload=b"hello"):
        return client.post(
            "/api/v1/sessions/session_TEST/files/upload",
            files={"file": (filename, payload, "application/octet-stream")},
        )

    def test_rejects_exe_extension(self, client: TestClient, auth_admin, tmp_path):
        """问题4：.exe 不在白名单，应返回 415。"""
        mock_svc, session_doc, input_dir = self._setup(tmp_path)
        with (
            patch(
                "app.api.v1.sessions.SessionService.get_session",
                new_callable=AsyncMock,
                return_value=session_doc,
            ),
            patch("app.engine.tool.workspace.WorkspaceManager.get_workspace") as mock_ws,
        ):
            ws = MagicMock()
            ws.input_dir = input_dir
            ws.input_dir.mkdir(parents=True, exist_ok=True)
            mock_ws.return_value = ws
            resp = self._post(client, "evil.exe")
        app.dependency_overrides.clear()
        assert resp.status_code == 415, resp.text
        mock_svc.create.assert_not_called()

    def test_allows_txt_extension(self, client: TestClient, auth_admin, tmp_path):
        """白名单内的 .txt 正常上传。"""
        mock_svc, session_doc, input_dir = self._setup(tmp_path)
        with (
            patch(
                "app.api.v1.sessions.SessionService.get_session",
                new_callable=AsyncMock,
                return_value=session_doc,
            ),
            patch("app.engine.tool.workspace.WorkspaceManager.get_workspace") as mock_ws,
        ):
            ws = MagicMock()
            ws.input_dir = input_dir
            ws.input_dir.mkdir(parents=True, exist_ok=True)
            mock_ws.return_value = ws
            resp = self._post(client, "notes.txt")
        app.dependency_overrides.clear()
        assert resp.status_code == 201, resp.text
        mock_svc.create.assert_called_once()
        # 传给文件库的文件名是清洗后的 basename
        assert mock_svc.create.call_args.kwargs["filename"] == "notes.txt"

    def test_filename_traversal_stripped_to_basename(
        self, client: TestClient, auth_admin, tmp_path
    ):
        """问题5：带 ../ 的文件名被剥离为 basename，不会越界写入。"""
        mock_svc, session_doc, input_dir = self._setup(tmp_path)
        with (
            patch(
                "app.api.v1.sessions.SessionService.get_session",
                new_callable=AsyncMock,
                return_value=session_doc,
            ),
            patch("app.engine.tool.workspace.WorkspaceManager.get_workspace") as mock_ws,
        ):
            ws = MagicMock()
            ws.input_dir = input_dir
            ws.input_dir.mkdir(parents=True, exist_ok=True)
            mock_ws.return_value = ws
            # ../evil.txt → basename "evil.txt"，仍落在 input_dir 内
            resp = self._post(client, "../../../etc/evil.txt")
        app.dependency_overrides.clear()
        assert resp.status_code == 201, resp.text
        # FileRef 存的是清洗后的纯文件名
        assert mock_svc.create.call_args.kwargs["filename"] == "evil.txt"
        # 物理文件确实落在 input_dir 内（而非越界到 /etc）
        written = list(input_dir.glob("evil*.txt"))
        assert written, "文件应写入 input_dir"
