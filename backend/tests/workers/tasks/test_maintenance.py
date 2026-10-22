"""Tests for maintenance.cleanup_orphan_sandboxes（孤儿沙盒容器清扫）.

Fake docker module injected via sys.modules（CI 无 Docker daemon）；
label 约定与 harness DockerSandbox._execute_docker 一致。
"""
import sys
import time
import types
from datetime import UTC, datetime

from app.core.config import settings
from app.workers.tasks.maintenance import (
    _container_age_seconds,
    cleanup_orphan_sandboxes,
)


class _FakeContainer:
    def __init__(self, labels=None, created=None):
        self.labels = labels or {}
        self.attrs = {"Created": created} if created else {}
        self.id = "abc123def4567890"
        self.removed = False

    def remove(self, force=False):
        self.removed = True


def _install_fake_docker(monkeypatch, containers: list[_FakeContainer]) -> list[dict]:
    """注入 fake docker 模块；返回捕获到的 filters 列表（单元素）。"""
    captured: list[dict] = []

    class _FakeContainers:
        def list(self, filters=None):
            captured.append(filters or {})
            return containers

    class _FakeClient:
        def __init__(self):
            self.containers = _FakeContainers()

    fake = types.ModuleType("docker")
    fake.from_env = lambda timeout=30: _FakeClient()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "docker", fake)
    return captured


def test_disabled_is_noop(monkeypatch):
    """SANDBOX_ENABLED=False → no-op，不触碰 docker。"""
    monkeypatch.setattr(settings, "SANDBOX_ENABLED", False)
    assert cleanup_orphan_sandboxes() == {"removed": 0, "disabled": True}


def test_stale_removed_fresh_kept(monkeypatch):
    """超龄容器强删，新鲜容器保留。"""
    monkeypatch.setattr(settings, "SANDBOX_ENABLED", True)
    monkeypatch.setattr(settings, "SANDBOX_ORPHAN_MAX_AGE", 600)
    now = time.time()
    stale = _FakeContainer(
        labels={"agent-flow.sandbox": "true", "agent-flow.created-at": str(int(now - 3600))}
    )
    fresh = _FakeContainer(
        labels={"agent-flow.sandbox": "true", "agent-flow.created-at": str(int(now - 10))}
    )
    captured = _install_fake_docker(monkeypatch, [stale, fresh])

    result = cleanup_orphan_sandboxes()

    assert result == {"removed": 1, "scanned": 2}
    assert captured == [{"label": "agent-flow.sandbox=true"}]
    assert stale.removed is True
    assert fresh.removed is False


def test_unparseable_age_skipped(monkeypatch):
    """label 缺失且 Created 不可解析 → 保守跳过（不删年龄不明的容器）。"""
    monkeypatch.setattr(settings, "SANDBOX_ENABLED", True)
    monkeypatch.setattr(settings, "SANDBOX_ORPHAN_MAX_AGE", 600)
    unknown = _FakeContainer(labels={})
    _install_fake_docker(monkeypatch, [unknown])

    result = cleanup_orphan_sandboxes()

    assert result == {"removed": 0, "scanned": 1}
    assert unknown.removed is False


def test_created_attr_fallback(monkeypatch):
    """label 缺失时回退 daemon Created（RFC3339 纳秒）判定年龄。"""
    monkeypatch.setattr(settings, "SANDBOX_ENABLED", True)
    monkeypatch.setattr(settings, "SANDBOX_ORPHAN_MAX_AGE", 600)
    now = datetime.now(UTC)
    stale_str = (now.timestamp() - 7200)
    stale_dt = datetime.fromtimestamp(stale_str, tz=UTC)
    stale = _FakeContainer(created=stale_dt.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z")
    _install_fake_docker(monkeypatch, [stale])

    result = cleanup_orphan_sandboxes()

    assert result == {"removed": 1, "scanned": 1}
    assert stale.removed is True


# ── _container_age_seconds 单测 ──────────────────────────────────────────


def test_age_from_created_attr_recent():
    created = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"
    age = _container_age_seconds(_FakeContainer(created=created), time.time())
    assert age is not None and 0 <= age < 5


def test_age_handles_nanosecond_precision():
    """Docker 返回纳秒精度（9 位小数），裁剪到 6 位后可解析。"""
    age = _container_age_seconds(
        _FakeContainer(created="2020-01-01T00:00:00.123456789Z"), time.time()
    )
    assert age is not None and age > 1_000_000


def test_age_label_preferred_over_attr():
    """label 存在时优先于 attrs.Created。"""
    now = time.time()
    container = _FakeContainer(
        labels={"agent-flow.created-at": str(now - 100)},
        created="2020-01-01T00:00:00.000000Z",
    )
    age = _container_age_seconds(container, now)
    assert age is not None and 100 <= age < 105
