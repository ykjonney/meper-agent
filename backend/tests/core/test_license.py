"""License 模块测试（IdentityLoader 兼容版：RSA-SHA256 签名 + AES-ECB 加密 + XML）。

测试用 RSA 密钥对现场生成；通过 mock 内嵌公钥/密钥实现隔离。
API 集成走 conftest 的 client fixture。
"""

import base64
import os
import sys
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
from loguru import logger

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


# ── MAC 指纹信源（安全报告修复 4：实测优先 + 注入交叉核对）───────────────
@pytest.fixture
def mac_env(monkeypatch):
    """隔离 MAC 信源：清缓存 + mock 实测值。"""
    monkeypatch.setattr(lic, "_mac_cache", None)
    monkeypatch.setattr(lic, "_measure_mac", lambda: "AA-BB-CC-DD-EE-F0")
    yield
    lic._mac_cache = None


def test_mac_env_matches_measured(mac_env, monkeypatch):
    """注入值与实测一致 → 静默采信。"""
    monkeypatch.setenv("AGENT_FLOW_MAC", "AA-BB-CC-DD-EE-F0")
    assert lic.get_machine_fingerprint() == "AA-BB-CC-DD-EE-F0"


def test_mac_env_mismatch_warns_and_trusted_by_default(mac_env, monkeypatch):
    """docker 场景：注入值 ≠ 实测（veth 随机 MAC）→ 告警（审计信号）后
    默认仍采信注入值（LICENSE_TRUST_ENV_MAC 默认 true）。"""
    monkeypatch.setenv("AGENT_FLOW_MAC", "11-22-33-44-55-66")
    records: list[object] = []
    handler_id = logger.add(records.append, level="WARNING")
    try:
        assert lic.get_machine_fingerprint() == "11-22-33-44-55-66"
    finally:
        logger.remove(handler_id)
    assert any("license_mac_env_mismatch" in str(m) for m in records)


def test_mac_env_mismatch_strict_mode_uses_measured(mac_env, monkeypatch):
    """LICENSE_TRUST_ENV_MAC=false：严格物理绑机——异机克隆（改注入值）
    直接拿不到授权 MAC，激活失败。"""
    monkeypatch.setattr(settings, "LICENSE_TRUST_ENV_MAC", False)
    monkeypatch.setenv("AGENT_FLOW_MAC", "11-22-33-44-55-66")
    assert lic.get_machine_fingerprint() == "AA-BB-CC-DD-EE-F0"


def test_mac_no_env_uses_measured(mac_env, monkeypatch):
    """手动部署：无注入值 → 直接用实测网卡 MAC。"""
    monkeypatch.delenv("AGENT_FLOW_MAC", raising=False)
    assert lic.get_machine_fingerprint() == "AA-BB-CC-DD-EE-F0"


def test_mac_measure_failure_fallback(monkeypatch):
    """实测全失败且无注入 → 维持 00 回退（与 Java 端一致）。"""
    monkeypatch.setattr(lic, "_mac_cache", None)
    monkeypatch.setattr(lic, "_measure_mac", lambda: "")
    monkeypatch.delenv("AGENT_FLOW_MAC", raising=False)
    try:
        assert lic.get_machine_fingerprint() == "00-00-00-00-00-00"
    finally:
        lic._mac_cache = None


# ── 物理网卡选卡算法（device 链接 + carrier + 硬件槽位排序）──────────────
def _fake_sysfs(tmp_path: Path, ifaces: dict) -> Path:
    """造假 sysfs 树：ifaces = {名: {"dev": bool, "carrier": str|None, "addr": str}}。

    dev=True 时建 device 符号链接指向独立硬件目录（tmp_path/hw/<名>，
    可用带 PCI 槽位形状的目录名控制排序）。"""
    sys_net = tmp_path / "class" / "net"
    sys_net.mkdir(parents=True)
    for name, spec in ifaces.items():
        d = sys_net / name
        d.mkdir()
        (d / "address").write_text(spec["addr"])
        if spec.get("carrier") is not None:
            (d / "carrier").write_text(spec["carrier"])
        if spec.get("dev"):
            hw = tmp_path / "hw" / spec.get("slot", name)
            hw.mkdir(parents=True, exist_ok=True)
            (d / "device").symlink_to(hw, target_is_directory=True)
    return sys_net


