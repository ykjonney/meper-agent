"""License 完整性链测试（安全报告修复 1+2）。

覆盖：
- 3 个校验点（license_mw / celery_app / engine）各自的独立完整性自检：
  物理定位哈希匹配/不匹配、非强制放行、.py 源形态拒绝、占位符未替换
  fail-closed、``sys.modules`` origin 一致性、``__pycache__`` pyc 形态
- 矛盾检测（``_license_contract_ok``）：build_flags 被拦截翻转时校验点
  仍按内联真值强制——报告路径 3 的封堵验证
- 构建期占位符注入函数（build_compiled.inject_license_integrity_hash）
- middleware 集成：完整性破坏/矛盾 → 业务 403 LIC_E_INTEGRITY、license
  端点可达、docs 不在白名单
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest
from app.core.config import settings

SHA_PLACEHOLDER = "__LICENSE_SO_SHA256__"
ENFORCED_PLACEHOLDER = "__LICENSE_ENFORCED__"


def _fake_tree(
    tmp_path: Path, artifact_name: str = "license.cpython-312-x86_64-linux-gnu.so"
) -> tuple[Path, Path, str]:
    """tmp 下造 app/core/license 产物 + app/api/middleware/anchor.py 守卫锚点。

    返回 (锚点文件路径, 产物路径, 产物 sha256)。
    """
    core = tmp_path / "app" / "core"
    core.mkdir(parents=True)
    artifact = core / artifact_name
    artifact.write_bytes(b"\x7fELF fake license module bytes")
    anchor = tmp_path / "app" / "api" / "middleware" / "anchor.py"
    anchor.parent.mkdir(parents=True, exist_ok=True)
    anchor.write_text("", encoding="utf-8")
    return anchor, artifact, hashlib.sha256(artifact.read_bytes()).hexdigest()


@pytest.fixture
def lic_origin(monkeypatch):
    """sys.modules 中真实 license 模块的 __spec__.origin 可 patch 且可还原。"""
    from app.core import license as lic

    monkeypatch.setattr(settings, "LICENSE_ENFORCE_EXTRA", False)
    lic._cached_status = None
    yield lic
    lic._cached_status = None


def _patch_enforced(monkeypatch, mod, value: str) -> None:
    monkeypatch.setattr(mod, "_BUILT_LICENSE_ENFORCED", value)


# ── 三个校验点的独立实现（同一语义，逐一验证防漂移）─────────────────────

CHECKPOINTS = [
    pytest.param("app.api.middleware.license_mw", "_license_module_intact", id="license_mw"),
    pytest.param("app.workers.celery_app", "_license_module_sha_ok", id="celery_app"),
    pytest.param("app.engine.workflow.engine", "_license_module_intact", id="engine"),
]


@pytest.mark.parametrize(("module_name", "func_name"), CHECKPOINTS)
class TestCheckpointSemantics:
    """三个校验点的语义一致：强制下哈希即法律，非强制全放行。"""

    def test_passes_when_hash_matches(
        self, module_name, func_name, tmp_path, monkeypatch, lic_origin
    ):
        import importlib

        mod = importlib.import_module(module_name)
        anchor, artifact, digest = _fake_tree(tmp_path)
        monkeypatch.setattr(mod, "__file__", str(anchor))
        _patch_enforced(monkeypatch, mod, "True")
        monkeypatch.setattr(mod, "_BUILT_LICENSE_SHA256", digest)
        monkeypatch.setattr(lic_origin.__spec__, "origin", str(artifact))
        assert getattr(mod, func_name)() is True

    def test_fails_when_hash_mismatch(
        self, module_name, func_name, tmp_path, monkeypatch, lic_origin
    ):
        import importlib

        mod = importlib.import_module(module_name)
        anchor, artifact, _ = _fake_tree(tmp_path)
        monkeypatch.setattr(mod, "__file__", str(anchor))
        _patch_enforced(monkeypatch, mod, "True")
        monkeypatch.setattr(mod, "_BUILT_LICENSE_SHA256", "0" * 64)
        monkeypatch.setattr(lic_origin.__spec__, "origin", str(artifact))
        assert getattr(mod, func_name)() is False

    def test_fails_on_source_py_form(
        self, module_name, func_name, tmp_path, monkeypatch, lic_origin
    ):
        """RELEASE 必须是编译形态——替换回 .py 源文件 → fail closed。"""
        import importlib

        mod = importlib.import_module(module_name)
        anchor, _, digest = _fake_tree(tmp_path, "license.cpython-312.py")
        monkeypatch.setattr(mod, "__file__", str(anchor))
        _patch_enforced(monkeypatch, mod, "True")
        monkeypatch.setattr(mod, "_BUILT_LICENSE_SHA256", digest)
        monkeypatch.setattr(
            lic_origin.__spec__, "origin", str(tmp_path / "app" / "core" / "license.cpython-312.py")
        )
        assert getattr(mod, func_name)() is False

    def test_fails_when_placeholder_unreplaced(
        self, module_name, func_name, tmp_path, monkeypatch, lic_origin
    ):
        """占位符未替换（源码轨误配强制模式）→ fail closed。"""
        import importlib

        mod = importlib.import_module(module_name)
        anchor, artifact, _ = _fake_tree(tmp_path)
        monkeypatch.setattr(mod, "__file__", str(anchor))
        _patch_enforced(monkeypatch, mod, "True")
        monkeypatch.setattr(lic_origin.__spec__, "origin", str(artifact))
        assert getattr(mod, func_name)() is False

    def test_fails_on_missing_file(
        self, module_name, func_name, tmp_path, monkeypatch, lic_origin
    ):
        import importlib

        mod = importlib.import_module(module_name)
        anchor, artifact, digest = _fake_tree(tmp_path)
        artifact.unlink()
        monkeypatch.setattr(mod, "__file__", str(anchor))
        _patch_enforced(monkeypatch, mod, "True")
        monkeypatch.setattr(mod, "_BUILT_LICENSE_SHA256", digest)
        monkeypatch.setattr(lic_origin.__spec__, "origin", str(artifact))
        assert getattr(mod, func_name)() is False

    def test_passes_when_not_enforced(self, module_name, func_name, tmp_path, monkeypatch):
        """非强制（dev：占位符/False）→ 跳过校验（占位符保持原样也不拦）。"""
        import importlib

        mod = importlib.import_module(module_name)
        anchor, artifact, digest = _fake_tree(tmp_path)
        artifact.unlink()  # 文件都不存在也必须放行
        monkeypatch.setattr(mod, "__file__", str(anchor))
        for value in (ENFORCED_PLACEHOLDER, "False"):
            _patch_enforced(monkeypatch, mod, value)
            monkeypatch.setattr(mod, "_BUILT_LICENSE_SHA256", digest)
            assert getattr(mod, func_name)() is True

    def test_pyc_in_pycache_accepted(
        self, module_name, func_name, tmp_path, monkeypatch, lic_origin
    ):
        """.pyc 回退构建形态：产物在 core/__pycache__/ 下也要能被定位。"""
        import importlib

        mod = importlib.import_module(module_name)
        anchor = tmp_path / "app" / "api" / "middleware" / "anchor.py"
        anchor.parent.mkdir(parents=True, exist_ok=True)
        anchor.write_text("", encoding="utf-8")
        pycdir = tmp_path / "app" / "core" / "__pycache__"
        pycdir.mkdir(parents=True)
        artifact = pycdir / "license.cpython-312.pyc"
        artifact.write_bytes(b"fake pyc bytes")
        digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        monkeypatch.setattr(mod, "__file__", str(anchor))
        _patch_enforced(monkeypatch, mod, "True")
        monkeypatch.setattr(mod, "_BUILT_LICENSE_SHA256", digest)
        monkeypatch.setattr(lic_origin.__spec__, "origin", str(artifact))
        assert getattr(mod, func_name)() is True


class TestSysModulesConsistency:
    """内存模块与物理文件一致性：假模块 origin 缺失/乱指 → fail closed。"""

    def test_fails_when_origin_missing(self, tmp_path, monkeypatch, lic_origin):
        from app.api.middleware import license_mw

        anchor, artifact, digest = _fake_tree(tmp_path)
        monkeypatch.setattr(license_mw, "__file__", str(anchor))
        _patch_enforced(monkeypatch, license_mw, "True")
        monkeypatch.setattr(license_mw, "_BUILT_LICENSE_SHA256", digest)
        monkeypatch.delattr(lic_origin.__spec__, "origin", raising=False)
        assert license_mw._license_module_intact() is False

    def test_fails_when_origin_points_elsewhere(self, tmp_path, monkeypatch, lic_origin):
        """origin 指向另一个真实存在的 .so（假模块常见伪造）→ 不一致即拒绝。"""
        from app.api.middleware import license_mw

        anchor, artifact, digest = _fake_tree(tmp_path)
        other = tmp_path / "elsewhere.so"
        other.write_bytes(b"different bytes")
        monkeypatch.setattr(license_mw, "__file__", str(anchor))
        _patch_enforced(monkeypatch, license_mw, "True")
        monkeypatch.setattr(license_mw, "_BUILT_LICENSE_SHA256", digest)
        monkeypatch.setattr(lic_origin.__spec__, "origin", str(other))
        assert license_mw._license_module_intact() is False


# ── 矛盾检测：拦截 build_flags 翻转总开关无法关闭校验（报告路径 3）──────

CONTRACT_CHECKPOINTS = [
    pytest.param("app.workers.celery_app", id="celery_app"),
    pytest.param("app.engine.workflow.engine", id="engine"),
]


@pytest.mark.parametrize("module_name", CONTRACT_CHECKPOINTS)
class TestContractCheck:
    """_license_contract_ok：构建期强制真值 vs license 模块自报状态。"""

    def test_build_flags_flip_detected(self, module_name, monkeypatch, lic_origin):
        """build_flags 被拦截翻转（假 False）→ 矛盾 → 拒绝。"""
        import importlib

        from app.core import build_flags

        mod = importlib.import_module(module_name)
        monkeypatch.setattr(build_flags, "LICENSE_ENFORCED", False)
        _patch_enforced(monkeypatch, mod, "True")
        assert mod._license_contract_ok() is False

    def test_consistent_enforced_passes(self, module_name, monkeypatch, lic_origin):
        import importlib

        from app.core import build_flags

        mod = importlib.import_module(module_name)
        monkeypatch.setattr(build_flags, "LICENSE_ENFORCED", True)
        _patch_enforced(monkeypatch, mod, "True")
        assert mod._license_contract_ok() is True

    def test_not_enforced_build_skips(self, module_name, monkeypatch, lic_origin):
        """非强制构建（dev）→ 恒 True，不依赖 license 模块。"""
        import importlib

        mod = importlib.import_module(module_name)
        _patch_enforced(monkeypatch, mod, ENFORCED_PLACEHOLDER)
        assert mod._license_contract_ok() is True


# ── middleware 集成 ─────────────────────────────────────────────────────

@pytest.fixture
def enforced_env(monkeypatch, tmp_path):
    """与 test_license.lic_env 同款强制环境（最小版：只需 enforced）。"""
    monkeypatch.setattr(settings, "LICENSE_ENFORCE_EXTRA", True)
    monkeypatch.setattr(settings, "LICENSE_PATH", str(tmp_path / "jasper.identity"))
    from app.core import license as lic

    lic._cached_status = None
    yield
    lic._cached_status = None


def test_middleware_integrity_breach_blocks_business(client, monkeypatch, enforced_env):
    """license 模块被替换（自检 False）→ 业务 API 403 且 code=LIC_E_INTEGRITY。"""
    from app.api.middleware import license_mw

    monkeypatch.setattr(license_mw, "_license_module_intact", lambda: False)
    resp = client.get("/api/v1/agents/")
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "LIC_E_INTEGRITY"


def test_middleware_integrity_breach_keeps_license_endpoints(client, monkeypatch, enforced_env):
    """激活向导必须仍可达（管理员换回正版包的通道）。"""
    from app.api.middleware import license_mw

    monkeypatch.setattr(license_mw, "_license_module_intact", lambda: False)
    assert client.get("/api/v1/system/license/status").status_code == 200
    assert client.get("/api/v1/health").status_code == 200


def test_middleware_contract_violation_blocks_business(client, monkeypatch):
    """报告路径 3 复现：build_flags 翻转（license 谎报不强制）+ 强制构建
    → 矛盾检测 403 LIC_E_INTEGRITY，license/health 端点仍可达。"""
    from app.api.middleware import license_mw
    from app.core import build_flags
    from app.core import license as lic

    monkeypatch.setattr(build_flags, "LICENSE_ENFORCED", False)
    monkeypatch.setattr(settings, "LICENSE_ENFORCE_EXTRA", False)
    _patch_enforced(monkeypatch, license_mw, "True")
    lic._cached_status = None
    try:
        resp = client.get("/api/v1/agents/")
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "LIC_E_INTEGRITY"
        assert client.get("/api/v1/system/license/status").status_code == 200
        assert client.get("/api/v1/health").status_code == 200
    finally:
        lic._cached_status = None


def test_middleware_docs_not_whitelisted(client, enforced_env):
    """docs/openapi 不在白名单：未激活降级态也不放行（fail closed）。"""
    resp = client.get("/api/v1/openapi.json")
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "LIC_E_NOT_ACTIVATED"


# ── 构建期占位符注入 ────────────────────────────────────────────────────

def _load_build_compiled():
    """scripts/ 不在包路径，按文件路径加载。"""
    import importlib.util

    path = Path(__file__).resolve().parents[2] / "scripts" / "build_compiled.py"
    spec = importlib.util.spec_from_file_location("build_compiled", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestInjectLicenseIntegrityHash:
    def _staging(self, tmp_path: Path) -> Path:
        staging = tmp_path / "app"
        for rel in (
            "api/middleware/license_mw.py",
            "workers/celery_app.py",
            "engine/workflow/engine.py",
        ):
            f = staging / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(
                f'_BUILT_LICENSE_SHA256 = "{SHA_PLACEHOLDER}"\n'
                f'_BUILT_LICENSE_ENFORCED = "{ENFORCED_PLACEHOLDER}"\n',
                encoding="utf-8",
            )
        return staging

    def test_replaces_all_sentinels(self, tmp_path):
        mod = _load_build_compiled()
        staging = self._staging(tmp_path)
        count = mod.inject_license_integrity_hash(staging, "b" * 64, enforce=True)
        assert count == 3
        for rel in mod.LICENSE_INTEGRITY_SENTINELS:
            text = (staging / rel).read_text(encoding="utf-8")
            assert "b" * 64 in text
            assert '_BUILT_LICENSE_ENFORCED = "True"' in text
            assert SHA_PLACEHOLDER not in text
            assert ENFORCED_PLACEHOLDER not in text

    def test_dev_build_injects_false(self, tmp_path):
        mod = _load_build_compiled()
        staging = self._staging(tmp_path)
        mod.inject_license_integrity_hash(staging, "b" * 64, enforce=False)
        text = (staging / mod.LICENSE_INTEGRITY_SENTINELS[0]).read_text(encoding="utf-8")
        assert '_BUILT_LICENSE_ENFORCED = "False"' in text

    def test_missing_hash_placeholder_aborts(self, tmp_path):
        """源文件漏写占位符 → 构建必须失败（静默跳过=校验点失效）。"""
        mod = _load_build_compiled()
        staging = self._staging(tmp_path)
        (staging / "engine/workflow/engine.py").write_text("x = 1\n", encoding="utf-8")
        with pytest.raises(SystemExit, match="占位符"):
            mod.inject_license_integrity_hash(staging, "c" * 64, enforce=True)

    def test_missing_enforced_placeholder_aborts(self, tmp_path):
        mod = _load_build_compiled()
        staging = self._staging(tmp_path)
        (staging / "api/middleware/license_mw.py").write_text(
            f'_BUILT_LICENSE_SHA256 = "{SHA_PLACEHOLDER}"\n', encoding="utf-8"
        )
        with pytest.raises(SystemExit, match="占位符"):
            mod.inject_license_integrity_hash(staging, "c" * 64, enforce=True)


def test_all_source_sentinels_carry_placeholders():
    """仓库源码轨：三个校验点必须都带双占位符（防新增校验点漏写）。"""
    repo_app = Path(__file__).resolve().parents[2] / "app"
    for rel in (
        "api/middleware/license_mw.py",
        "workers/celery_app.py",
        "engine/workflow/engine.py",
    ):
        text = (repo_app / rel).read_text(encoding="utf-8")
        assert SHA_PLACEHOLDER in text, rel
        assert ENFORCED_PLACEHOLDER in text, rel


def test_sys_modules_license_importable():
    """校验点依赖 sys.modules 中已加载的 app.core.license——导入即可满足。"""
    import importlib

    assert "app.core.license" in sys.modules or importlib.import_module("app.core.license")
