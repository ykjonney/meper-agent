"""License 模块测试（IdentityLoader 兼容版：RSA-SHA256 签名 + AES-ECB 加密 + XML）。

测试用 RSA 密钥对现场生成；通过 mock 内嵌公钥/密钥实现隔离。
API 集成走 conftest 的 client fixture。
"""

import base64
import os
import xml.etree.ElementTree as ET
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from app.core import license as lic
from app.core.config import settings
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from fastapi.testclient import TestClient

TEST_MAC = "08-BF-B8-73-4C-BB"


# ── 测试工具：生成 jasper.identity 格式的 license ────────────────────────
def _aes_ecb_encrypt(plaintext: bytes, key: bytes) -> bytes:
    """AES-128-ECB 加密 + PKCS7 padding（与 Java AESCoder 一致）。"""
    pad_len = 16 - len(plaintext) % 16
    padded = plaintext + bytes([pad_len]) * pad_len
    cipher = Cipher(algorithms.AES(key), modes.ECB())
    enc = cipher.encryptor()
    return enc.update(padded) + enc.finalize()


def _rsa_sha256_sign(priv: rsa.RSAPrivateKey, data: bytes) -> bytes:
    return priv.sign(data, asym_padding.PKCS1v15(), hashes.SHA256())


def _make_identity_xml(
    *,
    company: str = "测试客户",
    mac: str | None = TEST_MAC,
    expires_in_days: float = 365.0,
    auth_type: str = "mac",
    user_count: int = 100,
) -> bytes:
    now = datetime.now(UTC)
    start = now.isoformat()
    end = (now + timedelta(days=expires_in_days)).isoformat() if expires_in_days > 0 else (now - timedelta(days=1)).isoformat()

    lic_el = ET.Element("licence")
    ET.SubElement(lic_el, "companyName").text = company
    ET.SubElement(lic_el, "userCount").text = str(user_count)
    ET.SubElement(lic_el, "effectiveStartDate").text = start
    ET.SubElement(lic_el, "effectiveEndDate").text = end
    ET.SubElement(lic_el, "authType").text = auth_type
    ET.SubElement(lic_el, "usage").text = "prod"
    if mac:
        macs = ET.SubElement(lic_el, "macAddresses")
        ET.SubElement(macs, "macAddress").text = mac

    root = ET.Element("identity")
    ET.SubElement(root, "licenceNo").text = f"LIC-{now.timestamp():.0f}"
    root.append(lic_el)
    return ET.tostring(root, encoding="unicode").encode()


def _make_license_file(
    priv: rsa.RSAPrivateKey,
    aes_key: bytes,
    xml: bytes,
) -> bytes:
    """生成 jasper.identity 格式：Base64(密文) + 0x0D + Base64(签名)。"""
    ciphertext = _aes_ecb_encrypt(xml, aes_key)
    signature = _rsa_sha256_sign(priv, ciphertext)
    return base64.b64encode(ciphertext) + b"\x0d" + base64.b64encode(signature)


@pytest.fixture
def lic_env(tmp_path, monkeypatch):
    """强制模式 + 测试密钥 + tmp 路径 + mock 本机 MAC。"""
    # 生成测试 RSA 密钥对
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pub_pem = priv.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    aes_key = os.urandom(16)

    monkeypatch.setattr(settings, "LICENSE_ENFORCE_EXTRA", True)
    monkeypatch.setattr(settings, "LICENSE_PATH", str(tmp_path / "jasper.identity"))
    monkeypatch.setattr(lic, "_RSA_PUB_PEM", pub_pem)
    monkeypatch.setattr(lic, "_AES_KEY_B64", base64.b64encode(aes_key).decode())
    monkeypatch.setattr(lic, "_mac_cache", TEST_MAC)
    lic._cached_status = None

    yield {"priv": priv, "aes_key": aes_key}
    lic._cached_status = None


def _install(lic_env, **kwargs) -> lic.LicenseStatus:
    xml = _make_identity_xml(**kwargs)
    content = _make_license_file(lic_env["priv"], lic_env["aes_key"], xml)
    lic._cached_status = None
    return lic.install_license(content.decode())


# ── 单元：核心校验矩阵 ────────────────────────────────────────────────
def test_dev_mode_not_enforced(monkeypatch):
    monkeypatch.setattr(settings, "LICENSE_ENFORCE_EXTRA", False)
    monkeypatch.setattr(lic, "_mac_cache", TEST_MAC)
    lic._cached_status = None
    status = lic.evaluate_license(force=True)
    assert status.ok and not status.enforced
    lic._cached_status = None


def test_not_activated(lic_env):
    status = lic.evaluate_license(force=True)
    assert not status.ok
    assert status.code == lic.LIC_E_NOT_ACTIVATED


def test_valid_license(lic_env):
    status = _install(lic_env)
    assert status.ok, status.code
    assert status.payload.company_name == "测试客户"
    assert status.payload.mac_addresses == [TEST_MAC]
    assert status.days_left is not None and 364 <= status.days_left <= 366


