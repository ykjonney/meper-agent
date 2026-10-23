"""License verification (company IdentityLoader compatible).

验证链路（与 Java 端 IdentityLoader 逻辑一致）：

1. 读取 jasper.identity 文件
2. 按最后一个 0x0D 分割 → Base64 解码 → 密文 + 签名
3. RSA-SHA256 验签（公钥内嵌，从 JKS 证书预提取）
4. AES-128-ECB 解密（共享密钥内嵌）
5. XML 解析 → Identity（companyName / macAddresses / effectiveEndDate / authType）
6. authType="mac" 时比对 MAC 地址
7. 检查 effectiveEndDate

文件格式：Base64(AES密文) + 0x0D + Base64(RSA-SHA256签名)
明文格式：XML <identity><licenceNo/><licence>...</licence></identity>
"""

from __future__ import annotations

import base64
import os
import threading
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from loguru import logger

from app.core import build_flags
from app.core.config import settings

# ── 错误码 ─────────────────────────────────────────────────────────────
LIC_OK = "LIC_OK"
LIC_E_NOT_ACTIVATED = "LIC_E_NOT_ACTIVATED"
LIC_E_READ = "LIC_E_READ"
LIC_E_SIGNATURE = "LIC_E_SIGNATURE"
LIC_E_FINGERPRINT = "LIC_E_FINGERPRINT"
LIC_E_EXPIRED = "LIC_E_EXPIRED"

PRODUCT = "agent-flow"

# ── 内嵌常量（编译进 .so）────────────────────────────────────────────────
# AES-128-ECB 密钥（与 Java 端 AESCoder 共享）
_AES_KEY_B64 = "IVTjIT0QWU7JKWY3NGpiQw=="

