"""My app authorizations schemas — user self-service authorization API."""
from __future__ import annotations

from pydantic import BaseModel, Field


class AuthorizeAppRequest(BaseModel):
    """授权应用：绑定账密。"""

    username: str = Field(..., min_length=1, max_length=100, description="用户名")
    password: str = Field(..., min_length=1, max_length=200, description="密码")


class AppBindingResponse(BaseModel):
    """单个应用的授权状态（凭证脱敏）。"""

    app_id: str
    app_name: str = ""
    username: str = ""
    password_masked: str = ""
    bound: bool = False


class MyAuthorizationsResponse(BaseModel):
    """当前用户的全部应用授权。"""

    platform_user_id: str
    bindings: list[AppBindingResponse] = Field(default_factory=list)
    updated_at: str = ""


class AvailableAppResponse(BaseModel):
    """可授权的应用。"""

    id: str
    name: str
    description: str = ""
    mcp_count: int = 0


class AvailableAppsResponse(BaseModel):
    """可授权的应用列表。"""

    items: list[AvailableAppResponse]


# ---------------------------------------------------------------------------
# Ext（client 自助授权）专用 schemas
# ---------------------------------------------------------------------------


class ExtAuthorizeAppRequest(AuthorizeAppRequest):
    """client 授权应用：绑定账密（ext 端点用）。

    认领字段二选一填写：提供 claim_platform_username/password 时走
    「认领已有平台账号」路径（验证平台账密所有权），否则走自动开通。
    """

    claim_platform_username: str | None = Field(
        default=None, max_length=100, description="认领的平台账号用户名"
    )
    claim_platform_password: str | None = Field(
        default=None, max_length=200, description="认领的平台账号密码"
    )


class ExtAuthAppBrief(BaseModel):
    """首绑门页展示的应用信息。"""

    id: str
    name: str = ""
    has_login_config: bool = False


class ExtAuthBootstrapResponse(BaseModel):
    """首绑门页引导信息：当前 API Key 对应应用 + 外部用户名 + 绑定状态。"""

    app: ExtAuthAppBrief
    ext_username: str = ""
    bound: bool = False


class ExtAvailableAppResponse(AvailableAppResponse):
    """可授权应用（ext 侧），标记是否为 API Key 对应应用。"""

    is_key_app: bool = False


class ExtAvailableAppsResponse(BaseModel):
    """可授权应用列表（ext 侧）。"""

    key_app_id: str
    items: list[ExtAvailableAppResponse]
