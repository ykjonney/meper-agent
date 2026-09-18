"""DingtalkConnectionClient + send-with-session-webhook unit tests."""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.channels.connections.manager import get_connection_manager
from app.channels.errors import InvalidCredentialsError
from app.core.crypto import encrypt_secret
from app.models.channel import ChannelConfig, ChannelProvider


def _make_dt_config(*, credentials: dict | None = None) -> ChannelConfig:
    if credentials is None:
        credentials = {
            "app_key": encrypt_secret("ding_app_key"),
            "app_secret": encrypt_secret("ding_app_secret"),
        }
    return ChannelConfig(
        id="ch_dt1", _id="ch_dt1",
        name="dingtalk-test", provider=ChannelProvider.DINGTALK,
        agent_id="agent_01J", owner_user_id="user_01J",
        webhook_secret="x" * 32, credentials=credentials,
        receive_mode="long_connection",
    )


class TestDingtalkFactoryRegistration:
    def test_factory_registered_on_import(self):
        import app.channels.providers  # noqa: F401
        mgr = get_connection_manager()
        assert mgr.supports("dingtalk")

    def test_factory_creates_dingtalk_connection_client(self):
        from app.channels.providers.dingtalk.connection import DingtalkConnectionClient
        mgr = get_connection_manager()
        factory = mgr._factories.get("dingtalk")
        assert factory is not None
        client = factory(_make_dt_config())
        assert isinstance(client, DingtalkConnectionClient)


class TestConnectMissingCredentials:
    async def test_connect_raises_on_missing_app_key(self):
        from app.channels.providers.dingtalk.connection import DingtalkConnectionClient

        config = _make_dt_config(credentials={})
        client = DingtalkConnectionClient(config)
        with pytest.raises(InvalidCredentialsError):
            await client.connect()


class TestSdkHandlerContract:
    """Regression guard for the SDK handler contract (startup + dispatch).

    The stream client calls ``handler.pre_start()`` on every registered
    handler at startup, and dispatches inbound messages via
    ``handler.raw_process()`` (stream.py: 'ack = await handler.raw_process(msg)'),
    which wraps our ``process()`` and builds the AckMessage envelope. The
    original duck-typed handler implemented only ``process`` and crashed on
    each SDK entry point in turn — AttributeError 'pre_start' at connect
    time (endless connection_failed retry loop), then AttributeError
    'raw_process' on the first inbound message. The handler now subclasses
    CallbackHandler; these tests pin the contract to the SDK's real paths.
    """

    def test_handler_subclasses_sdk_callback_handler(self):
        import dingtalk_stream
        from app.channels.providers.dingtalk.connection import (
            DingtalkConnectionClient,
            _DingtalkMessageHandler,
        )

        client = DingtalkConnectionClient(_make_dt_config())
        handler = _DingtalkMessageHandler(client)
        assert isinstance(handler, dingtalk_stream.CallbackHandler)

    def test_handler_survives_sdk_pre_start(self):
        import dingtalk_stream
        from app.channels.providers.dingtalk.connection import (
            DingtalkConnectionClient,
            _DingtalkMessageHandler,
        )

        client = DingtalkConnectionClient(_make_dt_config())
        handler = _DingtalkMessageHandler(client)

        # Wire the handler exactly like DingtalkConnectionClient.connect()
        # does, then run the SDK's own pre_start over the registered map —
        # the exact code path that crashed before the fix. Must not raise.
        sdk_client = dingtalk_stream.DingTalkStreamClient(
            dingtalk_stream.Credential("test_key", "test_secret")
        )
        sdk_client.register_callback_handler(handler.TOPIC, handler)
        sdk_client.pre_start()

    async def test_handler_survives_sdk_message_dispatch(self):
        """raw_process is the SDK's inbound entry point — must return a
        well-formed AckMessage, not AttributeError. Exercises the exact
        dispatch path that dropped the first real inbound message."""
        import dingtalk_stream
        from app.channels.providers.dingtalk.connection import (
            DingtalkConnectionClient,
            _DingtalkMessageHandler,
        )

        client = DingtalkConnectionClient(_make_dt_config())
        handler = _DingtalkMessageHandler(client)

        callback = MagicMock()
        callback.data = {
            "msgtype": "text",
            "text": {"content": "你好"},
            "conversationId": "cid001",
            "senderStaffId": "staff123",
            "messageId": "msg001",
        }
        callback.headers.message_id = "hdr_msg_1"

        with patch(
            "app.channels.providers.dingtalk.connection.dispatch_inbound",
            new=AsyncMock(return_value="inb_dt1"),
        ) as mock_dispatch:
            ack = await handler.raw_process(callback)

        assert isinstance(ack, dingtalk_stream.AckMessage)
        assert ack.code == dingtalk_stream.AckMessage.STATUS_OK
        mock_dispatch.assert_awaited_once()


