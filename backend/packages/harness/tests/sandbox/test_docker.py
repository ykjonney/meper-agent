"""DockerSandbox 测试 — 降级闸（fail-closed）与 subprocess 路径（Docker 在 CI 不可用）。"""
from __future__ import annotations


import pytest

from agent_flow_harness.sandbox.docker import DockerSandbox, DockerSandboxConfig


def _make_sandbox(tmp_path, enabled=False, allow_local_fallback=True) -> DockerSandbox:
    """显式开启降级以测试 subprocess 路径；默认配置的拒绝路径另有单测覆盖。"""
    config = DockerSandboxConfig(enabled=enabled, allow_local_fallback=allow_local_fallback)
    return DockerSandbox(
        sandbox_id="test",
        work_dir=tmp_path,
        mounts={"tmp": tmp_path / "tmp", "output": tmp_path / "output"},
        config=config,
        timeout=10,
    )


def test_subprocess_fallback_success(tmp_path):
    """enabled=False + 显式允许降级 → subprocess 执行。"""
    sb = _make_sandbox(tmp_path)
    result = sb.execute_command("echo hello")
    assert result.exit_code == 0
    assert "hello" in result.stdout


def test_subprocess_fallback_nonzero(tmp_path):
    sb = _make_sandbox(tmp_path)
    result = sb.execute_command("exit 3")
    assert result.exit_code == 3


def test_subprocess_fallback_timeout(tmp_path):
    sb = _make_sandbox(tmp_path, enabled=False)
    sb._timeout = 1
    result = sb.execute_command("sleep 10")
    assert result.timed_out is True


def test_disabled_without_fallback_refuses(tmp_path):
    """enabled=False 且未允许降级（默认）→ fail-closed 拒绝执行。"""
    sb = _make_sandbox(tmp_path, enabled=False, allow_local_fallback=False)
    result = sb.execute_command("echo should_not_run")
    assert result.exit_code == 1
    assert "fallback is not allowed" in result.stderr


def test_docker_fallback_on_unavailable(tmp_path):
    """enabled=True 但 Docker 不可用 + 显式允许降级 → fallback 到 subprocess。"""
    config = DockerSandboxConfig(
        enabled=True, image="nonexistent:latest", allow_local_fallback=True,
    )
    sb = DockerSandbox(
        sandbox_id="t", work_dir=tmp_path, mounts={"tmp": tmp_path},
        config=config, timeout=10,
    )
    result = sb.execute_command("echo fallback")
    # Docker 不可用 → fallback subprocess
    assert result.exit_code == 0
    assert "fallback" in result.stdout


def test_docker_unavailable_without_fallback_refuses(tmp_path):
    """enabled=True 但 Docker 不可用且未允许降级 → fail-closed 拒绝执行。"""
    config = DockerSandboxConfig(enabled=True, image="nonexistent:latest")
    sb = DockerSandbox(
        sandbox_id="t", work_dir=tmp_path, mounts={"tmp": tmp_path},
        config=config, timeout=10,
    )
    result = sb.execute_command("echo should_not_run")
    assert result.exit_code == 1
    assert "docker unavailable" in result.stderr


def test_docker_config_defaults():
    config = DockerSandboxConfig()
    assert config.image == "agent-sandbox:latest"
    assert config.enabled is False
    assert config.mem_limit == "512m"
    assert config.network_mode == "none"
    assert config.allow_local_fallback is False
    assert config.max_concurrent == 0


# ── 进程级 client 复用 / 并发信号量 / label / stderr 拆分 ────────────────
# 通过向 sys.modules 注入 fake docker 模块覆盖真实路径（CI 无 Docker daemon）。


