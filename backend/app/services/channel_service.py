"""ChannelService — orchestration layer between IM channels and agent execution.

Analogue of AgentExecutionService for inbound IM messages. Responsibilities:
  1. Idempotency: dedup by platform_message_id before processing.
  2. Session resolution: encode (channel_id, platform_chat_id) into user_id,
     reusing the existing session mechanism with zero changes.
  3. Execution: delegate to AgentExecutionService.invoke (reuses all existing
     prompt rendering / tool assembly / token budget / persistence).
  4. Outbound: translate reply → OutboundEnvelope → adapter.send(), with
     bounded internal retries for transient send failures.
  5. Error handling: fallback reply + event-log update + degraded-state
     bookkeeping for credential failures.

Adapters themselves never call AgentExecutionService — they go through this
service so cross-cutting logic stays in one place. This is the only call
site for AgentExecutionService outside the HTTP API layer.
"""
from __future__ import annotations

import inspect
import logging
from datetime import UTC, datetime

from app.channels.base import InboundMessage, OutboundEnvelope
from app.channels.errors import (
    InvalidCredentialsError,
    PermanentChannelError,
    SendFailedError,
    TransientChannelError,
)
from app.channels.registry import ChannelRegistry
from app.core.config import settings
from app.db.mongodb import get_database
from app.models.channel import (
    ChannelConfig,
    ChannelStatus,
    InboundEventLog,
    InboundEventLogStatus,
)
from app.schemas.execution import ExecutionRequest
from app.services.agent_execution_service import AgentExecutionService

logger = logging.getLogger(__name__)