class TestHandlerProcess:
    """The _DingtalkMessageHandler.process should extract body from callback
    and dispatch via dispatch_inbound."""

    async def test_process_extracts_dict_data_and_dispatches(self):
        from app.channels.providers.dingtalk.connection import (
            DingtalkConnectionClient,
            _DingtalkMessageHandler,
        )

        client = DingtalkConnectionClient(_make_dt_config())
        handler = _DingtalkMessageHandler(client)

        callback = MagicMock()
        callback.data = {
            "msgtype": "text",
            "text": {"content": "你好"},
            "conversationId": "cid001",
            "senderStaffId": "staff123",
            "messageId": "msg001",
            "session_webhook": "https://oapi.dingtalk.com/robot/sendBySession?xxx",
        }

        with patch(
            "app.channels.providers.dingtalk.connection.dispatch_inbound",
            new=AsyncMock(return_value="inb_dt1"),
        ) as mock_dispatch:
            result = await handler.process(callback)

        # dispatch was called with a JSON body string containing the payload
        mock_dispatch.assert_awaited_once()
        body_arg = mock_dispatch.call_args.kwargs["body"]
        assert isinstance(body_arg, str)
        parsed = json.loads(body_arg)
        assert parsed["messageId"] == "msg001"
        assert parsed["session_webhook"].startswith("https://")

        # Returns (STATUS_OK, "OK") tuple per dingtalk SDK contract.
        # STATUS_OK is the integer 200 in dingtalk_stream.AckMessage.
        assert result[0] == 200
        assert result[1] == "OK"

    async def test_process_handles_bytes_data(self):
        from app.channels.providers.dingtalk.connection import (
            DingtalkConnectionClient,
            _DingtalkMessageHandler,
        )

        client = DingtalkConnectionClient(_make_dt_config())
        handler = _DingtalkMessageHandler(client)
        callback = MagicMock()
        callback.data = b'{"msgtype":"text","text":{"content":"hi"}}'

        with patch(
            "app.channels.providers.dingtalk.connection.dispatch_inbound",
            new=AsyncMock(return_value=None),
        ):
            result = await handler.process(callback)
        assert result[0] == 200  # STATUS_OK

    async def test_process_swallows_extract_failure(self):
        """If body extraction fails, return OK-STATUS skipped (don't kill the stream)."""
        from app.channels.providers.dingtalk.connection import (
            DingtalkConnectionClient,
            _DingtalkMessageHandler,
        )

        client = DingtalkConnectionClient(_make_dt_config())
        handler = _DingtalkMessageHandler(client)
        callback = MagicMock()
        # Unusual type triggers fallback path
        callback.data = object()
        # __extract_body has a fallback that returns "{}" — won't raise,
        # dispatch_inbound gets "{}" and parse_dingtalk_event returns None
        with patch(
            "app.channels.providers.dingtalk.connection.dispatch_inbound",
            new=AsyncMock(return_value=None),
        ):
            result = await handler.process(callback)
        assert result[0] == 200  # STATUS_OK


