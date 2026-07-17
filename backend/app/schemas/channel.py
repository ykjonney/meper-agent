"""Channel API request/response schemas + provider credential schema."""
from __future__ import annotations

from pydantic import BaseModel, Field

from app.models.channel import ChannelProvider


class CredentialField(BaseModel):
    key: str
    label: str
    type: str = "text"        # "text" | "secret"
    required: bool = True


class ProviderSchema(BaseModel):
    label: str
    credential_fields: list[CredentialField]


class ChannelCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    provider: ChannelProvider
    agent_id: str
    credentials: dict = Field(default_factory=dict)


class ChannelUpdateRequest(BaseModel):
    name: str | None = None
    agent_id: str | None = None
    credentials: dict | None = None
    enabled: bool | None = None


class ChannelResponse(BaseModel):
    id: str
    name: str
    provider: ChannelProvider
    agent_id: str
    owner_user_id: str
    enabled: bool
    status: str
    receive_mode: str
    credentials: dict   # always masked
    inbound_url: str
    created_at: str
    updated_at: str


class ChannelListResponse(BaseModel):
    items: list[ChannelResponse]
    total: int
    page: int
    page_size: int


class ProviderSchemaResponse(BaseModel):
    providers: dict[str, ProviderSchema]


PROVIDER_SCHEMAS: dict[str, ProviderSchema] = {
    ChannelProvider.LARK: ProviderSchema(
        label="飞书",
        credential_fields=[
            CredentialField(key="app_id", label="App ID"),
            CredentialField(key="app_secret", label="App Secret", type="secret"),
            CredentialField(key="verification_token", label="Verification Token", type="secret"),
            CredentialField(key="encrypt_key", label="Encrypt Key", type="secret", required=False),
        ],
    ),
    ChannelProvider.DINGTALK: ProviderSchema(
        label="钉钉",
        credential_fields=[
            CredentialField(key="app_key", label="App Key"),
            CredentialField(key="app_secret", label="App Secret", type="secret"),
            CredentialField(key="webhook_url", label="Group Robot Webhook URL", type="secret"),
        ],
    ),
    ChannelProvider.WECOM: ProviderSchema(
        label="企业微信",
        credential_fields=[
            CredentialField(key="corp_id", label="Corp ID"),
            CredentialField(key="agent_id", label="Agent ID"),
            CredentialField(key="secret", label="Secret", type="secret"),
            CredentialField(key="token", label="Token", type="secret"),
            CredentialField(key="encoding_aes_key", label="EncodingAESKey", type="secret"),
        ],
    ),
    ChannelProvider.MOCK: ProviderSchema(
        label="Mock (测试)",
        credential_fields=[],
    ),
}
