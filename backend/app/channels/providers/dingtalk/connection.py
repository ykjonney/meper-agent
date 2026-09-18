"""DingTalk (钉钉) long-connection client — receive events without a public URL.

Wraps ``dingtalk_stream.DingTalkStreamClient`` (Stream mode, WebSocket reverse
connection). Unlike lark, the dingtalk SDK is natively async, so no thread
bridge is needed — the SDK runs on the same asyncio loop.

Event flow on receipt:
  SDK dispatch → CallbackHandler.raw_process() → our process() override →
  build webhook-style JSON body → ``dispatch_inbound`` (parses, dedups,
  persists, enqueues Celery) → the same pipeline as HTTP webhook mode.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging

import dingtalk_stream

from app.channels.connections.base import ConnectionClient
from app.channels.connections.dispatch import dispatch_inbound
from app.channels.connections.manager import get_connection_manager
from app.channels.errors import InvalidCredentialsError
from app.channels.providers.dingtalk.verify import parse_dingtalk_event
from app.core.crypto import decrypt_secret
from app.models.channel import ChannelConfig

logger = logging.getLogger(__name__)


def register_dingtalk_connection() -> None:
    """Register the dingtalk ConnectionClient factory with the global manager.

    Called from ``app.channels.providers.__init__`` so the manager knows
    dingtalk supports long-connection mode.
    """
    if not _is_long_connection_enabled():
        logger.info("dingtalk_long_connection_disabled_by_config")
        return
    get_connection_manager().register_factory("dingtalk", DingtalkConnectionClient)
    logger.info("dingtalk_long_connection_registered")


def _is_long_connection_enabled() -> bool:
    from app.core.config import settings
    return settings.CHANNEL_DINGTALK_LONG_CONNECTION_ENABLED


class DingtalkConnectionClient(ConnectionClient):
    """One Stream-mode WebSocket connection to DingTalk for one ChannelConfig."""

    def __init__(self, config: ChannelConfig) -> None:
        super().__init__(config)
        self._sdk_client = None
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def connect(self) -> None:
        client_id = self._get_credential("app_key")
        client_secret = self._get_credential("app_secret")

        credential = dingtalk_stream.Credential(client_id, client_secret)
        self._sdk_client = dingtalk_stream.DingTalkStreamClient(credential)
        # The SDK client keeps the handler reference itself; ours would be
        # write-only, so we don't store one.
        self._sdk_client.register_callback_handler(
            _DingtalkMessageHandler.TOPIC, _DingtalkMessageHandler(self),
        )

        self._connected = True
        # Run the SDK loop as a separate task and SHIELD it: start() swallows
        # CancelledError (treats it as a network error and reconnects), and a
        # plain ``await sdk_task`` would forward our cancellation INTO the SDK
        # task — which then reconnects forever and this coroutine never wakes
        # (the exact mechanism that hung uvicorn's graceful shutdown). With
        # the shield, cancellation lands HERE and we can force the SDK exit.
        sdk_task = asyncio.create_task(self._sdk_client.start())
        try:
            await asyncio.shield(sdk_task)
        except asyncio.CancelledError:
            # Bounded force-shutdown; shield the cleanup task too so a
            # re-cancel can't abort it midway (it finishes detached).
            cleanup = asyncio.create_task(self._shutdown_sdk(sdk_task))
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.shield(cleanup)
            raise
        finally:
            self._connected = False

    async def _shutdown_sdk(self, sdk_task: asyncio.Task) -> None:
        """Force the SDK's reconnect loop to die (bounded, exception-safe).

        start() swallows one CancelledError per loop iteration, but its
        except-branches themselves ``await asyncio.sleep(...)`` — a second
        cancel lands inside that sleep, is NOT re-caught, and propagates
        out of start(). Close the websocket first so the recv side also
        unblocks. Only CancelledError is used on purpose: BaseExceptions
        (e.g. a KeyboardInterrupt poison) escape the task and kill the
        whole event loop.

        TODO(upgrade): the SDK's main branch (unreleased as of 0.24.3,
        the latest PyPI version) adds an official ``await client.stop()``
        built on an asyncio.Event stop signal — exactly this behavior,
        cooperatively. Once a release ships it, replace this method with
        ``await self._sdk_client.stop()`` and drop the re-cancel loop.
        """
        client = self._sdk_client
        ws = getattr(client, "websocket", None) if client is not None else None
        if ws is not None:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(ws.close(), timeout=3)
        for _ in range(3):
            if sdk_task.done():
                break
            sdk_task.cancel()
            await asyncio.wait({sdk_task}, timeout=1)
        if sdk_task.done() and not sdk_task.cancelled():
            # Retrieve & discard so "exception was never retrieved" doesn't
            # fire at GC; the SDK already logged it.
            with contextlib.suppress(BaseException):
                sdk_task.exception()  # type: ignore[arg-type]

    async def disconnect(self) -> None:
        """Close the live websocket and drop the SDK client.

        The task-level force-shutdown happens in connect()'s cancellation
        path; this covers the already-exited cases (belt and suspenders).
        """
        self._connected = False
        client = self._sdk_client
        if client is None:
            return
        ws = getattr(client, "websocket", None)
        if ws is not None:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(ws.close(), timeout=3)
        self._sdk_client = None

    # ── Credential access ──

    def _get_credential(self, key: str) -> str:
        encrypted = self.config.credentials.get(key)
        if not encrypted:
            raise InvalidCredentialsError(f"missing credential: {key}")
        return decrypt_secret(encrypted)


class _DingtalkMessageHandler(dingtalk_stream.CallbackHandler):
    """Chatbot message handler for the dingtalk Stream SDK.

    MUST subclass the SDK's ``CallbackHandler``: the stream client calls
    ``handler.pre_start()`` on every registered handler at startup and
    dispatches inbound messages via ``handler.raw_process()`` (which wraps
    our ``process()`` and builds the AckMessage envelope). A previous
    duck-typed version implementing only ``process`` crashed on each SDK
    entry point in turn — ``pre_start`` at connect time, ``raw_process``
    on the first inbound message. Inheriting the base class provides the
    full contract once and for all; only ``process`` is overridden.
    """

    TOPIC = "/v1.0/im/bot/messages/get"

    def __init__(self, owner: DingtalkConnectionClient) -> None:
        super().__init__()
        # SDK attaches dingtalk_client to handlers after registration
        # (CallbackHandler.__init__ sets it to None first).
        self.owner = owner

    async def process(self, callback):  # type: ignore[no-untyped-def]
        """SDK callback for each incoming chatbot message.

        ``callback`` is dingtalk_stream.CallbackMessage; its ``data`` field
        carries the inbound JSON. We forward it through dispatch_inbound
        using the same parser as webhook mode (parse_dingtalk_event).
        """
        # 无条件到达日志：不管后续解析/去重/执行结果如何，先记一笔。
        # 这是区分"平台没推"与"我们静默丢弃"的唯一可靠信号。
        # 只挑诊断相关字段——绝不打 sessionWebhook（含 ~2h 有效的回复
        # 令牌，进日志=任何读日志者可冒充机器人发消息）。
        data = getattr(callback, "data", None)
        preview = {
            k: data.get(k)
            for k in (
                "msgtype", "text", "msgId", "messageId",
                "conversationId", "conversationType",
                "senderNick", "senderStaffId", "senderPlatform",
            )
            if isinstance(data, dict) and data.get(k) is not None
        } if isinstance(data, dict) else {"raw": str(data)[:200]}
        logger.info(
            "dingtalk_message_received channel=%s topic=%s data=%s",
            self.owner.config.id,
            getattr(getattr(callback, "headers", None), "topic", "?"),
            preview,
        )
        try:
            body = self._extract_body(callback)
        except Exception as exc:
            logger.warning(
                "dingtalk_stream_extract_failed channel=%s err=%s",
                self.owner.config.id, exc,
            )
            return dingtalk_stream.AckMessage.STATUS_OK, "skipped"

        await dispatch_inbound(
            config=self.owner.config, body=body, parser=parse_dingtalk_event,
        )
        return dingtalk_stream.AckMessage.STATUS_OK, "OK"

    @staticmethod
    def _extract_body(callback) -> str:
        """Pull the inbound JSON out of the SDK's CallbackMessage.

        dingtalk's webhook receives a JSON body like:
          {"msgtype":"text","text":{"content":"..."}, "conversationId":"...",
           "senderStaffId":"...", "messageId":"...", ...}
        The stream SDK wraps this as callback.data (a dict). We re-serialize
        so parse_dingtalk_event (which takes a JSON string) can consume it.
        """
        data = getattr(callback, "data", None)
        if isinstance(data, dict):
            return json.dumps(data, ensure_ascii=False)
        if isinstance(data, (bytes, bytearray)):
            return data.decode("utf-8", errors="replace")
        if isinstance(data, str):
            return data
        # Fallback: build from common fields
        logger.warning("dingtalk_stream_unexpected_callback_data type=%s", type(data))
        return "{}"