class TestSendSessionWebhookPreference:
    """send should prefer session_webhook from the inbound context."""

    async def test_prefers_session_webhook_over_webhook_url(self):
        from app.channels.providers.dingtalk.client import send_text_message

        config = _make_dt_config(credentials={
            "app_key": encrypt_secret("k"),
            "app_secret": encrypt_secret("s"),
            "webhook_url": encrypt_secret("https://oapi.dingtalk.com/fallback"),
        })
        session_url = "https://oapi.dingtalk.com/session/xyz"

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_instance = mock_client_cls.return_value.__aenter__.return_value
            mock_instance.post = AsyncMock()
            mock_instance.post.return_value = MagicMock()
            mock_instance.post.return_value.json.return_value = {
                "errcode": 0, "messageId": "dt_reply_1",
            }
            mock_instance.post.return_value.raise_for_status = MagicMock()

            msg_id = await send_text_message(
                config=config, conversation_id="cid", text="hi",
                session_webhook=session_url,
            )

        # POST went to session_webhook, not fallback webhook_url
        mock_instance.post.assert_awaited_once()
        posted_url = mock_instance.post.call_args.args[0]
        assert posted_url == session_url
        assert msg_id == "dt_reply_1"

    async def test_falls_back_to_webhook_url_when_no_session(self):
        from app.channels.providers.dingtalk.client import send_text_message

        fallback = "https://oapi.dingtalk.com/fallback/abc"
        config = _make_dt_config(credentials={
            "app_key": encrypt_secret("k"),
            "app_secret": encrypt_secret("s"),
            "webhook_url": encrypt_secret(fallback),
        })

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_instance = mock_client_cls.return_value.__aenter__.return_value
            mock_instance.post = AsyncMock()
            mock_instance.post.return_value = MagicMock()
            mock_instance.post.return_value.json.return_value = {"errcode": 0}
            mock_instance.post.return_value.raise_for_status = MagicMock()

            await send_text_message(
                config=config, conversation_id="cid", text="hi",
                session_webhook=None,
            )

        posted_url = mock_instance.post.call_args.args[0]
        assert posted_url == fallback

    async def test_raises_when_no_session_and_no_webhook_url(self):
        from app.channels.providers.dingtalk.client import send_text_message

        # No session_webhook, no webhook_url credential
        config = _make_dt_config(credentials={
            "app_key": encrypt_secret("k"),
            "app_secret": encrypt_secret("s"),
        })
        with pytest.raises(InvalidCredentialsError):
            await send_text_message(
                config=config, conversation_id="cid", text="hi",
                session_webhook=None,
            )


class TestExtractSendContext:
    """ChannelService._extract_send_context should pull session_webhook from
    inbound.raw for dingtalk channels to use when replying."""

    def test_extracts_session_webhook_from_raw(self):
        from datetime import UTC, datetime

        from app.channels.base import InboundMessage
        from app.services.channel_service import _extract_send_context

        inbound = InboundMessage(
            channel_id="ch_dt", platform_chat_id="c", platform_user_id="u",
            message_id="m", text="hi",
            raw={"session_webhook": "https://oapi.dingtalk.com/sess/xyz",
                 "other_field": "ignored"},
            timestamp=datetime.now(UTC),
        )
        ctx = _extract_send_context(inbound)
        assert ctx == {"session_webhook": "https://oapi.dingtalk.com/sess/xyz"}

    def test_extracts_camelcase_session_webhook(self):
        """DingTalk webhook payloads use camelCase (sessionWebhook)."""
        from datetime import UTC, datetime

        from app.channels.base import InboundMessage
        from app.services.channel_service import _extract_send_context

        inbound = InboundMessage(
            channel_id="c", platform_chat_id="c", platform_user_id="u",
            message_id="m", text="x",
            raw={"sessionWebhook": "https://example.com/camel"},
            timestamp=datetime.now(UTC),
        )
        ctx = _extract_send_context(inbound)
        assert ctx == {"session_webhook": "https://example.com/camel"}

    def test_returns_empty_for_lark_payload(self):
        """Lark payloads don't have session_webhook → empty context."""
        from datetime import UTC, datetime

        from app.channels.base import InboundMessage
        from app.services.channel_service import _extract_send_context

        inbound = InboundMessage(
            channel_id="c", platform_chat_id="c", platform_user_id="u",
            message_id="m", text="x",
            raw={"header": {}, "event": {}},  # lark v2 envelope
            timestamp=datetime.now(UTC),
        )
        assert _extract_send_context(inbound) == {}


