"""Lark (飞书) signature verification + payload parsing tests."""
import hashlib
import hmac
import time

import pytest

from app.channels.providers.lark.verify import (
    verify_lark_signature,
    parse_lark_event,
    LarkVerificationError,
    URL_CHALLENGE_MARKER,
)
from app.core.crypto import encrypt_secret
from app.models.channel import ChannelConfig, ChannelProvider

_APP_SECRET = "test_app_secret_value"
_VERIFY_TOKEN = "test_verify_token_value"


def _make_config(encrypt_key: str | None = None) -> ChannelConfig:
    return ChannelConfig(
        name="lark-test", provider=ChannelProvider.LARK,
        agent_id="a", owner_user_id="u",
        webhook_secret="lark_secondary_secret_16",
        credentials={
            "app_secret": encrypt_secret(_APP_SECRET),
            "verification_token": encrypt_secret(_VERIFY_TOKEN),
            **({"encrypt_key": encrypt_secret(encrypt_key)} if encrypt_key else {}),
        },
    )


def _sign(timestamp: str, body: str) -> str:
    msg = f"{timestamp}{body}".encode("utf-8")
    sig = hmac.new(_APP_SECRET.encode("utf-8"), msg, hashlib.sha256).hexdigest()
    return f"sha256={sig}"


class TestVerifyLarkSignature:
    def test_valid_signature_passes(self):
        body = '{"event":{"message":{"message_id":"om_1","content":"{\\"text\\":\\"hi\\"}"},"sender_id":{"open_id":"ou_1"},"chat_id":"oc_1"}}'
        ts = str(int(time.time()))
        sig = _sign(ts, body)
        verify_lark_signature(
            body=body, timestamp=ts, signature=sig, config=_make_config()
        )

    def test_invalid_signature_raises(self):
        body = '{"x":1}'
        ts = str(int(time.time()))
        with pytest.raises(LarkVerificationError):
            verify_lark_signature(
                body=body, timestamp=ts, signature="sha256=bad",
                config=_make_config(),
            )

    def test_stale_timestamp_raises(self):
        body = '{"x":1}'
        ts = str(int(time.time()) - 7200)  # 2h ago
        sig = _sign(ts, body)
        with pytest.raises(LarkVerificationError, match="timestamp"):
            verify_lark_signature(
                body=body, timestamp=ts, signature=sig, config=_make_config(),
            )

    def test_missing_app_secret_raises(self):
        cfg = ChannelConfig(
            name="bad", provider=ChannelProvider.LARK,
            agent_id="a", owner_user_id="u",
            webhook_secret="lark_secondary_secret_16",
            credentials={},
        )
        with pytest.raises(LarkVerificationError):
            verify_lark_signature(
                body="x", timestamp="1", signature="sha256=x", config=cfg,
            )


class TestParseLarkEvent:
    def test_url_verification_returns_challenge_marker(self):
        body = '{"challenge":"abc123","token":"%s"}' % _VERIFY_TOKEN
        result = parse_lark_event(body, _make_config())
        assert result == {URL_CHALLENGE_MARKER: "abc123"}

    def test_url_verification_wrong_token_raises(self):
        body = '{"challenge":"abc","token":"wrong"}'
        with pytest.raises(LarkVerificationError, match="token"):
            parse_lark_event(body, _make_config())

    def test_text_message_parsed(self):
        body = (
            '{"schema":"2.0","header":{"event_type":"im.message.receive_v1",'
            '"token":"%s"},"event":{"sender":{"sender_id":{"open_id":"ou_sender"}},'
            '"message":{"message_id":"om_001","chat_id":"oc_chat1",'
            '"message_type":"text","content":"{\\"text\\":\\"hello world\\"}"}}}'
        ) % _VERIFY_TOKEN
        msg = parse_lark_event(body, _make_config())
        assert msg is not None
        assert msg.message_id == "om_001"
        assert msg.platform_chat_id == "oc_chat1"
        assert msg.platform_user_id == "ou_sender"
        assert msg.text == "hello world"

    def test_non_text_message_returns_none(self):
        body = (
            '{"schema":"2.0","header":{"event_type":"im.message.receive_v1",'
            '"token":"%s"},"event":{"sender":{"sender_id":{"open_id":"ou_x"}},'
            '"message":{"message_id":"om_2","chat_id":"oc_c","message_type":"image",'
            '"content":"{}"}}}'
        ) % _VERIFY_TOKEN
        assert parse_lark_event(body, _make_config()) is None
