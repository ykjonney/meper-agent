"""Sandbox executor — runs bash commands inside isolated Docker containers.

Each ``execute()`` call spins up a short-lived container, runs the command,
captures stdout/stderr, and tears the container down.  Containers have no
network access, a read-only root filesystem, and strict resource limits.

Workspace directories are mounted into the container:
  - ``tmp/``    → ``/workspace/tmp``    (rw)
  - ``input/``  → ``/workspace/input``  (ro)
  - ``output/`` → ``/workspace/output`` (rw)
  - ``SKILLS_DIR`` → ``/data/skills``  (ro)

When ``SANDBOX_ENABLED`` is False (default for local dev), the executor
falls back to ``subprocess.run()`` so development works without Docker.
"""
from __future__ import annotations

import contextlib
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from app.core.config import settings
from app.engine.tool.workspace import Workspace


@dataclass
class SandboxResult:
    """Result of a sandbox command execution."""

    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool = False
    duration: float = 0.0


class SandboxExecutor:
    """Execute shell commands inside an isolated Docker container.

    Thread-safe: each ``execute()`` creates an independent container,
    so concurrent calls do not interfere.
    """

    def __init__(
        self,
        image: str | None = None,
        mem_limit: str | None = None,
        cpu_quota: int | None = None,
        timeout: int | None = None,
        max_output_bytes: int | None = None,
    ) -> None:
        self.image = image or settings.SANDBOX_IMAGE
        self.mem_limit = mem_limit or settings.SANDBOX_MEM_LIMIT
        self.cpu_quota = cpu_quota or settings.SANDBOX_CPU_QUOTA
        self.timeout = timeout or settings.SANDBOX_TIMEOUT
        self.max_output_bytes = max_output_bytes or settings.SANDBOX_MAX_OUTPUT_BYTES

    # ── Public API ──────────────────────────────────────────────────────

    def execute(
        self,
        command: str,
        workspace: Workspace,
        timeout: int | None = None,
        env_vars: dict[str, str] | None = None,
    ) -> SandboxResult:
        """Run *command* inside a Docker sandbox container.

        Falls back to ``_execute_subprocess`` when Docker is unavailable
        or ``SANDBOX_ENABLED`` is False.
        """
        effective_timeout = timeout or self.timeout

        if not settings.SANDBOX_ENABLED:
            return self._execute_subprocess(
                command, workspace, effective_timeout, env_vars
            )

        try:
            return self._execute_docker(
                command, workspace, effective_timeout, env_vars
            )
        except _DockerUnavailableError as exc:
            logger.warning(
                "sandbox_docker_unavailable, falling back to subprocess",
                error=str(exc),
            )
            return self._execute_subprocess(
                command, workspace, effective_timeout, env_vars
            )
        except Exception as exc:
            logger.error("sandbox_execute_error", error=str(exc))
            return SandboxResult(
                stdout="",
                stderr=f"Sandbox execution error: {exc}",
                exit_code=1,
            )

    # ── Docker execution ────────────────────────────────────────────────

    def _execute_docker(
        self,
        command: str,
        workspace: Workspace,
        timeout: int,
        env_vars: dict[str, str] | None,
    ) -> SandboxResult:
        """Run command inside a Docker container."""
        import docker

        try:
            client = docker.from_env(timeout=30)
            client.ping()
        except Exception as exc:
            raise _DockerUnavailableError(str(exc)) from exc

        # Ensure workspace dirs exist before mounting
        workspace.tmp_dir.mkdir(parents=True, exist_ok=True)
        workspace.output_dir.mkdir(parents=True, exist_ok=True)
        workspace.input_dir.mkdir(parents=True, exist_ok=True)

        # Build volume mounts
        volumes = {
            str(workspace.tmp_dir): {"bind": "/workspace/tmp", "mode": "rw"},
            str(workspace.output_dir): {"bind": "/workspace/output", "mode": "rw"},
            str(workspace.input_dir): {"bind": "/workspace/input", "mode": "ro"},
        }

        # Mount SKILLS_DIR read-only if it exists
        skills_dir = Path(os.path.expanduser(settings.SKILLS_DIR))
        if skills_dir.exists():
            volumes[str(skills_dir)] = {"bind": "/data/skills", "mode": "ro"}

        # Build environment
        env = {"PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1"}
        if env_vars:
            env.update(env_vars)

        start = time.monotonic()
        timed_out = False

        try:
            container = client.containers.run(
                image=self.image,
                command=["bash", "-c", command],
                volumes=volumes,
                environment=env,
                working_dir="/workspace/tmp",
                user="sandbox",
                # Security
                network_mode="none",
                read_only=True,
                security_opt=["no-new-privileges"],
                # Resources
                mem_limit=self.mem_limit,
                cpu_quota=self.cpu_quota,
                cpu_period=100_000,
                # tmpfs for /tmp (ephemeral scratch)
                tmpfs={"/tmp": "size=64m,noexec"},
                # Lifecycle
                detach=True,
                auto_remove=False,
            )
        except docker.errors.ImageNotFound:
            raise _DockerUnavailableError(
                f"Sandbox image '{self.image}' not found. "
                "Build with: docker build -t agent-sandbox:latest -f deploy/Dockerfile.sandbox ."
            ) from None
        except Exception as exc:
            raise _DockerUnavailableError(str(exc)) from exc

        try:
            result = container.wait(timeout=timeout)
            exit_code = result.get("StatusCode", -1)
        except Exception:
            # Timeout — kill the container
            timed_out = True
            exit_code = -1
            with contextlib.suppress(Exception):
                container.kill()

        duration = time.monotonic() - start

        # Collect logs
        try:
            stdout_raw = container.logs(stdout=True, stderr=False)
            stderr_raw = container.logs(stdout=False, stderr=True)
        except Exception:
            stdout_raw = b""
            stderr_raw = b""

        # Cleanup
        with contextlib.suppress(Exception):
            container.remove(force=True)

        stdout = _truncate(stdout_raw.decode("utf-8", errors="replace"), self.max_output_bytes)
        stderr = _truncate(stderr_raw.decode("utf-8", errors="replace"), self.max_output_bytes)

        if timed_out:
            stderr += f"\n[timeout] Command exceeded {timeout}s and was killed."

        logger.info(
            "sandbox_docker_executed",
            user_id=workspace.user_id,
            session_id=workspace.session_id,
            exit_code=exit_code,
            timed_out=timed_out,
            duration=f"{duration:.2f}s",
            stdout_len=len(stdout),
            stderr_len=len(stderr),
            command_preview=command[:80],
        )

        return SandboxResult(
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
            timed_out=timed_out,
            duration=duration,
        )

    # ── Subprocess fallback ─────────────────────────────────────────────

    def _execute_subprocess(
        self,
        command: str,
        workspace: Workspace,
        timeout: int,
        env_vars: dict[str, str] | None,
    ) -> SandboxResult:
        """Fallback: run command via subprocess (no isolation).

        Used when SANDBOX_ENABLED=False (local dev) or Docker is unavailable.
        """
        workspace.tmp_dir.mkdir(parents=True, exist_ok=True)

        env = {**os.environ}
        if env_vars:
            env.update(env_vars)

        start = time.monotonic()
        timed_out = False

        try:
            proc = subprocess.run(
                ["bash", "-c", command],
                cwd=str(workspace.tmp_dir),
                capture_output=True,
                timeout=timeout,
                env=env,
            )
            exit_code = proc.returncode
            stdout_raw = proc.stdout
            stderr_raw = proc.stderr
        except subprocess.TimeoutExpired:
            timed_out = True
            exit_code = -1
            stdout_raw = b""
            stderr_raw = f"[timeout] Command exceeded {timeout}s and was killed.".encode()

        duration = time.monotonic() - start

        stdout = _truncate(stdout_raw.decode("utf-8", errors="replace"), self.max_output_bytes)
        stderr = _truncate(stderr_raw.decode("utf-8", errors="replace"), self.max_output_bytes)

        logger.info(
            "sandbox_subprocess_executed",
            user_id=workspace.user_id,
            session_id=workspace.session_id,
            exit_code=exit_code,
            timed_out=timed_out,
            duration=f"{duration:.2f}s",
            command_preview=command[:80],
        )

        return SandboxResult(
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
            timed_out=timed_out,
            duration=duration,
        )


# ── Helpers ───────────────────────────────────────────────────────────────────


def _truncate(text: str, max_bytes: int) -> str:
    """Truncate *text* to *max_bytes* UTF-8 bytes, appending a notice if cut."""
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    truncated = encoded[:max_bytes].decode("utf-8", errors="ignore")
    return truncated + f"\n\n[truncated — output exceeded {max_bytes} bytes]"


class _DockerUnavailableError(Exception):
    """Raised when Docker daemon is unreachable or image is missing."""