def _install_fake_docker(monkeypatch, *, wait_seconds: float = 0.0) -> dict:
    """注入 fake docker 模块并重置 client 单例，返回可断言的 state。"""
    import sys
    import threading
    import time
    import types

    from agent_flow_harness.sandbox import docker as docker_mod

    state: dict = {"from_env_calls": 0, "active": 0, "max_active": 0, "run_kwargs": {}}
    lock = threading.Lock()

    class _FakeContainer:
        def wait(self, timeout=None):
            with lock:
                state["active"] += 1
                state["max_active"] = max(state["max_active"], state["active"])
            if wait_seconds:
                time.sleep(wait_seconds)
            with lock:
                state["active"] -= 1
            return {"StatusCode": 0}

        def logs(self, stdout=True, stderr=True):
            if stdout and not stderr:
                return b"fake-stdout"
            if stderr and not stdout:
                return b"fake-stderr"
            return b""

        def kill(self):
            pass

        def remove(self, force=False):
            state["removed"] = True

    class _FakeContainers:
        def run(self, image=None, command=None, **kwargs):
            state["run_kwargs"] = kwargs
            return _FakeContainer()

    class _FakeClient:
        def __init__(self):
            with lock:
                state["from_env_calls"] += 1
            self.containers = _FakeContainers()

        def ping(self):
            return True

    fake = types.ModuleType("docker")
    fake.from_env = lambda timeout=30: _FakeClient()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "docker", fake)
    docker_mod._reset_docker_client()
    return state


def _make_enabled(tmp_path, **config_kwargs) -> DockerSandbox:
    config = DockerSandboxConfig(enabled=True, allow_local_fallback=False, **config_kwargs)
    return DockerSandbox(
        sandbox_id="t", work_dir=tmp_path, mounts={"tmp": tmp_path},
        config=config, timeout=10,
    )


def test_docker_client_reused_across_commands(tmp_path, monkeypatch):
    """两次执行只构造一次 client（from_env+ping 昂贵，进程级复用）。"""
    state = _install_fake_docker(monkeypatch)
    sb = _make_enabled(tmp_path)
    sb.execute_command("a")
    sb.execute_command("b")
    assert state["from_env_calls"] == 1


