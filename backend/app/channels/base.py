"""Channel abstract interface + standardized message types.

Adapters implement Channel to translate between a specific IM platform's
protocol and these normalized shapes. Everything downstream of the adapter
deals only with InboundMessage / OutboundEnvelope.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import ClassVar

from fastapi import Request
from pydantic import BaseModel, Field

from app.models.channel import ChannelConfig


class InboundMessage(BaseModel):
    """Normalized inbound message produced by an adapter's verify_inbound.

    Downstream services (ChannelService, AgentExecutionService) consume this
    and never see the raw platform payload.
    """
    channel_id: str
    platform_chat_id: str         # chat/group/open_id this conversation lives in
    platform_user_id: str         # sender identity within the platform
    platform_user_name: str | None = None
    message_id: str               # platform message id (idempotency key)
    text: str = Field(..., min_length=1)
    raw: dict                     # original payload (audit/debug/future rich format)
    timestamp: datetime


class OutboundEnvelope(BaseModel):
    """Normalized outbound message. ChannelService produces this; the adapter's
    send() translates it into a platform API call."""
    channel_id: str
    platform_chat_id: str
    text: str
    reply_to_message_id: str | None = None


class Channel(ABC):
    """IM platform adapter interface. Add a platform by:
      1. Create app/channels/providers/<name>/ with channel.py / verify.py / client.py
      2. Subclass Channel, decorate with @ChannelRegistry.register("<name>")
      3. Add an import line in app/channels/providers/__init__.py

    Adapters MUST be stateless — config is passed per-call so one class can
    serve multiple ChannelConfig instances safely.
    """
    provider: ClassVar[str]

    @abstractmethod
    def verify_inbound(
        self, request: Request, config: ChannelConfig
    ) -> InboundMessage | None:
        """Verify signature + parse HTTP callback.

        Returns:
            InboundMessage: verified, proceed with processing.
            None: special-case ack (e.g. Lark URL verification challenge) —
                  caller should return the adapter-specific ack response and
                  skip downstream processing.
        Raises:
            ChannelError / AuthError: verification failed, reject the callback.
        """

    @abstractmethod
    def send(self, envelope: OutboundEnvelope, config: ChannelConfig) -> str:
        """Call platform OpenAPI to send a message. Returns platform message id.

        Raises TransientChannelError on retryable failures, PermanentChannelError
        (e.g. InvalidCredentialsError / SendFailedError) otherwise.
        """

    def normalize_event(
        self, event: dict, config: ChannelConfig
    ) -> InboundMessage:
        """Optional: parse a long-connection (WebSocket) event into InboundMessage.
        HTTP-callback adapters don't need to implement this."""
        raise NotImplementedError(
            f"{self.provider} does not implement long-connection mode"
        )
