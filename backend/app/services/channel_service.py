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
from datetime import UTC, datetime, timedelta

from pymongo.errors import DuplicateKeyError

from app.channels.base import InboundMessage, OutboundEnvelope
from app.channels.errors import (
    AgentRuntimeError,
    PermanentChannelError,
    SendFailedError,
    TransientChannelError,
)
from app.channels.registry import ChannelRegistry
from app.core.config import settings
from app.db.mongodb import get_database
from app.models.channel import (
    ChannelConfig,
    ChannelProvider,
    ChannelStatus,
    InboundEventLog,
    InboundEventLogStatus,
)
from app.schemas.execution import ExecutionRequest
from app.services.agent_execution_service import AgentExecutionService
from app.services.session_service import SessionService

logger = logging.getLogger(__name__)

# IM 侧手动开新会话的指令（精确匹配，剥离首尾空白后）。命中后不进 agent，
# 直接创建新 session 并回复确认——下一次消息自然续在新会话上。
_SESSION_RESET_COMMANDS = ("#新话题", "/new", "/reset")
_SESSION_RESET_REPLY = "已开启新话题，请直接说出你的问题～"

# 群聊的 chat_type 平台原值（钉钉 "2"；飞书 "group"）。群消息加 "[昵称] "
# 前缀送入 agent——共享会话流保留跨用户接话能力，同时让 agent 感知"谁在
# 说话"（记忆归属到人）。单聊不加（一对一无需区分）。
_GROUP_CHAT_TYPES = frozenset({"2", "group"})


