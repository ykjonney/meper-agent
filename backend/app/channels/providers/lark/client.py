"""Lark OpenAPI client — send messages via /open-apis/im/v1/messages.

Docs: https://open.feishu.cn/document/server-docs/im-v1/message/create
"""
from __future__ import annotations

import json
import logging

import httpx

from app.core.crypto import decrypt_secret
from app.models.channel import ChannelConfig

logger = logging.getLogger(__name__)

TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
MESSAGE_URL = "https://open.feishu.cn/open-apis/im/v1/messages"

# Simple in-process token cache: {app_id: (token, expires_at)}
_token_cache: dict[str, tuple[str, float]] = {}


async def _get_tenant_access_token(config: ChannelConfig) -> str:
    import time
    app_id = config.credentials.get("app_id", "")
    cached = _token_cache.get(app_id)
    if cached and cached[1] > time.time() + 60:
        return cached[0]

    app_secret = decrypt_secret(config.credentials["app_secret"])
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(TOKEN_URL, json={
            "app_id": app_id,
            "app_secret": app_secret,
        })
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"lark token error: {data.get('msg')}")
        token = data["tenant_access_token"]
        expire = data.get("expire", 7200)
        _token_cache[app_id] = (token, time.time() + expire)
        return token


async def send_text_message(
    *, config: ChannelConfig, receive_id: str, text: str
) -> str:
    """Send a text message to a chat. Returns platform message id."""
    token = await _get_tenant_access_token(config)
    content = json.dumps({"text": text})
    receive_id_type = "chat_id" if not receive_id.startswith("ou_") else "open_id"
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            MESSAGE_URL,
            headers={"Authorization": f"Bearer {token}"},
            params={"receive_id_type": receive_id_type},
            json={"receive_id": receive_id, "msg_type": "text", "content": content},
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"lark send error: {data.get('msg')}")
        return data["data"]["message_id"]
