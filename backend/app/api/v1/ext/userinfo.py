"""External API — user info（终端用户 token 验证 + 返回用户名）。

供 chat-widget.js 在宿主页面验证用户输入的通用 token 并获取用户名。
鉴权：API Key（接入方凭证）+ X-User-Token（introspection 回调校验）。
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.v1.ext import auth_and_rate_limit
from app.core.auth_apikey import ApiKeyPrincipal
from app.services.external_identity_service import ExternalIdentityService
from app.services.user_mcp_credential_service import UserMcpCredentialService

router = APIRouter(tags=["external-userinfo"])


class ExtUserInfoResponse(BaseModel):
    """终端用户信息（给 widget 显示用户名用）。"""
    name: str
    binding_count: int = 0


@router.get(
    "/userinfo",
    response_model=ExtUserInfoResponse,
    summary="Verify user token & return name",
)
async def get_user_info(
    principal: ApiKeyPrincipal = Depends(auth_and_rate_limit),
) -> ExtUserInfoResponse:
    """验证终端用户 token，返回用户名和应用绑定数。

    chat-widget.js 在宿主页面调用此接口验证用户输入的 token。
    principal.user_id = platform_user_id（v4：external_identities 反查所得）。
    显示名优先取 principal.ext_username（introspection 的 username，
    人类可读，鉴权链保证非空）；identity.sub 里的锚 v4.2 起是稳定
    用户 ID（可能是 754113802395538714 这类数字 ID，不可读），仅作
    无 ext_username 时的回退；绑定数取 app_bindings 数量。
    """
    identities = await ExternalIdentityService.list_by_platform_user(principal.user_id or "")
    name = principal.ext_username or ""
    if not name:
        for identity in identities:
            # sub = {app_id}:{稳定用户ID}（老数据可能是登录名）
            username = (identity.get("sub") or "").split(":", 1)[-1]
            if username:
                name = username
                break
    if not name:
        name = "用户"

    binding_count = 0
    bindings = await UserMcpCredentialService.list_bindings(principal.user_id or "")
    if bindings:
        binding_count = len(bindings.get("app_bindings") or {})

    return ExtUserInfoResponse(name=name, binding_count=binding_count)