def _agent_input(inbound: InboundMessage) -> str:
    """Build the text sent to the agent (group messages get sender prefix).

    重置指令匹配、会话标题、去重均使用原始 text；前缀只影响 agent 输入。
    无昵称（如飞书事件不含）时退回裸文本。
    """
    if inbound.chat_type in _GROUP_CHAT_TYPES and inbound.platform_user_name:
        return f"[{inbound.platform_user_name}] {inbound.text}"
    return inbound.text


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
        try:
            await coll.insert_one(log.model_dump(by_alias=True))
        except DuplicateKeyError:
            # Concurrent race: another request inserted the same
            # (channel_id, platform_message_id) between our find_one and
            # insert_one. Treat as a duplicate and ack the platform.
            return None
        return log.id

    # ── Orchestration ──

    @staticmethod
    async def execute(
        inbound: InboundMessage, event_log_id: str | None = None
    ) -> None:
        """Resolve session, invoke agent, send reply.

        TransientChannelError propagates (the Celery task retries the whole
        message). PermanentChannelError → handle_error (fallback reply).

        Args:
            inbound: The normalized inbound message to process.
            event_log_id: Optional id of the persisted InboundEventLog. When
                provided, handle_error is handed the *real* persisted log so it
                can update its status to FAILED. When None (e.g. synchronous
                test callers without a persisted log), an in-memory log is
                reconstructed — handle_error's status update is then a no-op,
                which is acceptable for those callers.
        """
        config = await ChannelService.get_config(inbound.channel_id)
        if config is None or not config.enabled:
            logger.warning("channel %s missing or disabled", inbound.channel_id)
            return

        # 会话重置指令：不进 agent，开新 session 并直接确认（消费掉指令本身）。
        if _match_reset_command(inbound.text) is not None:
            user_id = f"channel:{config.id}:{inbound.platform_chat_id}"
            await SessionService.create_session(
                user_id=user_id, agent_id=config.agent_id, title="新话题",
            )
            await ChannelService._send_reply(inbound, config, _SESSION_RESET_REPLY)
            return

        try:
            reply_text = await ChannelService._invoke_agent(inbound, config)
            await ChannelService._send_reply(inbound, config, reply_text)
            await ChannelService._reset_failure_counter(config.id)
        except PermanentChannelError as e:
            logger.warning("permanent channel error: %s", e)
            if event_log_id is not None:
                # Fetch the real persisted log so handle_error can update its
                # status from PENDING → FAILED on the actual document.
                real_log = await ChannelService.get_event_log(event_log_id)
                if real_log is None:
                    # Log was TTL'd or missing; reconstruct in-memory using the
                    # provided id so any (no-op) update still targets that id.
                    real_log = InboundEventLog(
                        _id=event_log_id,
                        channel_id=inbound.channel_id,
                        platform_message_id=inbound.message_id,
                        payload=inbound.model_dump(mode="json"),
                    )
            else:
                # Synchronous caller (e.g. tests) without a persisted log —
                # reconstruct a fresh in-memory log (new id).
                real_log = InboundEventLog(
                    channel_id=inbound.channel_id,
                    platform_message_id=inbound.message_id,
                    payload=inbound.model_dump(mode="json"),
                )
            await ChannelService.handle_error(real_log, config, e)
        # TransientChannelError intentionally propagates to the Celery task.

    @staticmethod
    async def _invoke_agent(inbound: InboundMessage, config: ChannelConfig) -> str:
        """Encode identity into user_id, resolve a continuable session, invoke.

        会话延续（对齐行业惯例，见 docs/channel-long-connection-guide.md）：
        身份域 channel:{ch}:{chat} 内复用最近活跃 session——单聊连续多轮、
        群聊全群共享一条流。三个轮换边界：空闲超过
        CHANNEL_SESSION_IDLE_RESET_MINUTES、会话活满 CHANNEL_SESSION_MAX_AGE_HOURS
        （防止持续活跃的聊天无限累积）、token 预算耗尽（自动开新会话重试本轮）。
        复用的 session_id 传入 ExecutionRequest，与 Web 端多轮对话走完全相同
        的链路（checkpointer thread、token 预算、llm_summary 压缩随之自动生效）。
        """
        user_id = f"channel:{config.id}:{inbound.platform_chat_id}"
        session_id = await ChannelService._find_continuable_session(
            user_id, config.agent_id
        )
        from app.core.errors import SessionBudgetExceededError

        agent_input = _agent_input(inbound)
        try:
            response = await AgentExecutionService.invoke(
                agent_id=config.agent_id,
                body=ExecutionRequest(input=agent_input, session_id=session_id),
                user_id=user_id,
            )
        except SessionBudgetExceededError:
            # 预算耗尽的那条 session 已无法承载新消息（且刚被写入 updated_at，
            # 后续查找仍会命中）→ 立刻开新 session 承接本轮与后续消息。
            fresh = await SessionService.create_session(
                user_id=user_id, agent_id=config.agent_id,
                title=inbound.text[:200],
            )
            logger.info(
                "channel_session_budget_rollover user=%s old=%s new=%s",
                user_id, session_id, fresh["_id"],
            )
            response = await AgentExecutionService.invoke(
                agent_id=config.agent_id,
                body=ExecutionRequest(
                    input=agent_input, session_id=str(fresh["_id"]),
                ),
                user_id=user_id,
            )
        return response.output

    @staticmethod
    async def _find_continuable_session(user_id: str, agent_id: str) -> str | None:
        """Latest active session for this channel identity, None → start new.

        ``updated_at`` is bumped on every message/token write, so "latest"
        tracks the conversation the chat is actually in; the idle window
        (updated_since) rolls quiet chats, the max-age bound (created_since)
        rolls continuously-active ones so a single session can't accumulate
        messages/tokens forever.
        """
        idle_minutes = settings.CHANNEL_SESSION_IDLE_RESET_MINUTES
        max_age_hours = settings.CHANNEL_SESSION_MAX_AGE_HOURS
        updated_since = (
            (datetime.now(UTC) - timedelta(minutes=idle_minutes)).isoformat()
            if idle_minutes > 0 else None
        )
        created_since = (
            (datetime.now(UTC) - timedelta(hours=max_age_hours)).isoformat()
            if max_age_hours > 0 else None
        )
        doc = await SessionService.get_latest_session(
            user_id, agent_id,
            updated_since=updated_since, created_since=created_since,
        )
        if doc is not None:
            logger.info(
                "channel_session_reused user=%s session=%s", user_id, doc["_id"],
            )
            return str(doc["_id"])
        return None

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
            # Pass selected inbound-derived fields so platform adapters that
            # need them (e.g. DingTalk's session_webhook) can reply.
            context=_extract_send_context(inbound),
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
            context=_extract_send_context(inbound),
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

        # 3. Per spec §5.2.4, every PermanentChannelError counts toward
        #    consecutive_failures except AgentRuntimeError (which is a code
        #    bug in the agent itself, not the channel — degrading would punish
        #    every other user on this channel for a bug they didn't cause).
        #    InvalidCredentialsError AND SendFailedError (e.g. platform API
        #    outage) both bump; otherwise a persistently failing channel
        #    would silently lose every message and stay ACTIVE forever.
        if not isinstance(error, AgentRuntimeError):
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

    # ── CRUD (called by management API) ──

    @staticmethod
    async def create_channel(
        *, name: str, provider: ChannelProvider, agent_id: str,
        credentials: dict, owner_user_id: str,
        receive_mode: str = "webhook",
    ) -> ChannelConfig:
        import secrets

        from app.core.crypto import encrypt_secret

        encrypted_creds = {
            k: encrypt_secret(str(v)) for k, v in credentials.items() if v
        }
        cfg = ChannelConfig(
            name=name, provider=provider, agent_id=agent_id,
            owner_user_id=owner_user_id,
            credentials=encrypted_creds,
            webhook_secret=secrets.token_urlsafe(32),
            receive_mode=receive_mode,
        )
        await ChannelService._configs_coll().insert_one(cfg.model_dump(by_alias=True))
        return cfg

    @staticmethod
    async def list_channels(
        *, owner_user_id: str, page: int = 1, page_size: int = 20,
    ) -> tuple[list[ChannelConfig], int]:
        skip = (page - 1) * page_size
        coll = ChannelService._configs_coll()
        total = await coll.count_documents({"owner_user_id": owner_user_id})
        cursor = coll.find({"owner_user_id": owner_user_id}).skip(skip).limit(page_size)
        docs = await cursor.to_list(length=page_size)
        return [ChannelConfig(**d) for d in docs], total

    @staticmethod
    async def get_channel(channel_id: str, owner_user_id: str) -> ChannelConfig | None:
        doc = await ChannelService._configs_coll().find_one({
            "_id": channel_id, "owner_user_id": owner_user_id,
        })
        return ChannelConfig(**doc) if doc else None

    @staticmethod
    async def update_channel(
        channel_id: str, owner_user_id: str, *, name=None, agent_id=None,
        credentials: dict | None = None, enabled=None,
        receive_mode: str | None = None,
    ) -> ChannelConfig | None:
        from app.core.crypto import encrypt_secret

        update: dict = {"updated_at": datetime.now(UTC).isoformat()}
        if name is not None:
            update["name"] = name
        if agent_id is not None:
            update["agent_id"] = agent_id
        if enabled is not None:
            update["enabled"] = enabled
        if receive_mode is not None:
            update["receive_mode"] = receive_mode
        if credentials:
            # Merge: only overwrite keys the caller explicitly provided.
            # A partial update (e.g. only verification_token) must NOT wipe
            # existing app_id/app_secret — that was a real bug where editing
            # one credential field in the UI cleared the others.
            existing_doc = await ChannelService._configs_coll().find_one(
                {"_id": channel_id, "owner_user_id": owner_user_id},
                projection={"credentials": 1},
            )
            merged: dict = dict(existing_doc.get("credentials", {})) if existing_doc else {}
            for k, v in credentials.items():
                if v:  # skip empty values (UI "leave unchanged")
                    merged[k] = encrypt_secret(str(v))
            update["credentials"] = merged
        await ChannelService._configs_coll().update_one(
            {"_id": channel_id, "owner_user_id": owner_user_id},
            {"$set": update},
        )
        return await ChannelService.get_channel(channel_id, owner_user_id)

    @staticmethod
    async def delete_channel(channel_id: str) -> None:
        """Soft delete: disable + mark DISABLED. Keeps row for audit/event logs."""
        await ChannelService._configs_coll().update_one(
            {"_id": channel_id},
            {"$set": {
                "enabled": False,
                "status": ChannelStatus.DISABLED,
                "updated_at": datetime.now(UTC).isoformat(),
            }},
        )

    @staticmethod
    async def set_enabled(channel_id: str, enabled: bool) -> None:
        await ChannelService._configs_coll().update_one(
            {"_id": channel_id},
            {"$set": {
                "enabled": enabled,
                "status": ChannelStatus.ACTIVE if enabled else ChannelStatus.DISABLED,
                "updated_at": datetime.now(UTC).isoformat(),
            }},
        )

    @staticmethod
    async def reset_degraded(channel_id: str) -> None:
        """Manually clear DEGRADED state + reset failure counter."""
        await ChannelService._configs_coll().update_one(
            {"_id": channel_id},
            {"$set": {
                "consecutive_failures": 0,
                "status": ChannelStatus.ACTIVE,
                "updated_at": datetime.now(UTC).isoformat(),
            }},
        )

    @staticmethod
    def mask_credentials(credentials: dict) -> dict:
        from app.core.crypto import mask_secret

        return {k: mask_secret(str(v)) for k, v in credentials.items()}


