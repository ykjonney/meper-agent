"""Tests for the CLI create-admin command (AC1, AC2, AC3, AC4)."""
import sys
from unittest.mock import AsyncMock, patch

import pytest
from app.cli.__main__ import main as cli_main


class TestCreateAdminCli:
    """Test CLI argument parsing and dispatch."""

    def test_help_runs_without_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Running CLI with no args prints help and exits 0."""
        # With no subcommand, our CLI calls parser.print_help() and sys.exit(0)
        monkeypatch.setattr(sys, "argv", ["app.cli"])
        with pytest.raises(SystemExit) as exc:
            cli_main()
        assert exc.value.code == 0

    def test_weak_password_exits_with_error(
        self,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """AC3: Weak password is rejected with exit code 1."""
        monkeypatch.setattr(
            sys, "argv",
            ["app.cli", "create-admin",
             "--username", "admin",
             "--password", "weak",
             "--email", "admin@example.com"],
        )
        with pytest.raises(SystemExit) as exc:
            cli_main()
        assert exc.value.code == 1

        captured = capsys.readouterr()
        assert "密码" in captured.err or "Error" in captured.err

    def test_successful_admin_creation(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """AC1 + AC4: Successful creation prints message and tokens."""
        from app.schemas.auth import AdminCreateResult, TokenResponse

        mock_result = AdminCreateResult(
            message="管理员账户已创建：username=admin",
            user_id="user_01HTEST",
            username="admin",
            tokens=TokenResponse(
                access_token="fake.access.token",
                refresh_token="fake.refresh.token",
            ),
        )

        # Patch the async method with an AsyncMock
        with patch(
            "app.services.user_service.UserService.create_admin_user",
            new=AsyncMock(return_value=mock_result),
        ):
            monkeypatch.setattr(
                sys, "argv",
                ["app.cli", "create-admin",
                 "--username", "admin",
                 "--password", "Strong1234",
                 "--email", "admin@example.com"],
            )
            cli_main()

        captured = capsys.readouterr()
        assert "管理员账户已创建" in captured.out
        assert "user_01HTEST" in captured.out
        assert "fake.access.token" in captured.out
        assert "fake.refresh.token" in captured.out

    def test_admin_already_exists_exits_with_error(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """AC2: Duplicate admin creation exits with error."""
        from app.core.errors import ForbiddenError

        with patch(
            "app.services.user_service.UserService.create_admin_user",
            new=AsyncMock(
                side_effect=ForbiddenError(
                    code="ADMIN_ALREADY_EXISTS",
                    message="管理员账户已存在，请使用用户管理界面",
                )
            ),
        ):
            monkeypatch.setattr(
                sys, "argv",
                ["app.cli", "create-admin",
                 "--username", "admin",
                 "--password", "Strong1234",
                 "--email", "admin@example.com"],
            )
            with pytest.raises(SystemExit) as exc:
                cli_main()
            assert exc.value.code == 1

            captured = capsys.readouterr()
            assert "管理员账户已存在" in captured.err