def test_max_concurrent_limits_parallel_executions(tmp_path, monkeypatch):
    """max_concurrent=1 时多线程并发实测 ≤1（信号量串行化）。"""
    import threading

    from agent_flow_harness.sandbox import docker as docker_mod

    state = _install_fake_docker(monkeypatch, wait_seconds=0.3)
    sb = _make_enabled(tmp_path, max_concurrent=1)
    threads = [
        threading.Thread(target=sb.execute_command, args=(f"cmd{i}",)) for i in range(3)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert state["max_active"] == 1
    docker_mod._reset_docker_client()


def test_unlimited_concurrency_runs_in_parallel(tmp_path, monkeypatch):
    """对照组：max_concurrent=0（不限）时多线程真实并行。"""
    import threading

    from agent_flow_harness.sandbox import docker as docker_mod

    state = _install_fake_docker(monkeypatch, wait_seconds=0.3)
    sb = _make_enabled(tmp_path)
    threads = [
        threading.Thread(target=sb.execute_command, args=(f"cmd{i}",)) for i in range(3)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert state["max_active"] >= 2
    docker_mod._reset_docker_client()


def test_containers_labeled_for_orphan_sweep(tmp_path, monkeypatch):
    """容器打 agent-flow.* label（孤儿清扫任务的识别依据）。"""
    state = _install_fake_docker(monkeypatch)
    sb = _make_enabled(tmp_path)
    sb.execute_command("x")
    labels = state["run_kwargs"]["labels"]
    assert labels["agent-flow.sandbox"] == "true"
    assert labels["agent-flow.sandbox-id"] == "t"
    assert labels["agent-flow.created-at"].isdigit()


def test_stdout_stderr_split(tmp_path, monkeypatch):
    """stdout/stderr 分流回收（合并调用会丢失 stderr）。"""
    _install_fake_docker(monkeypatch)
    sb = _make_enabled(tmp_path)
    result = sb.execute_command("x")
    assert result.stdout == "fake-stdout"
    assert result.stderr == "fake-stderr"


def test_docker_config_custom():
    config = DockerSandboxConfig(
        image="my-sandbox:v2",
        enabled=True,
        mem_limit="2g",
        cpu_quota=200_000,
        network_mode="bridge",
    )
    assert config.image == "my-sandbox:v2"
    assert config.enabled is True
    assert config.mem_limit == "2g"
    assert config.network_mode == "bridge"


def test_id_property(tmp_path):
    sb = DockerSandbox(sandbox_id="my-id", work_dir=tmp_path)
    assert sb.id == "my-id"


def test_file_operations_work(tmp_path):
    """文件操作: write 写到 output_dir, read/glob/grep 读 work_dir。"""
    sb = _make_sandbox(tmp_path)
    # write goes to output_dir
    sb.write_file("note.txt", "hello world")
    assert (tmp_path / "output" / "note.txt").read_text() == "hello world"

    # read/glob operate on work_dir
    (tmp_path / "a.py").write_text("print('x')")
    matches = sb.glob(".", "*.py")
    assert any("a.py" in m for m in matches)


def test_path_traversal_blocked(tmp_path):
    sb = _make_sandbox(tmp_path)
    with pytest.raises((PermissionError, ValueError)):
        sb.read_file("../../../etc/passwd")


# ── workspace 模式（work_dir 为 {root}/tmp 结构，app 场景）────────────


def _make_workspace_sandbox(tmp_path) -> DockerSandbox:
    root = tmp_path / "ws"
    work_dir = root / "tmp"
    work_dir.mkdir(parents=True)
    (root / "input").mkdir()
    (root / "output").mkdir()
    return DockerSandbox(
        sandbox_id="ws",
        work_dir=work_dir,
        mounts={
            "tmp": work_dir,
            "input": root / "input",
            "output": root / "output",
        },
        config=DockerSandboxConfig(enabled=False, allow_local_fallback=True),
        timeout=10,
    )


def test_ws_write_output_edit_bare_name(tmp_path):
    """与 LocalSandbox 同构：write 产物经回退可被 edit 裸文件名编辑。"""
    sb = _make_workspace_sandbox(tmp_path)
    sb.write_file("report.md", "# v1\n")
    sb.edit_file("report.md", "# v1", "# v2")
    assert (tmp_path / "ws" / "output" / "report.md").read_text(encoding="utf-8") == "# v2\n"


def test_ws_edit_input_rejected(tmp_path):
    """与 LocalSandbox 同构：input 只读，edit 被拒、read 可用。"""
    sb = _make_workspace_sandbox(tmp_path)
    (tmp_path / "ws" / "input" / "spec.md").write_text("spec\n", encoding="utf-8")
    assert sb.read_file("/workspace/input/spec.md") == "spec\n"
    with pytest.raises(PermissionError, match="read-only input"):
        sb.edit_file("input/spec.md", "spec", "modified")


# ── bind_source_mapper：容器视角 → daemon 宿主视角的 volumes 源换算 ──


def _make_mapped_sandbox(root, mapper) -> DockerSandbox:
    return DockerSandbox(
        sandbox_id="mapped",
        work_dir=root / "tmp",
        mounts={
            "tmp": root / "tmp",
            "input": root / "input",
            "output": root / "output",
        },
        config=DockerSandboxConfig(enabled=False, bind_source_mapper=mapper),
        timeout=10,
    )


def test_build_volumes_without_mapper_keeps_source(tmp_path):
    """无 mapper（本地开发，两路径相同）：volumes 源 = 进程视角绝对路径。"""
    root = tmp_path / "ws"
    for sub in ("input", "output", "tmp"):
        (root / sub).mkdir(parents=True)
    sb = _make_mapped_sandbox(root, mapper=None)
    volumes = sb._build_volumes()
    assert str((root / "input").resolve()) in volumes
    assert volumes[str((root / "input").resolve())] == {
        "bind": "/workspace/input",
        "mode": "ro",
    }
    assert volumes[str((root / "output").resolve())]["mode"] == "rw"


def test_build_volumes_applies_mapper(tmp_path):
    """mapper 换算 volumes 源前缀；挂载点/权限约定不变。

    backend 容器化部署：进程视角 /data/workspaces → daemon 宿主视角
    /host/workspaces，未换算则 daemon 自动建 root 空目录、文件链路断裂。
    """
    root = tmp_path / "ws"
    for sub in ("input", "output", "tmp"):
        (root / sub).mkdir(parents=True)
    prefix = str(tmp_path.resolve())

    def mapper(path: str) -> str:
        if path.startswith(prefix):
            return "/host" + path[len(prefix):]
        return path

    sb = _make_mapped_sandbox(root, mapper=mapper)
    volumes = sb._build_volumes()

    assert set(volumes) == {
        f"/host{str((root / sub).resolve())[len(prefix):]}"
        for sub in ("input", "output", "tmp")
    }
    assert volumes[f"/host{str((root / 'input').resolve())[len(prefix):]}"] == {
        "bind": "/workspace/input",
        "mode": "ro",
    }
    assert volumes[f"/host{str((root / 'tmp').resolve())[len(prefix):]}"]["mode"] == "rw"
