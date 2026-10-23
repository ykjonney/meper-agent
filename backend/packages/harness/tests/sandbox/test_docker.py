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


# ── 复用模式：常驻容器 + exec ────────────────────────────────────────────


class _ReuseFakeNotFound(Exception):
    """模拟 docker.errors.NotFound。"""


class _ReuseFakeContainer:
    def __init__(self, harness, name):
        self._h = harness
        self.name = name
        self.status = "running"
        self.exec_calls: list[list] = []
        self.removed = False
        # 可编排的 exec 行为：元素为 (code, (stdout, stderr)) 或 Exception
        self.exec_results: list = []

    def reload(self):
        if self.status == "gone":
            raise RuntimeError("container gone")

    def exec_run(self, cmd, user=None, workdir=None, environment=None, demux=False):
        self.exec_calls.append(list(cmd))
        if self.exec_results:
            item = self.exec_results.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
        return (0, (b"", b""))

    def remove(self, force=False):
        self.removed = True
        self.status = "gone"


def _install_reuse_fake(monkeypatch):
    """复用模式 fake：跟踪 run/get/exec 与容器生死；重置注册表与 client。"""
    import sys
    import types

    from agent_flow_harness.sandbox import docker as docker_mod

    class _Client:
        def __init__(self, h):
            self.containers = _Containers(h)

        def ping(self):
            return True

    class _Containers:
        def __init__(self, h):
            self._h = h

        def get(self, name):
            c = self._h.containers_by_name.get(name)
            if c is None or c.status == "gone":
                raise _ReuseFakeNotFound(name)
            return c

        def run(self, image=None, command=None, name=None, **kwargs):
            self._h.run_calls.append({"image": image, "command": command, "name": name})
            c = _ReuseFakeContainer(self._h, name)
            self._h.containers_by_name[name] = c
            return c

    class _H:
        def __init__(self):
            self.run_calls: list[dict] = []
            self.containers_by_name: dict[str, _ReuseFakeContainer] = {}

    h = _H()
    fake = types.ModuleType("docker")
    fake.errors = types.SimpleNamespace(NotFound=_ReuseFakeNotFound)  # type: ignore[attr-defined]
    fake.from_env = lambda timeout=30: _Client(h)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "docker", fake)
    docker_mod._reset_docker_client()
    with docker_mod._registry_lock:
        docker_mod._containers.clear()
    return h


def _make_reuse(tmp_path, **config_kwargs) -> DockerSandbox:
    return _make_enabled(tmp_path, reuse_container=True, **config_kwargs)


def test_reuse_two_commands_one_container(tmp_path, monkeypatch):
    """两次执行 → 1 次容器创建 + 2 次 exec（复用生效）。"""
    from agent_flow_harness.sandbox.docker import SANDBOX_LAST_USED_FILE

    h = _install_reuse_fake(monkeypatch)
    sb = _make_reuse(tmp_path)
    sb.execute_command("echo a")
    sb.execute_command("echo b")

    assert len(h.run_calls) == 1
    assert h.run_calls[0]["command"] == ["sleep", "infinity"]
    assert h.run_calls[0]["name"].startswith("agent-flow-sbx-")
    total_execs = [c for c in h.containers_by_name.values() if c.exec_calls]
    assert len(total_execs) == 1
    cmd = total_execs[0].exec_calls[0]
    # 触碰 + 超时包裹 + 原命令
    assert cmd[0] == "timeout" and cmd[1] == "--kill-after=10"
    assert SANDBOX_LAST_USED_FILE in cmd[-1]
    assert "echo a" in cmd[-1]


def test_reuse_adopts_existing_container(tmp_path, monkeypatch):
    """注册表为空但 daemon 上有同名容器（后端重启）→ 收养而非新建。"""
    from agent_flow_harness.sandbox import docker as docker_mod

    h = _install_reuse_fake(monkeypatch)
    name = docker_mod.sandbox_container_name(
        {"tmp": tmp_path}, "agent-sandbox:latest", "none"
    )
    h.containers_by_name[name] = _ReuseFakeContainer(h, name)

    sb = _make_reuse(tmp_path)
    sb.execute_command("x")

    assert len(h.run_calls) == 0  # 未新建


