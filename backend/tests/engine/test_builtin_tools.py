"""Tests for _read_via_sandbox in builtin_tools."""
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from app.engine.agent.builtin_tools import _read_via_sandbox
from app.engine.tool.workspace import Workspace
from app.engine.tool.sandbox import SandboxResult


def _make_workspace() -> Workspace:
    """Create a minimal Workspace for testing."""
    r = Path("/host/ws/user/session")
    return Workspace(
        root=r,
        input_dir=r / "input",
        output_dir=r / "output",
        tmp_dir=r / "tmp",
    )


class TestReadViaSandbox:
    """Test reading files through the sandbox container."""

    def test_successful_read(self):
        """A successful cat returns the file content."""
        ws = _make_workspace()
        mock_result = SandboxResult(
            stdout="hello world\n",
            stderr="",
            exit_code=0,
        )
        with patch("app.engine.tool.sandbox.SandboxExecutor") as MockExec:
            MockExec.return_value.execute.return_value = mock_result
            result = _read_via_sandbox("/workspace/tmp/test.txt", ws)
        assert result == "hello world\n"

    def test_file_not_found(self):
        """cat failing with 'No such file' returns a friendly error."""
        ws = _make_workspace()
        mock_result = SandboxResult(
            stdout="",
            stderr="cat: /workspace/tmp/missing.txt: No such file or directory",
            exit_code=1,
        )
        with patch("app.engine.tool.sandbox.SandboxExecutor") as MockExec:
            MockExec.return_value.execute.return_value = mock_result
            result = _read_via_sandbox("/workspace/tmp/missing.txt", ws)
        assert "File not found" in result

    def test_timeout(self):
        """A timed-out read returns a timeout error."""
        ws = _make_workspace()
        mock_result = SandboxResult(
            stdout="",
            stderr="[timeout]",
            exit_code=-1,
            timed_out=True,
        )
        with patch("app.engine.tool.sandbox.SandboxExecutor") as MockExec:
            MockExec.return_value.execute.return_value = mock_result
            result = _read_via_sandbox("/workspace/tmp/huge.bin", ws)
        assert "timed out" in result.lower()

    def test_other_error(self):
        """A non-zero exit code with other stderr returns the error."""
        ws = _make_workspace()
        mock_result = SandboxResult(
            stdout="",
            stderr="Permission denied",
            exit_code=1,
        )
        with patch("app.engine.tool.sandbox.SandboxExecutor") as MockExec:
            MockExec.return_value.execute.return_value = mock_result
            result = _read_via_sandbox("/workspace/tmp/secret.txt", ws)
        assert "Permission denied" in result

    def test_truncates_large_content(self):
        """Content exceeding max_content is truncated."""
        ws = _make_workspace()
        large = "x" * 60_000
        mock_result = SandboxResult(
            stdout=large,
            stderr="",
            exit_code=0,
        )
        with patch("app.engine.tool.sandbox.SandboxExecutor") as MockExec:
            MockExec.return_value.execute.return_value = mock_result
            result = _read_via_sandbox("/workspace/tmp/big.txt", ws)
        assert len(result) < len(large)
        assert "truncated" in result
