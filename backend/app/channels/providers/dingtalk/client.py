"""DingTalk robot message-sending client.

Uses the group robot outgoing webhook to push messages back.
Docs: https://open.dingtalk.com/document/robots/robot-overview
"""
from __future__ import annotations

import logging

import httpx

from app.channels.errors import SendFailedError
from app.core.crypto import decrypt_secret
from app.models.channel import ChannelConfig

logger = logging.getLogger(__name__)


async def send_text_message(
    *, config: ChannelConfig, conversation_id: str, text: str
) -> str:
    """Send a text message back to the DingTalk conversation via group robot webhook."""
    webhook_url_enc = config.credentials.get("webhook_url")
    if not webhook_url_enc:
        raise SendFailedError("no webhook_url configured for dingtalk channel")
    webhook_url = decrypt_secret(webhook_url_enc)

    payload = {
        "msgtype": "text",
        "text": {"content": text},
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(webhook_url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            if data.get("errcode") != 0:
                raise SendFailedError(f"dingtalk send error: {data.get('errmsg')}")
            return data.get("messageId", f"dt_{id(payload)}")
    except httpx.HTTPError as e:
        raise SendFailedError(f"dingtalk http error: {e}") from e