def test_lf_separator_paste(lic_env):
    """网页粘贴场景：textarea 按 HTML 规范把 \\r 规范化为 \\n，分隔符 0x0D→0x0A 也必须能解析。"""
    content = _make_license_file(lic_env["priv"], lic_env["aes_key"], _make_identity_xml())
    lic._cached_status = None
    # \r → \n（粘贴规范化的结果）
    status = lic.install_license(content.replace(b"\x0d", b"\x0a").decode())
    assert status.ok, status.code
    # CRLF / 尾部多余换行（复制时带上行尾）也应容忍
    lic._cached_status = None
    status = lic.install_license((content.replace(b"\x0d", b"\x0d\x0a") + b"\x0a").decode())
    assert status.ok, status.code


def test_expired(lic_env):
    status = _install(lic_env, expires_in_days=-1)
    assert status.code == lic.LIC_E_EXPIRED


def test_mac_mismatch(lic_env):
    status = _install(lic_env, mac="AA-BB-CC-DD-EE-FF")
    assert status.code == lic.LIC_E_FINGERPRINT
    # 失败不落盘
    assert not lic.license_path().exists()


def test_bad_signature(lic_env):
    """用另一把 RSA 密钥签 → 验签失败。"""
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    xml = _make_identity_xml()
    content = _make_license_file(other, lic_env["aes_key"], xml)
    lic._cached_status = None
    status = lic.install_license(content.decode())
    assert status.code == lic.LIC_E_SIGNATURE


def test_garbage_file(lic_env):
    lic._cached_status = None
    status = lic.install_license("not-a-license")
    assert status.code == lic.LIC_E_READ


def test_auth_type_online_skips_mac(lic_env):
    """authType != 'mac' → 跳过 MAC 检查（在线模式由服务端管）。"""
    status = _install(lic_env, mac="AA-BB-CC-DD-EE-FF", auth_type="online")
    assert status.ok


# ── API 集成 ──────────────────────────────────────────────────────────
def test_api_unactivated_business_403_wizard_ok(lic_env, client: TestClient):
    resp = client.get("/api/v1/agents")
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == lic.LIC_E_NOT_ACTIVATED
    assert client.get("/api/v1/system/license/status").status_code == 200


def test_api_install_hot_recovery(lic_env, client: TestClient):
    assert client.get("/api/v1/agents").status_code == 403
    xml = _make_identity_xml()
    content = _make_license_file(lic_env["priv"], lic_env["aes_key"], xml)
    resp = client.post(
        "/api/v1/system/license/install",
        content=content,
        headers={"Content-Type": "text/plain"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["activated"] is True
    assert client.get("/api/v1/agents").status_code == 401  # 到达鉴权层


def test_api_expired(lic_env, client: TestClient):
    xml = _make_identity_xml(expires_in_days=-1)
    content = _make_license_file(lic_env["priv"], lic_env["aes_key"], xml)
    lic.license_path().write_bytes(content)
    lic._cached_status = None
    status = lic.evaluate_license(force=True)
    assert status.code == lic.LIC_E_EXPIRED
    resp = client.get("/api/v1/agents")
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == lic.LIC_E_EXPIRED


def test_api_expiring_soon_header(lic_env, client: TestClient):
    _install(lic_env, expires_in_days=3)
    resp = client.get("/api/v1/agents")
    assert "X-License-Expiring" in resp.headers


def test_api_dev_mode_allows_business(monkeypatch, client: TestClient):
    monkeypatch.setattr(settings, "LICENSE_ENFORCE_EXTRA", False)
    lic._cached_status = None
    try:
        resp = client.get("/api/v1/agents")
        assert resp.status_code == 401
    finally:
        lic._cached_status = None


# ── 真实文件测试（docs/jasper.identity）────────────────────────────────
def test_real_identity_file():
    """用公司签发的真实 jasper.identity 验证（MAC 会不匹配，但验签/解密/解析应通过）。"""
    real = Path(__file__).parent.parent.parent / "docs" / "jasper.identity"
    if not real.exists():
        pytest.skip("docs/jasper.identity 不存在")

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(settings, "LICENSE_ENFORCE_EXTRA", True)
    monkeypatch.setattr(settings, "APP_ENV", "development")
    monkeypatch.setattr(lic, "_mac_cache", "08-BF-B8-73-4C-BB")  # 用 license 里的 MAC
    monkeypatch.setattr(settings, "LICENSE_PATH", str(real))
    lic._cached_status = None

    try:
        status = lic.evaluate_license(force=True)
        # 验签+解密+XML 解析应该全通过；MAC 匹配 → ok
        assert status.ok, f"code={status.code}"
        assert "盖鼎" in status.payload.company_name
    finally:
        lic._cached_status = None
        monkeypatch.undo()