# RSA-2048 公钥（PEM，从 JKS 证书 moneytree 提取）
_RSA_PUB_PEM = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAxOt/taeoal3wOIE7B4Si
JoMcgb4YUKQjPs0uVxr6eMSTTaWGeYc+824nWnDubJIpmNNq/5PT++9rC3erXZAx
2UVaiz/1Rt2LK3dxkOvTTRZj5QcMdtCGOBeMxswZ4SlewgFDN3yIpwlRgzi8Tv7w
2lvOIi2AIv9j0XcjDBZHhfAmOmaWtXhHst+DlOvMdV2GlB2umgEsM7LAkzEDrPdG
Es3RH5Pg8HWtcUxq5hZxXZEFGYdrHpqavkq0WH16F+jU25Sy5c4e/3DBHJKIk1Sw
/ENobWJHtHbpDhirjoVqwXa1mnFHyHJ5huGooh6hidl1zQxpRkFl6nVp0KpZCa7D
nQIDAQAB
-----END PUBLIC KEY-----"""


class LicenseError(Exception):
    """分散校验点使用的异常。"""
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass
class LicensePayload:
    """从 jasper.identity 解析出的授权信息。"""
    licence_no: str = ""
    company_name: str = ""
    application_name: str = ""
    user_count: int = 0
    auth_type: str = ""
    usage: str = ""
    effective_start: str = ""
    effective_end: str = ""
    mac_addresses: list[str] = field(default_factory=list)

    # 兼容现有 LicenseStatus 接口
    @property
    def licensee(self) -> str:
        return self.company_name

    @property
    def license_id(self) -> str:
        return self.licence_no

    @property
    def edition(self) -> str:
        return self.usage or "standard"

    @property
    def expires_at(self) -> datetime | None:
        if not self.effective_end:
            return None
        try:
            return datetime.fromisoformat(self.effective_end)
        except (ValueError, TypeError):
            return None

    @property
    def fingerprint(self) -> str:
        return ",".join(self.mac_addresses)


@dataclass
class LicenseStatus:
    """一次完整校验的结果。"""
    ok: bool
    code: str
    enforced: bool
    payload: LicensePayload | None = None
    fingerprint: str = ""
    evaluated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def expires_at(self) -> datetime | None:
        return self.payload.expires_at if self.payload else None

    @property
    def days_left(self) -> int | None:
        if self.payload is None or self.payload.expires_at is None:
            return None
        delta = self.payload.expires_at - datetime.now(UTC)
        return delta.days

    @property
    def expiring_soon(self) -> bool:
        return self.days_left is not None and 0 <= self.days_left <= 7


def _now() -> datetime:
    return datetime.now(UTC)


def is_enforced() -> bool:
    return build_flags.LICENSE_ENFORCED or settings.LICENSE_ENFORCE_EXTRA


# ── MAC 地址（绑机标识）────────────────────────────────────────────────
_mac_cache: str | None = None
_mac_lock = threading.Lock()


def get_machine_fingerprint() -> str:
    """本机 MAC 地址（发给签发端的标识）。"""
    global _mac_cache
    with _mac_lock:
        if _mac_cache is None:
            _mac_cache = _read_primary_mac()
        return _mac_cache


def _read_primary_mac() -> str:
    """读取第一个非 lo 接口的 MAC 地址，格式化为 XX-XX-XX-XX-XX-XX（与 Java 端一致）。

    AGENT_FLOW_MAC 环境变量优先（Docker 部署：容器内是 veth 随机 MAC，
    由启动器在宿主算好真实网卡 MAC 注入，保证绑机校验与手动部署一致）。
    """
    import os
    import subprocess
    import sys

    env_mac = os.environ.get("AGENT_FLOW_MAC", "").strip().upper().replace(":", "-")
    if env_mac:
        return env_mac
    try:
        if sys.platform.startswith("linux"):
            out = subprocess.run(
                ["cat", "/sys/class/net/$(ls /sys/class/net | grep -v lo | head -1)/address"],
                capture_output=True, text=True, timeout=5, shell=True,
            ).stdout.strip()
            # 格式化 AA:BB:CC → AA-BB-CC（与 Java 端格式一致）
            return out.upper().replace(":", "-")
        elif sys.platform == "darwin":
            out = subprocess.run(
                ["ifconfig", "en0"],
                capture_output=True, text=True, timeout=5,
            ).stdout
            for line in out.splitlines():
                if "ether" in line:
                    mac = line.split("ether")[1].strip().split()[0]
                    return mac.upper().replace(":", "-")
    except Exception:
        pass
    return "00-00-00-00-00-00"


# ── 文件路径 ────────────────────────────────────────────────────────────
def _pkg_root() -> Path:
    p = Path(__file__).resolve()
    for anc in p.parents:
        if (anc / "agent_flow_harness").is_dir():
            return anc.parent
    return p.parent.parent.parent


def license_path() -> Path:
    p = Path(os.path.expanduser(settings.LICENSE_PATH))
    return p if p.is_absolute() else (_pkg_root() / p)


# ── 解析与验证 ──────────────────────────────────────────────────────────
def parse_license(content: bytes) -> LicensePayload:
    """解析 jasper.identity → 验签 + 解密 + XML 解析。

    raises ValueError: 错误码。
    """
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    # 1. 按分隔符分割（0x0D；兼容 0x0A——网页激活向导粘贴时 textarea 按 HTML
    #    规范会把 \r 规范化成 \n，严格要求 0x0D 会导致粘贴内容全部解析失败）
    idx = max(content.rfind(b"\x0d"), content.rfind(b"\x0a"))
    if idx < 1 or idx >= len(content) - 1:
        raise ValueError(LIC_E_READ)
    try:
        ciphertext = base64.b64decode(content[:idx])
        signature = base64.b64decode(content[idx + 1:])
    except Exception:
        raise ValueError(LIC_E_READ) from None

    # 2. RSA-SHA256 验签
    try:
        from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
        loaded = serialization.load_pem_public_key(_RSA_PUB_PEM.encode())
        assert isinstance(loaded, RSAPublicKey)  # 我们嵌入的必须是 RSA
        loaded.verify(signature, ciphertext, padding.PKCS1v15(), hashes.SHA256())
    except InvalidSignature:
        raise ValueError(LIC_E_SIGNATURE) from None

    # 3. AES-128-ECB 解密
    aes_key = base64.b64decode(_AES_KEY_B64)
    cipher = Cipher(algorithms.AES(aes_key), modes.ECB())
    decryptor = cipher.decryptor()
    padded = decryptor.update(ciphertext) + decryptor.finalize()
    pad_len = padded[-1]
    if pad_len < 1 or pad_len > 16:
        raise ValueError(LIC_E_READ)
    plaintext = padded[:-pad_len]

    # 4. XML 解析
    try:
        root = ET.fromstring(plaintext)
        licence = root.find("licence")
        if licence is None:
            raise ValueError(LIC_E_READ)
        payload = LicensePayload(
            licence_no=root.findtext("licenceNo", ""),
            company_name=licence.findtext("companyName", ""),
            application_name=licence.findtext("applicationName", ""),
            user_count=int(licence.findtext("userCount", "0")),
            auth_type=licence.findtext("authType", ""),
            usage=licence.findtext("usage", ""),
            effective_start=licence.findtext("effectiveStartDate", ""),
            effective_end=licence.findtext("effectiveEndDate", ""),
            mac_addresses=[m.text for m in licence.findall(".//macAddress") if m.text],
        )
    except ET.ParseError:
        raise ValueError(LIC_E_READ) from None

    return payload


# ── 校验主流程（带缓存）────────────────────────────────────────────────
_cache_lock = threading.Lock()
_cached_status: LicenseStatus | None = None
_cached_at: float = 0.0
_CACHE_TTL_SECONDS = 60.0


def _evaluate() -> LicenseStatus:
    fp = get_machine_fingerprint()
    if not is_enforced():
        return LicenseStatus(ok=True, code=LIC_OK, enforced=False, fingerprint=fp)

    path = license_path()
    if not path.exists():
        return LicenseStatus(ok=False, code=LIC_E_NOT_ACTIVATED, enforced=True, fingerprint=fp)

    try:
        content = path.read_bytes()
    except OSError:
        return LicenseStatus(ok=False, code=LIC_E_READ, enforced=True, fingerprint=fp)

    try:
        payload = parse_license(content)
    except ValueError as exc:
        code = str(exc) or LIC_E_READ
        logger.warning("license_invalid code={}", code)
        return LicenseStatus(ok=False, code=code, enforced=True, fingerprint=fp)

    # MAC 绑机检查（authType="mac" 时）
    if payload.auth_type == "mac" and payload.mac_addresses:
        local_mac = fp
        if local_mac not in payload.mac_addresses:
            logger.warning("license_mac_mismatch local={} licensed={}", local_mac, payload.mac_addresses)
            return LicenseStatus(ok=False, code=LIC_E_FINGERPRINT, enforced=True, fingerprint=fp)

    # 到期检查
    if payload.expires_at is not None:
        now = _now()
        # 有效期可能是带时区的 ISO 格式
        exp = payload.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=UTC)
        if now > exp:
            return LicenseStatus(ok=False, code=LIC_E_EXPIRED, enforced=True, fingerprint=fp)

    return LicenseStatus(ok=True, code=LIC_OK, enforced=True, payload=payload, fingerprint=fp)


def evaluate_license(force: bool = False) -> LicenseStatus:
    global _cached_status, _cached_at
    if not force:
        with _cache_lock:
            if _cached_status is not None and time.monotonic() - _cached_at < _CACHE_TTL_SECONDS:
                return _cached_status
    status = _evaluate()
    with _cache_lock:
        _cached_status = status
        _cached_at = time.monotonic()
    return status


def ensure_licensed() -> None:
    status = evaluate_license()
    if not status.ok:
        raise LicenseError(status.code)


def install_license(content: str) -> LicenseStatus:
    """校验并落盘新 license（原子替换），随后热放行。"""
    content_bytes = content.strip().encode("utf-8")
    try:
        payload = parse_license(content_bytes)
    except ValueError as exc:
        return LicenseStatus(ok=False, code=str(exc) or LIC_E_READ, enforced=is_enforced())

    if not is_enforced():
        _atomic_write_license(content_bytes)
        return evaluate_license(force=True)

    # MAC 检查
    local_mac = get_machine_fingerprint()
    if (payload.auth_type == "mac" and payload.mac_addresses
            and local_mac not in payload.mac_addresses):
        return LicenseStatus(ok=False, code=LIC_E_FINGERPRINT, enforced=True, fingerprint=local_mac)

    # 到期检查
    if payload.expires_at is not None:
        exp = payload.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=UTC)
        if _now() > exp:
            return LicenseStatus(ok=False, code=LIC_E_EXPIRED, enforced=True)

    _atomic_write_license(content_bytes)
    logger.info("license_installed company={} licence_no={}", payload.company_name, payload.licence_no)
    return evaluate_license(force=True)


def _atomic_write_license(content: bytes) -> None:
    path = license_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(content)
    os.replace(tmp, path)


def license_request_info() -> dict[str, Any]:
    return {
        "product": PRODUCT,
        "mac_address": get_machine_fingerprint(),
        "generated_at": _now().isoformat(),
    }
