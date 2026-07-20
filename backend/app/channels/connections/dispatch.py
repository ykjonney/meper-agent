"""Shared inbound dispatcher for long-connection events.

Long-connection clients receive raw platform events. Instead of re-implementing
parse + dedup + enqueue, each client converts its event into the same JSON body
the HTTP webhook would receive, then calls ``dispatch_inbound(config, body)``.

This guarantees webhook and long-connection modes share an identical downstream
pipeline: parse → dedup → persist → Celery ``process_inbound``.
"""
from __future__ import annotations

import json
import logging
from typing import Awaitable, Callable

from app.models.channel import ChannelConfig

logger = logging.getLogger(__name__)

# Parser type: (body, config) -> InboundMessage | None
# Each provider wires its own ``parse_xxx_event`` here.
EventParser = Callable[[str | bytes | dict, ChannelConfig], "object | None"]


async def dispatch_inbound(
    *, config: ChannelConfig, body: str | bytes | dict, parser: EventParser
) -> str | None:
    """Parse a long-connection event and enqueue it through the same pipeline
    as an HTTP webhook callback.

    Args:
        config: The channel that received the event.
        body: Raw platform payload, already verified by the SDK transport.
              For lark/dingtalk this is the same JSON the webhook would
              receive; pass it through unchanged.
        parser: Provider-specific parser (e.g. ``parse_lark_event``).

    Returns:
        The created InboundEventLog id, or None if dedup / parse skipped it.
    """
    # Late imports to avoid circulars at module import time.
    from app.services.channel_service import ChannelService
    from app.workers.tasks.channel_inbound import process_inbound

    if isinstance(body, (bytes, bytearray)):
        body_str = body.decode("utf-8", errors="replace")
    elif isinstance(body, dict):
        body_str = json.dumps(body, ensure_ascii=False)
    else:
        body_str = body

    try:
        inbound = parser(body_str, config)
    except Exception as exc:
        logger.warning(
            "long_connection_parse_failed channel=%s err=%s", config.id, exc
        )
        return None

    if inbound is None:
        # Non-text message, URL verification marker, or empty content — skip.
        return None

    log_id = await ChannelService.create_or_dedup_event(inbound)
    if log_id is None:
        logger.debug("long_connection_dedup channel=%s msg=%s", config.id, getattr(inbound, "message_id", "?"))
        return None

    # Enqueue via Celery — same as the webhook path. The FastAPI process
    # only owns the connection; execution still happens on the Celery worker
    # so a slow agent doesn't block event receipt.
    process_inbound.delay(log_id)
    return log_id
