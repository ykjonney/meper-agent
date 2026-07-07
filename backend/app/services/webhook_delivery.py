"""Webhook delivery — HTTP POST with HMAC signing and retry logic."""
from __future__ import annotations

import json
import time

import httpx
from loguru import logger

from app.services.webhook_service import WebhookService, compute_signature

MAX_RETRIES = 5
BACKOFF_BASE = 1  # seconds: 1, 2, 4, 8, 16
TIMEOUT = 10  # seconds


async def deliver_with_retry(
    webhook_id: str,
    url: str,
    secret: str,
    event: str,
    payload: dict,
) -> bool:
    """Deliver a webhook event with exponential backoff retry.

    Returns True if delivery succeeded, False otherwise.
    """
    body_json = json.dumps(payload, ensure_ascii=False, default=str)
    last_error: str | None = None
    last_status: int | None = None

    for attempt in range(1, MAX_RETRIES + 1):
        timestamp = int(time.time())
        signature = compute_signature(secret, timestamp, body_json)

        headers = {
            "Content-Type": "application/json",
            "X-Webhook-Event": event,
            "X-Webhook-Signature": f"sha256={signature}",
            "X-Webhook-Timestamp": str(timestamp),
            "User-Agent": "AgentFlow-Webhook/1.0",
        }

        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                resp = await client.post(url, content=body_json, headers=headers)

            if 200 <= resp.status_code < 300:
                logger.info(
                    "webhook_delivered",
                    webhook_id=webhook_id,
                    event=event,
                    attempt=attempt,
                )
                await WebhookService.log_delivery(
                    webhook_id=webhook_id,
                    event=event,
                    url=url,
                    status_code=resp.status_code,
                    success=True,
                    attempts=attempt,
                )
                return True

            last_status = resp.status_code
            last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"

        except httpx.TimeoutException:
            last_error = "Request timed out"
        except Exception as exc:
            last_error = str(exc)

        logger.warning(
            "webhook_delivery_failed",
            webhook_id=webhook_id,
            event=event,
            attempt=attempt,
            error=last_error,
        )

        # Wait before retry (exponential backoff)
        if attempt < MAX_RETRIES:
            wait = BACKOFF_BASE * (2 ** (attempt - 1))
            await _async_sleep(wait)

    # All retries exhausted
    logger.error(
        "webhook_delivery_exhausted",
        webhook_id=webhook_id,
        event=event,
        attempts=MAX_RETRIES,
        error=last_error,
    )
    await WebhookService.log_delivery(
        webhook_id=webhook_id,
        event=event,
        url=url,
        status_code=last_status,
        success=False,
        attempts=MAX_RETRIES,
        error=last_error,
    )
    return False


async def _async_sleep(seconds: float) -> None:
    """Async-compatible sleep."""
    import asyncio

    await asyncio.sleep(seconds)
