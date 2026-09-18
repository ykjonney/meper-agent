"""DingTalk (钉钉) signature verification + parsing tests."""
import base64
import hashlib
import hmac
import json
import time

import pytest
from app.channels.providers.dingtalk.verify import (
    DingtalkVerificationError,
    parse_dingtalk_event,
    verify_dingtalk_signature,
)
from app.core.crypto import encrypt_secret
from app.models.channel import ChannelConfig, ChannelProvider

_APP_SECRET = "test_dingtalk_secret"


def _make_config() -> ChannelConfig:
    return ChannelConfig(
        name="dingtalk-test", provider=ChannelProvider.DINGTALK,
        agent_id="a", owner_user_id="u",
        webhook_secret="dingtalk_secondary_16+",
        credentials={"app_secret": encrypt_secret(_APP_SECRET)},
    )


def _sign(timestamp: str) -> str:
    """DingTalk sign = Base64(HMAC-SHA256(secret, f'{timestamp}\n{secret}'))."""
    string_to_sign = f"{timestamp}\n{_APP_SECRET}"
    digest = hmac.new(
        _APP_SECRET.encode("utf-8"),
        string_to_sign.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return base64.b64encode(digest).decode("utf-8")


class TestVerifyDingtalkSignature:
    def test_valid_signature_passes(self):
        ts = str(int(time.time()))
        verify_dingtalk_signature(
            timestamp=ts, sign=_sign(ts), config=_make_config()
        )

    def test_invalid_signature_raises(self):
        ts = str(int(time.time()))
        with pytest.raises(DingtalkVerificationError):
            verify_dingtalk_signature(
                timestamp=ts, sign="bad_signature", config=_make_config()
            )

    def test_stale_timestamp_raises(self):
        ts = str(int(time.time()) - 7200)
        with pytest.raises(DingtalkVerificationError, match="timestamp"):
            verify_dingtalk_signature(
                timestamp=ts, sign=_sign(ts), config=_make_config()
            )


class TestParseDingtalkEvent:
    def test_text_message_parsed(self):
        body = (
            '{"msgtype":"text","text":{"content":"你好"},"conversationId":"cid001",'
            '"senderStaffId":"staff123","messageId":"msg001"}'
        )
        msg = parse_dingtalk_event(body, _make_config())
        assert msg is not None
        assert msg.message_id == "msg001"
        assert msg.platform_chat_id == "cid001"
        assert msg.platform_user_id == "staff123"
        assert msg.text == "你好"

    def test_non_text_message_returns_none(self):
        body = '{"msgtype":"markdown","text":{}}'
        assert parse_dingtalk_event(body, _make_config()) is None

    def test_empty_content_returns_none(self):
        body = '{"msgtype":"text","text":{"content":""}}'
        assert parse_dingtalk_event(body, _make_config()) is None

    def test_encrypted_body_raises_not_implemented(self):
        """First iteration: encrypted callbacks not yet supported."""
        body = '{"encrypt":"some_base64_data"}'
        with pytest.raises(DingtalkVerificationError, match="encrypt"):
            parse_dingtalk_event(body, _make_config())


class TestStreamMsgIdField:
    """Regression: Stream 模式载荷的字段是 msgId（非 webhook 的 messageId）。
    此前只读 messageId → message_id 恒空串 → 去重键 (channel_id, "") 使
    每渠道只有第一条消息通过、其余被幂等去重静默丢弃（"只回第一条"）。"""

    def test_stream_msgid_extracted(self):
        from app.channels.providers.dingtalk.verify import parse_dingtalk_event

        cfg = ChannelConfig(
            name="t", provider=ChannelProvider.DINGTALK,
            agent_id="a", owner_user_id="u",
            webhook_secret="x" * 16,
        )
        body = json.dumps({
            "msgtype": "text",
            "text": {"content": "测试"},
            "conversationId": "cid_1",
            "senderStaffId": "staff_1",
            "msgId": "msgtLCdEToVbLJ2AMoFMe4TQg==",   # Stream 真实字段
        })
        inbound = parse_dingtalk_event(body, cfg)
        assert inbound is not None
        assert inbound.message_id == "msgtLCdEToVbLJ2AMoFMe4TQg=="

    def test_distinct_stream_messages_no_longer_collide_on_empty_id(self):
        """两条不同的流消息必须得到不同的 message_id（修复前均为空串）。"""
        from app.channels.providers.dingtalk.verify import parse_dingtalk_event

        cfg = ChannelConfig(
            name="t", provider=ChannelProvider.DINGTALK,
            agent_id="a", owner_user_id="u",
            webhook_secret="x" * 16,
        )
        ids = set()
        for i in range(2):
            body = json.dumps({
                "msgtype": "text", "text": {"content": f"m{i}"},
                "conversationId": "cid_1", "senderStaffId": "s",
                "msgId": f"msg_{i}",
            })
            inbound = parse_dingtalk_event(body, cfg)
            ids.add(inbound.message_id)
        assert len(ids) == 2

    def test_missing_id_skips_instead_of_poisoning_dedup(self):
        """两个 ID 字段都缺 → 跳过（返回 None），绝不让空串污染去重键。"""
        from app.channels.providers.dingtalk.verify import parse_dingtalk_event

        cfg = ChannelConfig(
            name="t", provider=ChannelProvider.DINGTALK,
            agent_id="a", owner_user_id="u",
            webhook_secret="x" * 16,
        )
        body = json.dumps({
            "msgtype": "text", "text": {"content": "无ID消息"},
            "conversationId": "cid_1", "senderStaffId": "s",
        })
        assert parse_dingtalk_event(body, cfg) is None