class ChannelService:
    # ── DB access ──

    @staticmethod
    def _configs_coll():
        return get_database().channel_configs

    @staticmethod
    def _event_logs_coll():
        return get_database().inbound_event_logs

    @staticmethod
    async def get_config(channel_id: str) -> ChannelConfig | None:
        doc = await ChannelService._configs_coll().find_one({"_id": channel_id})
        return ChannelConfig(**doc) if doc else None

    @staticmethod
    async def get_event_log(log_id: str) -> InboundEventLog | None:
        doc = await ChannelService._event_logs_coll().find_one({"_id": log_id})
        return InboundEventLog(**doc) if doc else None

    # ── Idempotency ──

    @staticmethod
    async def create_or_dedup_event(inbound: InboundMessage) -> str | None:
        """Insert a pending event log entry, dedup by platform_message_id.

        Returns the new log id, or None if the event was already processed
        (duplicate). Caller should ack the platform and skip processing on None.
        """
        coll = ChannelService._event_logs_coll()
        existing = await coll.find_one({
            "channel_id": inbound.channel_id,
            "platform_message_id": inbound.message_id,
        })
        if existing:
            return None
        log = InboundEventLog(
            channel_id=inbound.channel_id,
            platform_message_id=inbound.message_id,
            payload=inbound.model_dump(mode="json"),
        )
        await coll.insert_one(log.model_dump(by_alias=True))
        return log.id

    # ── Orchestration ──

    @staticmethod
    async def execute(inbound: InboundMessage) -> None:
        """Resolve session, invoke agent, send reply.

        TransientChannelError propagates (the Celery task retries the whole
        message). PermanentChannelError → handle_error (fallback reply).
        """
        config = await ChannelService.get_config(inbound.channel_id)
        if config is None or not config.enabled:
            logger.warning("channel %s missing or disabled", inbound.channel_id)
            return

        try:
            reply_text = await ChannelService._invoke_agent(inbound, config)
            await ChannelService._send_reply(inbound, config, reply_text)
            await ChannelService._reset_failure_counter(config.id)
        except PermanentChannelError as e:
            logger.warning("permanent channel error: %s", e)
            dummy_log = InboundEventLog(
                channel_id=inbound.channel_id,
                platform_message_id=inbound.message_id,
                payload=inbound.model_dump(mode="json"),
            )
            await ChannelService.handle_error(dummy_log, config, e)
        # TransientChannelError intentionally propagates to the Celery task.

    @staticmethod
    async def _invoke_agent(inbound: InboundMessage, config: ChannelConfig) -> str:
        """Encode identity into user_id, call AgentExecutionService.invoke."""
        user_id = f"channel:{config.id}:{inbound.platform_chat_id}"
        body = ExecutionRequest(input=inbound.text)
        response = await AgentExecutionService.invoke(
            agent_id=config.agent_id,
            body=body,
            user_id=user_id,
        )
        return response.output

    @staticmethod
    async def _send_reply(
        inbound: InboundMessage, config: ChannelConfig, text: str
    ) -> None:
        """Translate reply → envelope → adapter.send(), with bounded retries.

        PermanentChannelError is re-raised immediately (no retry). Transient
        failures are retried up to CHANNEL_SEND_MAX_RETRIES times; if all
        attempts fail, the call is converted to SendFailedError.
        """
        envelope = OutboundEnvelope(
            channel_id=config.id,
            platform_chat_id=inbound.platform_chat_id,
            text=text,
            reply_to_message_id=inbound.message_id,
        )
        adapter = ChannelRegistry.get(config.provider)
        last_err: Exception | None = None
        for attempt in range(1, settings.CHANNEL_SEND_MAX_RETRIES + 1):
            try:
                return await _call_send(adapter, envelope, config)
            except PermanentChannelError:
                raise  # don't retry permanent errors
            except TransientChannelError as e:
                last_err = e
                logger.info("send attempt %d failed (transient): %s", attempt, e)
            except Exception as e:
                last_err = e
                logger.error("send attempt %d failed: %s", attempt, e)
        raise SendFailedError(
            f"send failed after {settings.CHANNEL_SEND_MAX_RETRIES} attempts: {last_err}"
        )

    # ── Error handling ──

    @staticmethod
    async def handle_error(
        event_log: InboundEventLog,
        config: ChannelConfig,
        error: PermanentChannelError,
    ) -> None:
        """Send fallback user_message + mark event log failed + bookkeeping."""
        # 1. Reply user-facing message (best-effort — don't shadow the real error)
        inbound = InboundMessage(**event_log.payload)
        envelope = OutboundEnvelope(
            channel_id=config.id,
            platform_chat_id=inbound.platform_chat_id,
            text=error.user_message,
            reply_to_message_id=inbound.message_id,
        )
        adapter = ChannelRegistry.get(config.provider)
        try:
            await _call_send(adapter, envelope, config)
        except Exception as send_err:
            logger.error("fallback reply also failed: %s", send_err)

        # 2. Update event log status
        await ChannelService._event_logs_coll().update_one(
            {"_id": event_log.id},
            {"$set": {
                "status": InboundEventLogStatus.FAILED,
                "processed_at": datetime.now(UTC).isoformat(),
                "error": f"{type(error).__name__}: {error}",
            }},
        )

        # 3. Credential failures degrade the channel; code bugs don't.
        #    AgentRuntimeError is a transient code bug (the agent itself is
        #    broken, not the channel creds), so degrading would make things
        #    worse for every other user on this channel. Only credential
        #    failures count toward the degrade threshold.
        if isinstance(error, InvalidCredentialsError):
            await ChannelService._bump_failure_counter(config.id)

    @staticmethod
    async def _bump_failure_counter(channel_id: str) -> None:
        await ChannelService._configs_coll().update_one(
            {"_id": channel_id},
            {"$inc": {"consecutive_failures": 1}},
        )
        await ChannelService._maybe_degrade(channel_id)

    @staticmethod
    async def _reset_failure_counter(channel_id: str) -> None:
        await ChannelService._configs_coll().update_one(
            {"_id": channel_id},
            {"$set": {
                "consecutive_failures": 0,
                "status": ChannelStatus.ACTIVE,
            }},
        )

    @staticmethod
    async def _maybe_degrade(channel_id: str) -> None:
        cfg = await ChannelService._configs_coll().find_one({"_id": channel_id})
        if cfg and cfg.get("consecutive_failures", 0) >= settings.CHANNEL_DEGRADED_ON_CONSECUTIVE_FAILURES:
            await ChannelService._configs_coll().update_one(
                {"_id": channel_id},
                {"$set": {"status": ChannelStatus.DEGRADED}},
            )
            logger.warning(
                "channel %s auto-degraded after %d failures",
                channel_id, cfg["consecutive_failures"],
            )


# Adapter.send() may be sync (MockChannel) or async (Lark/DingTalk/WeCom).
# Detect and await if needed.
async def _call_send(
    adapter, envelope: OutboundEnvelope, config: ChannelConfig
) -> str:
    result = adapter.send(envelope, config)
    if inspect.isawaitable(result):
        return await result
    return result
