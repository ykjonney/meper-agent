"""Tests for the builtin ``read`` tool (host-filesystem implementation).

The harness-era ``read`` reads files directly from the host filesystem (the old
``_read_via_sandbox`` container path was removed). ``read`` is a langchain
``StructuredTool``, so we invoke it via ``.invoke({"path": ...})``. Without a
workspace context, ``_safe_path_for_read`` resolves absolute paths as-is, which
lets us exercise ``read`` against a temp file without standing up a workspace.
"""
from app.engine.agent.builtin_tools import read


def _read(path: str) -> str:
    """Invoke the ``read`` StructuredTool with the given path."""
    return read.invoke({"path": path})


class TestRead:
    """Test reading files through the host-filesystem read() builtin."""

    def test_successful_read(self, tmp_path):
        """An existing file returns its content."""
        f = tmp_path / "test.txt"
        f.write_text("hello world\n", encoding="utf-8")

        result = _read(str(f))
        assert result == "hello world\n"

    def test_file_not_found(self, tmp_path):
        """A missing file returns a friendly error message."""
        result = _read(str(tmp_path / "missing.txt"))
        assert "not found" in result.lower()

    def test_truncates_large_content(self, tmp_path):
        """Content exceeding max_content is truncated with a notice."""
        f = tmp_path / "big.txt"
        large = "x" * 60_000
        f.write_text(large, encoding="utf-8")

        result = _read(str(f))
        assert len(result) < len(large)
        assert "truncated" in result.lower()
