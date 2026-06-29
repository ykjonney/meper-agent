"""Unit tests for :class:`SandboxExecutor` host-path translation.

The harness-era sandbox replaced the old ``_translate_container_paths`` (which
rewrote command strings) with ``_host_path`` — a static method that maps a
container-internal directory to the corresponding host-side path via the
``WORKSPACES_HOST_DIR`` / ``SKILLS_HOST_DIR`` settings. These tests cover
``_host_path`` and the ``SandboxResult`` dataclass.
"""
from __future__ import annotations

from pathlib import Path

from app.engine.tool.sandbox import SandboxExecutor, SandboxResult
from app.engine.tool.workspace import Workspace


def _make_workspace(root: Path) -> Workspace:
    return Workspace(
        root=root,
        input_dir=root / "input",
        output_dir=root / "output",
        tmp_dir=root / "tmp",
    )


class TestHostPath:
    """Tests for ``SandboxExecutor._host_path``."""

    def test_translate_workspaces_path(self, monkeypatch) -> None:
        """A container workspace path is translated to the host workspace path."""
        monkeypatch.setattr(
            "app.engine.tool.sandbox.settings.WORKSPACES_CONTAINER_DIR",
            "/workspace",
        )
        monkeypatch.setattr(
            "app.engine.tool.sandbox.settings.WORKSPACES_HOST_DIR",
            "/host/ws",
        )
        result = SandboxExecutor._host_path("/workspace/user1/sess1/tmp")
        assert result == "/host/ws/user1/sess1/tmp"

    def test_translate_skills_path(self, monkeypatch) -> None:
        """A container skills path is translated to the host skills path."""
        monkeypatch.setattr(
            "app.engine.tool.sandbox.settings.SKILLS_CONTAINER_DIR",
            "/data/skills",
        )
        monkeypatch.setattr(
            "app.engine.tool.sandbox.settings.SKILLS_HOST_DIR",
            "/host/skills",
        )
        result = SandboxExecutor._host_path("/data/skills/my-skill")
        assert result == "/host/skills/my-skill"

    def test_passthrough_when_container_equals_host(self, monkeypatch) -> None:
        """Local dev: container dir == host dir, so the path is unchanged."""
        monkeypatch.setattr(
            "app.engine.tool.sandbox.settings.WORKSPACES_CONTAINER_DIR",
            "/workspace",
        )
        monkeypatch.setattr(
            "app.engine.tool.sandbox.settings.WORKSPACES_HOST_DIR",
            "/workspace",
        )
        result = SandboxExecutor._host_path("/workspace/user1/sess1/tmp")
        assert result == "/workspace/user1/sess1/tmp"

    def test_passthrough_for_unrelated_path(self, monkeypatch) -> None:
        """A path under neither container dir is returned unchanged."""
        monkeypatch.setattr(
            "app.engine.tool.sandbox.settings.WORKSPACES_CONTAINER_DIR",
            "/workspace",
        )
        monkeypatch.setattr(
            "app.engine.tool.sandbox.settings.SKILLS_CONTAINER_DIR",
            "/data/skills",
        )
        result = SandboxExecutor._host_path("/etc/passwd")
        assert result == "/etc/passwd"


class TestSandboxResult:
    """Sanity checks on the SandboxResult dataclass defaults."""

    def test_defaults(self):
        r = SandboxResult(stdout="ok", stderr="", exit_code=0)
        assert r.timed_out is False
        assert r.duration == 0.0
