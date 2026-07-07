"""Webhook service — CRUD, event dispatch, delivery logging."""
from __future__ import annotations

import hashlib
import hmac
import secrets

from loguru import logger

from app.core.errors import ValidationError
from app.db.mongodb import get_database
from app.models.base import utc_now
from app.models.webhook import (
    WEBHOOK_EVENTS,
    Webhook,
    WebhookDeliveryLog,
    WebhookStatus,
)


class WebhookService:
    """Service layer for Webhook configuration and event dispatch."""

    COLLECTION = "webhooks"
    LOG_COLLECTION = "webhook_delivery_logs"

    @staticmethod
    def _collection():
        return get_database()[WebhookService.COLLECTION]

    @staticmethod
    def _log_collection():
        return get_database()[WebhookService.LOG_COLLECTION]

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    @staticmethod
    async def create_webhook(
        name: str,
        url: str,
        events: list[str],
        api_key_id: str | None = None,
    ) -> dict:
        """Create a new Webhook configuration.

        Generates a random secret for HMAC signing.
        """
        # Validate events
        invalid = set(events) - set(WEBHOOK_EVENTS)
        if invalid:
            raise ValidationError(
                code="WEBHOOK_INVALID_EVENTS",
                message=f"无效的事件类型: {', '.join(sorted(invalid))}",
            )

        secret = secrets.token_urlsafe(32)
        webhook = Webhook(
            name=name,
            url=url,
            secret=secret,
            events=events,
            api_key_id=api_key_id,
        )

        doc = webhook.model_dump(by_alias=True)
        await WebhookService._collection().insert_one(doc)
        logger.info("webhook_created", webhook_id=webhook.id, name=name)
        # Return doc without secret in list/detail views
        return _strip_secret(doc)

    @staticmethod
    async def get_webhook(webhook_id: str) -> dict | None:
        """Get a Webhook by ID. Returns doc or None."""
        doc = await WebhookService._collection().find_one({"_id": webhook_id})
        if doc is None:
            return None
        return _strip_secret(doc)

    @staticmethod
    async def get_webhook_with_secret(webhook_id: str) -> dict | None:
        """Get a Webhook including the secret (internal use only)."""
        return await WebhookService._collection().find_one({"_id": webhook_id})

    @staticmethod
    async def list_webhooks(
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[dict], int]:
        """List Webhooks with pagination."""
        col = WebhookService._collection()
        total = await col.count_documents({})
        cursor = (
            col.find({}, {"secret": 0})
            .sort("created_at", -1)
            .skip((page - 1) * page_size)
            .limit(page_size)
        )
        items = await cursor.to_list(length=page_size)
        return items, total

    @staticmethod
    async def update_webhook(
        webhook_id: str,
        name: str | None = None,
        url: str | None = None,
        events: list[str] | None = None,
        api_key_id: str | None = None,
        status: str | None = None,
    ) -> dict | None:
        """Update a Webhook configuration."""
        col = WebhookService._collection()
        doc = await col.find_one({"_id": webhook_id})
        if doc is None:
            return None

        set_fields: dict = {"updated_at": utc_now().isoformat()}

        if name is not None:
            set_fields["name"] = name
        if url is not None:
            set_fields["url"] = url
        if events is not None:
            invalid = set(events) - set(WEBHOOK_EVENTS)
            if invalid:
                raise ValidationError(
                    code="WEBHOOK_INVALID_EVENTS",
                    message=f"无效的事件类型: {', '.join(sorted(invalid))}",
                )
            set_fields["events"] = events
        if api_key_id is not None:
            set_fields["api_key_id"] = api_key_id
        if status is not None:
            set_fields["status"] = status

        await col.update_one({"_id": webhook_id}, {"$set": set_fields})
        result = await col.find_one({"_id": webhook_id}, {"secret": 0})
        return result

    @staticmethod
    async def delete_webhook(webhook_id: str) -> bool:
        """Delete a Webhook configuration."""
        result = await WebhookService._collection().delete_one({"_id": webhook_id})
        return result.deleted_count > 0

    # ------------------------------------------------------------------
    # Event dispatch
    # ------------------------------------------------------------------

    @staticmethod
    async def dispatch_event(event: str, payload: dict) -> None:
        """Find matching active webhooks and enqueue delivery.

        This is the main entry point called from task/agent execution.

        Scoping rules:
        - If payload contains ``api_key_id``, only webhooks bound to that
          key (or system-wide webhooks with ``api_key_id=null``) match.
        - If payload has no ``api_key_id`` (internal trigger), only
          system-wide webhooks (``api_key_id=null``) match.
        - ``callback_url`` in payload is a one-off callback — handled
          independently, not affected by global webhook subscriptions.
        """
        if event not in WEBHOOK_EVENTS and event != "test":
            logger.warning("webhook_dispatch_unknown_event", event=event)
            return

        event_api_key_id = payload.get("api_key_id")

        # Build filter: event + active + scoped by api_key_id
        if event_api_key_id:
            # Match webhooks bound to this key OR system-wide webhooks
            query_filter = {
                "status": WebhookStatus.ACTIVE,
                "events": event,
                "$or": [
                    {"api_key_id": event_api_key_id},
                    {"api_key_id": None},
                ],
            }
        else:
            # Internal trigger — only system-wide webhooks
            query_filter = {
                "status": WebhookStatus.ACTIVE,
                "events": event,
                "api_key_id": None,
            }

        col = WebhookService._collection()
        cursor = col.find(query_filter)
        webhooks = await cursor.to_list(length=50)

        for wh in webhooks:
            _enqueue_delivery(wh, event, payload)

        # Handle callback_url (one-off) independently
        callback_url = payload.pop("callback_url", None)
        if callback_url and event in ("task.completed", "task.failed"):
            # Use any active webhook's secret for signing, or empty
            first_wh = webhooks[0] if webhooks else None
            secret = first_wh["secret"] if first_wh else ""
            _enqueue_oneoff_delivery(callback_url, event, payload, secret)

    # ------------------------------------------------------------------
    # Delivery log
    # ------------------------------------------------------------------

    @staticmethod
    async def log_delivery(
        webhook_id: str,
        event: str,
        url: str,
        status_code: int | None,
        success: bool,
        attempts: int,
        error: str | None = None,
    ) -> None:
        """Record a delivery attempt."""
        log = WebhookDeliveryLog(
            webhook_id=webhook_id,
            event=event,
            url=url,
            status_code=status_code,
            success=success,
            attempts=attempts,
            error=error,
        )
        await WebhookService._log_collection().insert_one(log.model_dump(by_alias=True))

    @staticmethod
    async def list_delivery_logs(
        webhook_id: str,
        limit: int = 50,
    ) -> list[dict]:
        """List recent delivery logs for a webhook."""
        cursor = (
            WebhookService._log_collection()
            .find({"webhook_id": webhook_id})
            .sort("timestamp", -1)
            .limit(limit)
        )
        return await cursor.to_list(length=limit)


