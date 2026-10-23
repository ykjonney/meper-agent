"""Tests for sandbox_lifecycle.destroy_workspace_sandbox（复用容器显式销毁钩子）.

Fake docker module injected via sys.modules；名字推导与 harness
sandbox_container_name 一致（tmp/input/output 三挂载 + image + network）。
"""
import sys
import types

from app.core.config import settings
from app.engine.harness_integration.sandbox_lifecycle import destroy_workspace_sandbox


class _FakeNotFoundError(Exception):
    pass


class _FakeContainer:
    def __init__(self, name):
        self.name = name
        self.status = "running"
        self.removed = False

    def remove(self, force=False):
        self.removed = True


def _install_fake_docker(monkeypatch, containers_by_name: dict[str, _FakeContainer]):
    """注入 fake docker 模块并重置 harness client 缓存。"""
    from agent_flow_harness.sandbox import docker as docker_mod

    class _Containers:
        def get(self, name):
            c = containers_by_name.get(name)
            if c is None:
                raise _FakeNotFoundError(name)
            return c

    class _Client:
        def __init__(self):
            self.containers = _Containers()

        def ping(self):
            return True

    fake = types.ModuleType("docker")
    fake.errors = types.SimpleNamespace(NotFound=_FakeNotFoundError)  # type: ignore[attr-defined]
    fake.from_env = lambda timeout=30: _Client()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "docker", fake)
    docker_mod._reset_docker_client()


def test_disabled_is_noop(monkeypatch, tmp_path):
    """SANDBOX_ENABLED=False → 不触碰 docker，不抛异常。"""
    monkeypatch.setattr(settings, "SANDBOX_ENABLED", False)
    # 不注入 fake docker —— 若代码尝试 import/调用真实 docker 即失败
    destroy_workspace_sandbox(tmp_path)


def test_destroy_removes_container(monkeypatch, tmp_path):
    """开启复用 + 容器存在 → 按推导名删除。"""
    from agent_flow_harness.sandbox.docker import sandbox_container_name

    monkeypatch.setattr(settings, "SANDBOX_ENABLED", True)
    monkeypatch.setattr(settings, "SANDBOX_REUSE_CONTAINER", True)
    name = sandbox_container_name(
        {"tmp": tmp_path / "tmp", "input": tmp_path / "input", "output": tmp_path / "output"},
        image=settings.SANDBOX_IMAGE,
        network_mode=settings.SANDBOX_NETWORK_MODE,
    )
    container = _FakeContainer(name)
    _install_fake_docker(monkeypatch, {name: container})

    destroy_workspace_sandbox(tmp_path)  # 不应抛异常

    assert container.removed is True


def test_destroy_missing_container_is_silent(monkeypatch, tmp_path):
    """容器不存在（从未创建/已回收）→ 幂等无异常。"""
    monkeypatch.setattr(settings, "SANDBOX_ENABLED", True)
    monkeypatch.setattr(settings, "SANDBOX_REUSE_CONTAINER", True)
    _install_fake_docker(monkeypatch, {})

    destroy_workspace_sandbox(tmp_path)


def test_reuse_off_is_noop(monkeypatch, tmp_path):
    """SANDBOX_REUSE_CONTAINER=False → 不触碰 docker。"""
    monkeypatch.setattr(settings, "SANDBOX_ENABLED", True)
    monkeypatch.setattr(settings, "SANDBOX_REUSE_CONTAINER", False)
    destroy_workspace_sandbox(tmp_path)