def _pick(tmp_path: Path, ifaces: dict) -> str | None:
    iface = lic._select_linux_iface(_fake_sysfs(tmp_path, ifaces))
    return iface.name if iface else None


def test_select_physical_over_docker0(tmp_path):
    """docker0（虚拟，无 device 链接）不得抢在物理网卡前面——本次修复的根因。"""
    got = _pick(tmp_path, {
        "docker0": {"addr": "02:42:aa:bb:cc:dd"},
        "ens192": {"dev": True, "carrier": "1", "addr": "60:3e:5f:4d:13:74"},
    })
    assert got == "ens192"


def test_select_carrier_up_preferred(tmp_path):
    """同为物理：链路 up 的优先于没插线的备用口。"""
    got = _pick(tmp_path, {
        "ens192": {"dev": True, "carrier": "0", "addr": "aa:00:00:00:00:01"},
        "ens224": {"dev": True, "carrier": "1", "addr": "aa:00:00:00:00:02"},
    })
    assert got == "ens224"


def test_select_pci_slot_order_beats_name_order(tmp_path):
    """排序按硬件槽位路径而非接口名——udev 改名/命名规则差异不漂移。"""
    got = _pick(tmp_path, {
        # eth0 名字靠前，但硬件槽位在 08；eth1 槽位 03 → 应选 eth1
        "eth0": {"dev": True, "carrier": "1", "slot": "0000:00:08.0", "addr": "aa:00:00:00:00:01"},
        "eth1": {"dev": True, "carrier": "1", "slot": "0000:00:03.0", "addr": "aa:00:00:00:00:02"},
    })
    assert got == "eth1"


def test_select_bond_slave_over_bond_master(tmp_path):
    """bond 绑定：bond0 无 device 链接，slave 有 → 选 slave（active-backup
    下 slave MAC=bond MAC，稳定）。"""
    got = _pick(tmp_path, {
        "bond0": {"addr": "aa:00:00:00:00:09"},
        "ens192": {"dev": True, "carrier": "1", "addr": "aa:00:00:00:00:01"},
    })
    assert got == "ens192"


def test_select_carrier_unknown_ranks_above_down(tmp_path):
    """carrier 读取失败（管理态 down 等）排在 down 之前。"""
    got = _pick(tmp_path, {
        "ens192": {"dev": True, "addr": "aa:00:00:00:00:01"},              # 无 carrier 文件
        "ens224": {"dev": True, "carrier": "0", "addr": "aa:00:00:00:00:02"},
    })
    assert got == "ens192"


def test_select_all_virtual_falls_back(tmp_path):
    """全部无硬件背书（无直通的容器内）→ 兜底第一个非 lo（旧行为）。"""
    got = _pick(tmp_path, {
        "veth1a2b": {"addr": "aa:00:00:00:00:03"},
        "docker0": {"addr": "02:42:aa:bb:cc:dd"},
    })
    assert got == "docker0"  # 字母序第一个非 lo


def test_select_skips_nondirectory_entries(tmp_path):
    """/sys/class/net 下混有普通文件（bonding_masters 控制文件，字母序
    靠前）——不得当成接口（真实容器/VM 内会踩中）。"""
    sys_net = _fake_sysfs(tmp_path, {
        "docker0": {"addr": "02:42:aa:bb:cc:dd"},
        "eth0": {"dev": True, "carrier": "1", "addr": "60:3e:5f:4d:13:74"},
    })
    (sys_net / "bonding_masters").write_text("")  # 普通文件，非目录
    iface = lic._select_linux_iface(sys_net)
    assert iface is not None and iface.name == "eth0"


def test_select_empty_returns_none(tmp_path):
    assert _pick(tmp_path, {}) is None


def test_measure_mac_uses_sys_net_path(tmp_path, monkeypatch):
    """_measure_mac 读 LICENSE_SYS_NET_PATH（Docker 挂载点定制的能力来源）。"""
    sys_net = _fake_sysfs(tmp_path, {
        "docker0": {"addr": "02:42:aa:bb:cc:dd"},
        "ens192": {"dev": True, "carrier": "1", "addr": "60:3e:5f:4d:13:74"},
    })
    monkeypatch.setattr(settings, "LICENSE_SYS_NET_PATH", str(sys_net))
    monkeypatch.setattr(sys, "platform", "linux")  # 让 darwin 测试机走 linux 分支
    assert lic._measure_mac() == "60-3E-5F-4D-13-74"


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
