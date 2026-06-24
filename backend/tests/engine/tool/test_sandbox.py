"""Unit tests for :class:`SandboxExecutor` path translation."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from app.engine.tool.sandbox import SandboxExecutor
from app.engine.tool.workspace import Workspace


def _make_workspace(root: Path) -> Workspace:
    return Workspace(
        root=root,
        input_dir=root / "input",
        output_dir=root / "output",
        tmp_dir=root / "tmp",
        scope="task",
    )


class TestTranslateContainerPaths:
    """Tests for ``SandboxExecutor._translate_container_paths``."""

    def test_noop_when_paths_match(self, tmp_path: Path) -> None:
        """When container path == host path, command is unchanged."""
        ws = _make_workspace(tmp_path)
        with (
            patch("app.engine.tool.sandbox.settings") as mock_settings,
        ):
            # Container and host paths are identical
            mock_settings.SANDBOX_CONTAINER_SKILLS_DIR = "/data/skills"
            mock_settings.SKILLS_CONTAINER_DIR = "/data/skills"
            mock_settings.SANDBOX_CONTAINER_WORKSPACE_DIR = "/workspace"

            result = SandboxExecutor._translate_container_paths(
                "cd /data/skills/foo && python3 script.py",
                ws,
            )

        # No translation because SKILLS paths match
        assert result == "cd /data/skills/foo && python3 script.py"

    def test_translates_skills_path(self, tmp_path: Path) -> None:
        """Container skills path is translated to host skills path."""
        ws = _make_workspace(tmp_path)
        with patch("app.engine.tool.sandbox.settings") as mock_settings:
            mock_settings.SANDBOX_CONTAINER_SKILLS_DIR = "/data/skills"
            mock_settings.SKILLS_CONTAINER_DIR = str(tmp_path / "skills")
            mock_settings.SANDBOX_CONTAINER_WORKSPACE_DIR = "/workspace"

            result = SandboxExecutor._translate_container_paths(
                "cd /data/skills/my-skill && ls",
                ws,
            )

        assert f"cd {tmp_path}/skills/my-skill && ls" == result

    def test_translates_workspace_path(self, tmp_path: Path) -> None:
        """Container workspace path is translated to workspace.root."""
        ws = _make_workspace(tmp_path)
        with patch("app.engine.tool.sandbox.settings") as mock_settings:
            mock_settings.SANDBOX_CONTAINER_SKILLS_DIR = "/data/skills"
            mock_settings.SKILLS_CONTAINER_DIR = "/data/skills"
            mock_settings.SANDBOX_CONTAINER_WORKSPACE_DIR = "/workspace"

            result = SandboxExecutor._translate_container_paths(
                "cat /workspace/output/report.txt",
                ws,
            )

        assert f"cat {tmp_path}/output/report.txt" == result

    def test_translates_both_in_single_command(self, tmp_path: Path) -> None:
        """Multiple container paths in one command are all translated."""
        ws = _make_workspace(tmp_path)
        host_skills = str(tmp_path / "host_skills")
        with patch("app.engine.tool.sandbox.settings") as mock_settings:
            mock_settings.SANDBOX_CONTAINER_SKILLS_DIR = "/data/skills"
            mock_settings.SKILLS_CONTAINER_DIR = host_skills
            mock_settings.SANDBOX_CONTAINER_WORKSPACE_DIR = "/workspace"

            result = SandboxExecutor._translate_container_paths(
                "cp /data/skills/foo/data.csv /workspace/output/ && ls /workspace/tmp",
                ws,
            )

        assert f"cp {host_skills}/foo/data.csv {tmp_path}/output/" in result
        assert f"ls {tmp_path}/tmp" in result

    def test_no_translation_when_no_container_paths(self, tmp_path: Path) -> None:
        """Command with no container paths is unchanged."""
        ws = _make_workspace(tmp_path)
        with patch("app.engine.tool.sandbox.settings") as mock_settings:
            mock_settings.SANDBOX_CONTAINER_SKILLS_DIR = "/data/skills"
            mock_settings.SKILLS_CONTAINER_DIR = "/opt/skills"
            mock_settings.SANDBOX_CONTAINER_WORKSPACE_DIR = "/workspace"

            result = SandboxExecutor._translate_container_paths(
                "echo hello world",
                ws,
            )

        assert result == "echo hello world"