def _strip_secret(doc: dict) -> dict:
    """Return a webhook doc without the secret field."""
    return {k: v for k, v in doc.items() if k != "secret"}


def _enqueue_delivery(webhook: dict, event: str, payload: dict) -> None:
    """Enqueue a Celery task for webhook delivery."""
    try:
        from app.workers.tasks.webhook_delivery import deliver_webhook

        deliver_webhook.delay(
            webhook_id=webhook["_id"],
            url=webhook["url"],
            secret=webhook["secret"],
            event=event,
            payload=payload,
        )
    except Exception:
        # If Celery is unavailable, do synchronous delivery (dev mode)
        logger.warning("webhook_celery_unavailable, attempting sync delivery")
        _deliver_sync(
            webhook_id=webhook["_id"],
            url=webhook["url"],
            secret=webhook["secret"],
            event=event,
            payload=payload,
        )


def _enqueue_oneoff_delivery(
    url: str, event: str, payload: dict, secret: str
) -> None:
    """Enqueue a one-off callback delivery (from callback_url)."""
    try:
        from app.workers.tasks.webhook_delivery import deliver_webhook

        deliver_webhook.delay(
            webhook_id="__callback__",
            url=url,
            secret=secret,
            event=event,
            payload=payload,
        )
    except Exception:
        logger.warning("webhook_celery_unavailable, attempting sync callback")
        _deliver_sync(
            webhook_id="__callback__",
            url=url,
            secret=secret,
            event=event,
            payload=payload,
        )


def _deliver_sync(
    webhook_id: str, url: str, secret: str, event: str, payload: dict
) -> None:
    """Synchronous fallback delivery (for dev/test without Celery)."""
    import asyncio

    from app.services.webhook_delivery import deliver_with_retry

    async def _run():
        await deliver_with_retry(
            webhook_id=webhook_id,
            url=url,
            secret=secret,
            event=event,
            payload=payload,
        )

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_run())
    except RuntimeError:
        asyncio.run(_run())


# ---------------------------------------------------------------------------
# HMAC signing
# ---------------------------------------------------------------------------


def compute_signature(secret: str, timestamp: int, body_json: str) -> str:
    """Compute HMAC-SHA256 signature for webhook payload.

    signature = HMAC-SHA256(secret, timestamp + "." + body_json)
    """
    message = f"{timestamp}.{body_json}"
    return hmac.new(
        secret.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