def test_reuse_recreates_on_exec_failure(tmp_path, monkeypatch):
    """容器死亡（exec 抛异常）→ 重建并重试一次，对调用方透明。"""
    from agent_flow_harness.sandbox import docker as docker_mod

    h = _install_reuse_fake(monkeypatch)
    name = docker_mod.sandbox_container_name(
        {"tmp": tmp_path}, "agent-sandbox:latest", "none"
    )
    dead = _ReuseFakeContainer(h, name)
    dead.exec_results = [RuntimeError("container died")]
    h.containers_by_name[name] = dead

    sb = _make_reuse(tmp_path)
    result = sb.execute_command("echo retry")

    assert result.exit_code == 0
    assert len(h.run_calls) == 1  # 重建了一次
    assert dead.removed is True


def test_reuse_timeout_maps_124(tmp_path, monkeypatch):
    """timeout(1) 退出码 124 → timed_out=True（与一次性容器语义对齐）。"""
    from agent_flow_harness.sandbox import docker as docker_mod

    h = _install_reuse_fake(monkeypatch)
    name = docker_mod.sandbox_container_name({"tmp": tmp_path}, "agent-sandbox:latest", "none")
    c = _ReuseFakeContainer(h, name)
    c.exec_results = [(124, (b"", b""))]
    h.containers_by_name[name] = c

    sb = _make_reuse(tmp_path)
    result = sb.execute_command("sleep 999")
    assert result.timed_out is True
    assert result.exit_code == -1
    assert "[timeout]" in result.stderr


def test_reuse_demux_split(tmp_path, monkeypatch):
    """exec demux 输出 → stdout/stderr 正确分流。"""
    from agent_flow_harness.sandbox import docker as docker_mod

    h = _install_reuse_fake(monkeypatch)
    name = docker_mod.sandbox_container_name({"tmp": tmp_path}, "agent-sandbox:latest", "none")
    c = _ReuseFakeContainer(h, name)
    c.exec_results = [(0, (b"out-bytes", b"err-bytes"))]
    h.containers_by_name[name] = c

    sb = _make_reuse(tmp_path)
    result = sb.execute_command("x")
    assert result.stdout == "out-bytes"
    assert result.stderr == "err-bytes"


def test_container_name_deterministic(tmp_path, monkeypatch):
    """同键同名（与 dict 顺序无关），键变名变。"""
    from agent_flow_harness.sandbox.docker import sandbox_container_name

    p1 = tmp_path / "a"
    p2 = tmp_path / "b"
    n1 = sandbox_container_name({"tmp": p1, "input": p2}, "img", "none")
    n2 = sandbox_container_name({"input": p2, "tmp": p1}, "img", "none")
    assert n1 == n2
    assert sandbox_container_name({"tmp": p1}, "img", "none") != sandbox_container_name(
        {"tmp": p1}, "img", "bridge"
    )
    assert sandbox_container_name({"tmp": p1}, "img", "none") != sandbox_container_name(
        {"tmp": p2}, "img", "none"
    )


def test_lru_eviction_at_cap(tmp_path, monkeypatch):
    """存活容器达上限 → 第 3 个工作区挤掉最久未用的（总数不超上限）。"""
    h = _install_reuse_fake(monkeypatch)
    for i in range(3):
        wdir = tmp_path / f"w{i}"
        wdir.mkdir()
        sb = _make_reuse(wdir, max_containers=2)
        sb.execute_command(f"echo {i}")

    assert len(h.run_calls) == 3  # 三个工作区各建一次
    live = [c for c in h.containers_by_name.values() if not c.removed]
    assert len(live) == 2  # w0（最久未用）被驱逐


def test_reuse_config_invariant():
    """max_containers <= max_concurrent → 配置即报错（LRU 需要空闲容器可逐）。"""
    import pytest

    with pytest.raises(ValueError, match="max_containers must exceed max_concurrent"):
        DockerSandboxConfig(reuse_container=True, max_containers=4, max_concurrent=8)


def test_reuse_remove_sandbox_container_idempotent(tmp_path, monkeypatch):
    """remove_sandbox_container 幂等：存在则删返回 True，不存在返回 False。"""
    from agent_flow_harness.sandbox import docker as docker_mod
    from agent_flow_harness.sandbox.docker import remove_sandbox_container

    h = _install_reuse_fake(monkeypatch)
    name = docker_mod.sandbox_container_name({"tmp": tmp_path}, "agent-sandbox:latest", "none")
    h.containers_by_name[name] = _ReuseFakeContainer(h, name)

    assert remove_sandbox_container(name) is True
    assert h.containers_by_name[name].removed is True
    assert remove_sandbox_container(name) is False  # 已删，幂等


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