class _StubbornSDKClient:
    """Mimics the real SDK's start(): blocks on recv, swallows CancelledError,
    then reconnects via open_connection() — the exact behavior that used to
    make manager task.cancel() (and thus uvicorn reload) hang forever."""

    def __init__(self) -> None:
        self.closed = False
        self.reconnect_calls = 0
        self.exited = False
        self.websocket = MagicMock()

        async def _close() -> None:
            self.closed = True

        self.websocket.close = _close

    def register_callback_handler(self, topic, handler) -> None:  # noqa: ANN001
        pass

    def open_connection(self):  # noqa: ANN201
        self.reconnect_calls += 1
        return {"endpoint": "wss://stub", "ticket": "t"}

    async def start(self):  # noqa: ANN201
        try:
            while True:
                try:
                    # "recv loop": blocks until the websocket is closed
                    while not self.closed:
                        await asyncio.sleep(0.01)
                except asyncio.CancelledError:
                    pass  # the real SDK swallows this and reconnects
                self.open_connection()
                # Reconnect setup — the real SDK awaits websockets.connect()
                # here; a second cancel lands on this await and is NOT
                # re-caught by the inner except, so start() exits.
                await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            self.exited = True
            raise


class TestForcedShutdown:
    """Regression: dingtalk SDK start() swallows cancellation and reconnects,
    so stopping a channel hung graceful shutdown (zombie workers on every
    uvicorn reload). Cancellation must close the websocket and re-cancel the
    SDK task so start() actually returns."""

    async def test_cancellation_shuts_down_stubborn_sdk(self):
        from app.channels.providers.dingtalk.connection import (
            DingtalkConnectionClient,
        )

        client = DingtalkConnectionClient(_make_dt_config())
        stub = _StubbornSDKClient()
        with patch.object(
            DingtalkConnectionClient, "_get_credential",
            MagicMock(return_value="k"),
        ), patch("dingtalk_stream.Credential"), patch(
            "dingtalk_stream.DingTalkStreamClient", return_value=stub,
        ):
            task = asyncio.create_task(client.connect())
            await asyncio.sleep(0.05)  # let connect() reach the shielded await
            task.cancel()
            # asyncio.wait (NOT wait_for — awaiting a just-cancelled task
            # inside wait_for deadlocks on py3.12's asyncio.timeout). Before
            # the fix this stayed pending: the cancellation was forwarded
            # into the SDK task, which swallowed it and reconnected forever.
            done, pending = await asyncio.wait({task}, timeout=5)
            assert not pending, "cancellation must complete promptly"

        await asyncio.sleep(0.1)  # grace for the SDK task to wind down
        assert stub.closed is True  # websocket actually closed
        assert stub.exited is True  # SDK loop actually exited

    async def test_disconnect_poisons_reconnect_and_closes_ws(self):
        from app.channels.providers.dingtalk.connection import (
            DingtalkConnectionClient,
        )

        client = DingtalkConnectionClient(_make_dt_config())
        stub = _StubbornSDKClient()
        client._sdk_client = stub

        await client.disconnect()

        assert stub.closed is True  # websocket closed, not just state cleared
        assert client._sdk_client is None


class TestArrivalLogHygiene:
    """到达日志不得泄漏 sessionWebhook（~2h 有效的回复令牌）。"""

    async def test_arrival_log_excludes_session_webhook(self, caplog):
        import logging as _logging

        from app.channels.providers.dingtalk.connection import (
            DingtalkConnectionClient,
            _DingtalkMessageHandler,
        )

        client = DingtalkConnectionClient(_make_dt_config())
        handler = _DingtalkMessageHandler(client)
        callback = MagicMock()
        callback.headers.topic = "/v1.0/im/bot/messages/get"
        callback.data = {
            "msgtype": "text", "text": {"content": "hi"},
            "msgId": "m1", "conversationId": "c1",
            "sessionWebhook": "https://oapi.dingtalk.com/robot/sendBySession?session=SECRET",
        }

        with patch(
            "app.channels.providers.dingtalk.connection.dispatch_inbound",
            new=AsyncMock(return_value=None),
        ), caplog.at_level(_logging.INFO, logger="app.channels.providers.dingtalk.connection"):
            await handler.process(callback)

        joined = "\n".join(r.getMessage() for r in caplog.records)
        assert "dingtalk_message_received" in joined
        assert "SECRET" not in joined and "sessionWebhook" not in joined
        assert "m1" in joined  # 诊断字段仍在