# Adapter.send() may be sync (MockChannel) or async (Lark/DingTalk/WeCom).
# Detect and await if needed.
async def _call_send(
    adapter, envelope: OutboundEnvelope, config: ChannelConfig
) -> str:
    result = adapter.send(envelope, config)
    if inspect.isawaitable(result):
        return await result
    return result


def _match_reset_command(text: str) -> str | None:
    """Return the matched reset command if ``text`` is exactly one (None else).

    Exact-match only — a message *containing* "#新话题" mid-sentence still
    goes to the agent.
    """
    stripped = text.strip()
    for cmd in _SESSION_RESET_COMMANDS:
        if stripped == cmd:
            return cmd
    return None


def _extract_send_context(inbound: InboundMessage) -> dict:
    """Pull platform-specific reply state from an inbound message's raw payload.

    Most platforms need nothing (they send via a stable OpenAPI + token). The
    notable exception is DingTalk, whose bot reply address (session_webhook)
    is embedded in each inbound event and expires after ~2h. We surface known
    platform-specific keys here so adapters can pick them up from the
    OutboundEnvelope without each adapter re-parsing InboundMessage.raw.
    """
    raw = inbound.raw or {}
    context: dict = {}
    # DingTalk stream / webhook both carry session_webhook on inbound events.
    sw = raw.get("session_webhook") or raw.get("sessionWebhook")
    if sw:
        context["session_webhook"] = sw
    return context
