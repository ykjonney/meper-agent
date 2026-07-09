"""API Key encryption utilities — AES-256-GCM symmetric encryption.

Provides reversible encryption for sensitive credentials stored in the
``models`` collection. The master key is loaded from the
``MODEL_ENCRYPTION_KEY`` environment variable (Base64-encoded 32 bytes).

Design:
- Algorithm: AES-256-GCM (authenticated encryption)
- Nonce: 12 bytes random per encryption (prepended to ciphertext)
- Output: Base64(nonce || ciphertext || tag) as a single string
"""
from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import settings
from app.core.errors import AppError

# GCM recommends a 96-bit (12-byte) nonce
_NONCE_BYTES = 12
# AES-256 requires a 32-byte (256-bit) key
_KEY_BYTES = 32


class CryptoError(AppError):
    """Raised when encryption / decryption of API keys fails."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(code=code, message=message, status_code=500)


def _load_master_key() -> bytes:
    """Load and decode the master encryption key from settings.

    The key is expected to be a Base64-encoded 32-byte value.

    Raises:
        CryptoError: If the key is missing or has the wrong length.
    """
    raw = settings.MODEL_ENCRYPTION_KEY
    if not raw:
        raise CryptoError(
            code="MODEL_ENCRYPTION_KEY_MISSING",
            message="缺少 MODEL_ENCRYPTION_KEY 配置，无法加解密 API Key",
        )

    try:
        key = base64.b64decode(raw, validate=True)
    except Exception as exc:
        raise CryptoError(
            code="MODEL_ENCRYPTION_KEY_INVALID",
            message="MODEL_ENCRYPTION_KEY 不是合法的 Base64 字符串",
        ) from exc

    if len(key) != _KEY_BYTES:
        raise CryptoError(
            code="MODEL_ENCRYPTION_KEY_INVALID",
            message=(
                f"MODEL_ENCRYPTION_KEY 长度不正确，期望 {_KEY_BYTES} 字节，"
                f"实际 {len(key)} 字节"
            ),
        )
    return key


def get_encryption_key() -> bytes:
    """Return the configured master encryption key (cached per-call)."""
    return _load_master_key()


def encrypt_api_key(plaintext: str, master_key: bytes | None = None) -> str:
    """Encrypt a plaintext API key with AES-256-GCM.

    Args:
        plaintext: The raw API key string.
        master_key: Optional pre-decoded master key (avoids repeated decode).

    Returns:
        Base64(nonce || ciphertext || tag).
    """
    key = master_key if master_key is not None else _load_master_key()
    nonce = os.urandom(_NONCE_BYTES)
    aesgcm = AESGCM(key)

    # AESGCM.append_tag=True (default) appends the tag to the ciphertext,
    # producing ciphertext || tag.
    ct = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), associated_data=None)
    return base64.b64encode(nonce + ct).decode("ascii")


def decrypt_api_key(encrypted: str, master_key: bytes | None = None) -> str:
    """Decrypt an AES-256-GCM encrypted API key.

    Args:
        encrypted: Base64(nonce || ciphertext || tag) produced by
            :func:`encrypt_api_key`.
        master_key: Optional pre-decoded master key.

    Returns:
        The plaintext API key string.

    Raises:
        CryptoError: If the input is malformed or decryption fails.
    """
    if not encrypted:
        raise CryptoError(
            code="MODEL_API_KEY_DECRYPT_FAILED",
            message="无法解密空的 API Key",
        )

    key = master_key if master_key is not None else _load_master_key()

    try:
        blob = base64.b64decode(encrypted, validate=True)
    except Exception as exc:
        raise CryptoError(
            code="MODEL_API_KEY_DECRYPT_FAILED",
            message="API Key 密文不是合法的 Base64 字符串",
        ) from exc

    if len(blob) <= _NONCE_BYTES:
        raise CryptoError(
            code="MODEL_API_KEY_DECRYPT_FAILED",
            message="API Key 密文长度不足",
        )

    nonce = blob[:_NONCE_BYTES]
    ct_with_tag = blob[_NONCE_BYTES:]
    aesgcm = AESGCM(key)

    try:
        plaintext = aesgcm.decrypt(nonce, ct_with_tag, associated_data=None)
    except Exception as exc:
        raise CryptoError(
            code="MODEL_API_KEY_DECRYPT_FAILED",
            message="API Key 解密失败，请检查 MODEL_ENCRYPTION_KEY 是否正确",
        ) from exc

    return plaintext.decode("utf-8")


def mask_api_key(plaintext: str) -> str:
    """Mask an API key for safe display, e.g. ``sk-****abcd``.

    The first 3 and last 4 characters are preserved; everything in
    between is replaced with ``****``. Keys shorter than 8 chars are
    fully masked as ``****``.
    """
    if not plaintext:
        return ""
    if len(plaintext) < 8:
        return "****"
    return f"{plaintext[:3]}****{plaintext[-4:]}"


# ---------------------------------------------------------------------------
# Semantic aliases — the original functions are named "api_key" but the
# implementation is generic AES-256-GCM string encryption. These aliases
# provide clearer semantics for non-API-key secrets (tool credentials, etc.).
# ---------------------------------------------------------------------------

encrypt_secret = encrypt_api_key
decrypt_secret = decrypt_api_key
mask_secret = mask_api_key
