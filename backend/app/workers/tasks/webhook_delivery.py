"""Celery task — async webhook delivery with retry."""
from loguru import logger

from app.workers.celery_app import celery_app


@celery_app.task(
    name="app.workers.tasks.webhook_delivery.deliver_webhook",
    bind=True,
    max_retries=5,
    default_retry_delay=1,
)
def deliver_webhook(
    self,
    webhook_id: str,
    url: str,
    secret: str,
    event: str,
    payload: dict,
) -> dict:
    """Deliver a webhook event via HTTP POST with HMAC signing.

    Retries up to 5 times with exponential backoff on failure.
    """
    from app.services.webhook_delivery import deliver_with_retry
    from app.workers.loop import run_async

    logger.info(
        "celery_webhook_delivery_start",
        webhook_id=webhook_id,
        event=event,
    )

    success = run_async(
        deliver_with_retry(
            webhook_id=webhook_id,
            url=url,
            secret=secret,
            event=event,
            payload=payload,
        )
    )

    return {
        "webhook_id": webhook_id,
        "event": event,
        "success": success,
    }
