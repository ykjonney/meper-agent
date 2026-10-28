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


def _read_carrier(iface: Path) -> str:
    """接口链路状态：'1'=up / '0'=down / ''=读取失败（管理态 down 等）。"""
    try:
        return (iface / "carrier").read_text().strip()
    except (OSError, ValueError):
        return ""


def _iface_rank(iface: Path) -> tuple[int, str]:
    """物理网卡排序键：carrier up 优先 > 读取失败 > down；同级按硬件槽位
    路径（device 解析结果，PCI 总线序）——与接口命名无关，跨重启/改名/
    udev 规则都稳定（eth0、ens192、enp0s3 同一槽位路径不变）。"""
    rank = {"1": 0, "": 1, "0": 2}.get(_read_carrier(iface), 1)
    try:
        hw = str((iface / "device").resolve())
    except OSError:
        hw = str(iface)
    return (rank, hw)


def _select_linux_iface(sys_net: Path) -> Path | None:
    """选绑机网卡：物理网卡优先——``device`` 符号链接 = 真实硬件背书
    （PCI/USB/virtio），docker0/veth/bridge/tun/wg 等**虚拟接口均没有**；
    同为物理时 carrier up 优先、硬件槽位排序。全部无硬件背书（如无硬件
    直通的容器内）退回"第一个非 lo"（旧行为兜底）。"""
    candidates: list[Path] = []
    fallback: Path | None = None
    try:
        entries = sorted(sys_net.iterdir())
    except OSError:
        return None
    for p in entries:
        # 注意：/sys/class/net 下混有普通文件（如 bonding_masters 控制文件，
        # 模块加载即存在、字母序靠前）——只认目录
        if p.name == "lo" or not p.is_dir():
            continue
        if fallback is None:
            fallback = p
        if (p / "device").exists():
            candidates.append(p)
    if candidates:
        return sorted(candidates, key=_iface_rank)[0]
    return fallback


def _measure_mac() -> str:
    """实测绑机网卡 MAC（XX-XX-...格式；失败返回空串）。

    网卡目录由 ``LICENSE_SYS_NET_PATH`` 决定：手动部署读宿主
    ``/sys/class/net``；Docker 部署 compose 把宿主该目录只读挂载到
    ``/host-sys/class/net`` 并设此变量——两形态选到同一块物理网卡。
    """
    import subprocess
    import sys

    try:
        if sys.platform.startswith("linux"):
            iface = _select_linux_iface(Path(settings.LICENSE_SYS_NET_PATH))
            if iface is not None:
                return (iface / "address").read_text().strip().upper().replace(":", "-")
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
    return ""


def _read_primary_mac() -> str:
    """绑机指纹信源（XX-XX-XX-XX-XX-XX，与 Java 端一致）。

    实测优先（安全报告修复 4 v2）：手动部署读宿主物理网卡，Docker 部署
    经只读挂载读宿主同一块物理网卡——两形态同源同值，不依赖启动方式。
    ``AGENT_FLOW_MAC`` 降级为手动覆盖项（compose 不再注入）：
    - 与实测一致 → 静默采信；
    - 不一致 → 记结构化告警 ``license_mac_env_mismatch``（伪造指纹的
      审计信号，缓存保证每进程仅一次）后按 ``LICENSE_TRUST_ENV_MAC``
      决定采信——默认 true 保持兼容；
    - 实测全失败 → 维持回退 ``00-00-00-00-00-00``。
    """
    env_mac = os.environ.get("AGENT_FLOW_MAC", "").strip().upper().replace(":", "-")
    hw_mac = _measure_mac()
    if env_mac:
        if hw_mac and env_mac != hw_mac:
            logger.warning(
                "license_mac_env_mismatch local={} env={}", hw_mac, env_mac
            )
        if hw_mac and not settings.LICENSE_TRUST_ENV_MAC:
            return hw_mac
        return env_mac
    return hw_mac or "00-00-00-00-00-00"


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
