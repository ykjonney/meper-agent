"""Tests for maintenance.cleanup_orphan_sandboxes（孤儿沙盒容器清扫）.

Fake docker module injected via sys.modules（CI 无 Docker daemon）；
label 约定与 harness DockerSandbox._execute_docker / SANDBOX_LAST_USED_FILE 一致。
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


class _FakeReusableContainer(_FakeContainer):
    """复用模式容器：支持 exec_run 读 last-used（可编排结果/异常）。"""

    def __init__(self, labels=None, created=None, *, last_used=None, exec_exc=None):
        super().__init__(labels=labels, created=created)
        self._last_used = last_used
        self._exec_exc = exec_exc

    def exec_run(self, cmd, user=None):
        if self._exec_exc is not None:
            raise self._exec_exc
        if self._last_used is None:
            return 1, None  # cat 无文件
        return 0, (str(self._last_used).encode(), None)


def _install_fake_docker(monkeypatch, containers: list) -> list[dict]:
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


def _enable_oneshot(monkeypatch):
    """一次性容器分支的公共 stub（复用关闭）。"""
    monkeypatch.setattr(settings, "SANDBOX_ENABLED", True)
    monkeypatch.setattr(settings, "SANDBOX_REUSE_CONTAINER", False)
    monkeypatch.setattr(settings, "SANDBOX_ORPHAN_MAX_AGE", 600)


def test_disabled_is_noop(monkeypatch):
    """SANDBOX_ENABLED=False → no-op，不触碰 docker。"""
    monkeypatch.setattr(settings, "SANDBOX_ENABLED", False)
    assert cleanup_orphan_sandboxes() == {"removed": 0, "disabled": True}


def test_oneshot_stale_removed_fresh_kept(monkeypatch):
    """超龄容器强删，新鲜容器保留。"""
    _enable_oneshot(monkeypatch)
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


def test_oneshot_unparseable_age_skipped(monkeypatch):
    """label 缺失且 Created 不可解析 → 保守跳过（不删年龄不明的容器）。"""
    _enable_oneshot(monkeypatch)
    unknown = _FakeContainer(labels={})
    _install_fake_docker(monkeypatch, [unknown])

    result = cleanup_orphan_sandboxes()

    assert result == {"removed": 0, "scanned": 1}
    assert unknown.removed is False


def test_oneshot_created_attr_fallback(monkeypatch):
    """label 缺失时回退 daemon Created（RFC3339 纳秒）判定年龄。"""
    _enable_oneshot(monkeypatch)
    now = datetime.now(UTC)
    stale_str = (now.timestamp() - 7200)
    stale_dt = datetime.fromtimestamp(stale_str, tz=UTC)
    stale = _FakeContainer(created=stale_dt.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z")
    _install_fake_docker(monkeypatch, [stale])

    result = cleanup_orphan_sandboxes()

    assert result == {"removed": 1, "scanned": 1}
    assert stale.removed is True


# ── 复用模式分支（闲置回收 + 寿命兜底）──────────────────────────────────


def _enable_reuse(monkeypatch):
    monkeypatch.setattr(settings, "SANDBOX_ENABLED", True)
    monkeypatch.setattr(settings, "SANDBOX_REUSE_CONTAINER", True)
    monkeypatch.setattr(settings, "SANDBOX_ORPHAN_MAX_AGE", 600)
    monkeypatch.setattr(settings, "SANDBOX_CONTAINER_IDLE_TIMEOUT", 300)
    monkeypatch.setattr(settings, "SANDBOX_CONTAINER_MAX_LIFETIME", 86400)


def _reuse_labels(now: float, age: float) -> dict:
    return {"agent-flow.sandbox": "true", "agent-flow.created-at": str(int(now - age))}


def test_reuse_idle_stale_removed_fresh_kept(monkeypatch):
    """闲置超时（last-used 超阈值）删除，活跃容器保留。"""
    _enable_reuse(monkeypatch)
    now = time.time()
    fresh = _FakeReusableContainer(
        labels=_reuse_labels(now, 60), last_used=str(now - 10)
    )
    stale = _FakeReusableContainer(
        labels=_reuse_labels(now, 3600), last_used=str(now - 3600)
    )
    _install_fake_docker(monkeypatch, [fresh, stale])

    result = cleanup_orphan_sandboxes()

    assert result == {"removed": 1, "scanned": 2}
    assert fresh.removed is False
    assert stale.removed is True


def test_reuse_exec_fail_young_kept_old_removed(monkeypatch):
    """last-used 不可读：年轻容器保守跳过；超过孤儿阈值才删。"""
    _enable_reuse(monkeypatch)
    now = time.time()
    young_broken = _FakeReusableContainer(
        labels=_reuse_labels(now, 30), exec_exc=RuntimeError("container hung")
    )
    old_broken = _FakeReusableContainer(
        labels=_reuse_labels(now, 7200), exec_exc=RuntimeError("container hung")
    )
    _install_fake_docker(monkeypatch, [young_broken, old_broken])

    result = cleanup_orphan_sandboxes()

    assert result == {"removed": 1, "scanned": 2}
    assert young_broken.removed is False
    assert old_broken.removed is True


def test_reuse_lifetime_backstop(monkeypatch):
    """寿命兜底：created-at 超 MAX_LIFETIME 时无论 last-used 多新都删。"""
    _enable_reuse(monkeypatch)
    now = time.time()
    ancient_but_active = _FakeReusableContainer(
        labels=_reuse_labels(now, 90000), last_used=str(now - 5)
    )
    _install_fake_docker(monkeypatch, [ancient_but_active])

    result = cleanup_orphan_sandboxes()

    assert result == {"removed": 1, "scanned": 1}
    assert ancient_but_active.removed is True


def test_reuse_never_executed_young_kept(monkeypatch):
    """刚创建还没跑过命令（cat 无文件）→ 保守保留。"""
    _enable_reuse(monkeypatch)
    now = time.time()
    newborn = _FakeReusableContainer(labels=_reuse_labels(now, 5), last_used=None)
    _install_fake_docker(monkeypatch, [newborn])

    result = cleanup_orphan_sandboxes()

    assert result == {"removed": 0, "scanned": 1}
    assert newborn.removed is False


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
