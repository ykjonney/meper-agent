"""External API — my app authorizations（终端用户自助授权）。

client 端自助授权入口，解决"未绑定用户到不了授权端点"的鸡生蛋问题：
- bootstrap / PUT 用 relaxed 鉴权（``auth_and_rate_limit_allow_unbound``）
  ——仍要求 API Key 有效 + introspection active，仅跳过「已绑定」检查。
- 首次绑定（身份不存在）双路径：自动开通 ext_user 账号（默认）或
  认领已有平台账号（claim 字段，复用平台登录校验防爆破）。
- username：所有应用自由填写，但 key 应用前端默认带出 introspection
  用户名；凭证一律经应用 login_url 真实验证，身份锚（ext_user_id）与
  登录名解耦，安全性对齐 studio 流程（login_url 验证 + sub 抢注保护）。
"""
from fastapi import APIRouter, Depends

from app.api.v1.ext import auth_and_rate_limit, auth_and_rate_limit_allow_unbound
from app.core.auth_apikey import ApiKeyPrincipal
from app.core.errors import (
    ForbiddenError,
    NotFoundError,
    UnauthorizedError,
    ValidationError,
)
from app.schemas.my_app_authorizations import (
    ExtAuthAppBrief,
    ExtAuthBootstrapResponse,
    ExtAuthorizeAppRequest,
    ExtAvailableAppResponse,
    ExtAvailableAppsResponse,
    MyAuthorizationsResponse,
)
from app.services.application_service import ApplicationService
from app.services.auth_service import AuthService
from app.services.user_mcp_credential_service import UserMcpCredentialService
from app.services.user_service import UserService

router = APIRouter(tags=["external-authorizations"])


async def _list_bindings_response(platform_user_id: str) -> MyAuthorizationsResponse:
    """脱敏绑定列表（复用 studio 侧的响应结构）。"""
    result = await UserMcpCredentialService.list_bindings(platform_user_id)
    applications = await ApplicationService.list_applications()
    app_map = {a["_id"]: a for a in applications}

    bindings = []
    app_bindings = (result or {}).get("app_bindings", {})
    for aid, b in app_bindings.items():
        app = app_map.get(aid, {})
        bindings.append({
            "app_id": aid,
            "app_name": app.get("name", ""),
            "username": b.get("username", ""),
            "password_masked": b.get("password", ""),
            "bound": True,
        })
    return MyAuthorizationsResponse(
        platform_user_id=platform_user_id,
        bindings=bindings,  # type: ignore[arg-type]
        updated_at=(result or {}).get("updated_at", ""),
    )


@router.get(
    "/my-app-authorizations/bootstrap",
    response_model=ExtAuthBootstrapResponse,
    summary="首绑门页引导信息（未绑定可访问）",
)
async def bootstrap_authorization(
    principal: ApiKeyPrincipal = Depends(auth_and_rate_limit_allow_unbound),
) -> ExtAuthBootstrapResponse:
    """返回 API Key 对应应用 + introspection 用户名 + 绑定状态。

    未绑定用户可访问（relaxed 鉴权），供首绑门页渲染表单：
    username 默认取 ext_username（前端可改，见 PUT 端点说明）。
    """
    application = await ApplicationService.get_application(principal.app_id)
    login_config = (application or {}).get("login_config") or {}

    bound = False
    if principal.user_id:
        binding = await UserMcpCredentialService.get_binding(
            principal.user_id, principal.app_id
        )
        bound = binding is not None

    return ExtAuthBootstrapResponse(
        app=ExtAuthAppBrief(
            id=principal.app_id,
            name=(application or {}).get("name", ""),
            has_login_config=bool(login_config.get("login_url")),
        ),
        ext_username=principal.ext_username or "",
        bound=bound,
    )


@router.get(
    "/my-app-authorizations/available-apps",
    response_model=ExtAvailableAppsResponse,
    summary="可授权应用列表",
)
async def list_available_apps(
    principal: ApiKeyPrincipal = Depends(auth_and_rate_limit),
) -> ExtAvailableAppsResponse:
    """列出可授权应用（配置了 login_url 的），标记 key 对应应用。

    前端授权面板据此渲染应用选择；key 应用的 username 需锁定为
    introspection 用户名（防冒名）。
    """
    applications = await ApplicationService.list_applications()
    items: list[ExtAvailableAppResponse] = []
    for a in applications:
        login_config = a.get("login_config") or {}
        if not login_config.get("login_url"):
            continue
        items.append(ExtAvailableAppResponse(
            id=a["_id"],
            name=a.get("name", ""),
            description=a.get("description", ""),
            mcp_count=len(a.get("mcp_connection_ids") or []),
            is_key_app=a["_id"] == principal.app_id,
        ))
    return ExtAvailableAppsResponse(key_app_id=principal.app_id, items=items)


@router.put(
    "/my-app-authorizations/{app_id}",
    response_model=MyAuthorizationsResponse,
    summary="授权应用（绑定账密，未绑定可访问）",
)
async def authorize_app(
    app_id: str,
    body: ExtAuthorizeAppRequest,
    principal: ApiKeyPrincipal = Depends(auth_and_rate_limit_allow_unbound),
) -> MyAuthorizationsResponse:
    """授权某应用：绑定/更新账密。

    安全规则：
    - username 所有应用均可改（key 应用前端默认带出 introspection
      用户名）；凭证经应用 login_url 真实验证，持有有效账密即视为
      有权使用该账号，且身份锚与登录名解耦（改名/换账号不影响映射）。
    - 认领（claim 字段）仅在首次绑定 key 应用时可用——已有平台身份后
      认领会把凭证挂到别的账号、运行时查不到（禁止）。
    - 跨应用绑定要求已有平台身份（先完成 key 应用首绑）。
    """
    application = await ApplicationService.get_application(app_id)
    if application is None:
        raise NotFoundError(
            code="APPLICATION_NOT_FOUND",
            message=f"应用 {app_id} 不存在",
        )
    login_config = application.get("login_config") or {}
    if not login_config.get("login_url"):
        raise ValidationError(
            code="APPLICATION_NO_LOGIN_CONFIG",
            message=f"应用「{application.get('name', app_id)}」未配置登录端点",
        )

    is_key_app = app_id == principal.app_id
    # key 应用 username 不再强制等于 introspection 用户名——前端默认带出
    # ext_username 但允许修改（登录名可能与 introspection 返回值不同的场景）。
    # 凭证仍须经应用 login_url 真实校验；身份锚是 ext_user_id（与登录名解耦），
    # 改用户名不影响身份映射与解绑。

    # 认领字段必须成对出现
    claim_user = body.claim_platform_username
    claim_pass = body.claim_platform_password
    if bool(claim_user) != bool(claim_pass):
        raise ValidationError(
            code="CLAIM_FIELDS_INCOMPLETE",
            message="认领平台账号需同时提供账号与密码",
        )

    # 解析目标平台账号
    if claim_user:
        if principal.user_id:
            raise ForbiddenError(
                code="EXT_CLAIM_NOT_ALLOWED",
                message="已有平台身份，无需认领账号",
            )
        if not is_key_app:
            raise ForbiddenError(
                code="EXT_CLAIM_NOT_ALLOWED",
                message="认领仅支持首次绑定当前应用时使用",
            )
        # 复用平台登录校验（锁定检查/失败计数/停用拒绝），只验不发 token。
        # 401 会被 client 的 apikey 401 处理器误判为身份失效弹回错误页，
        # 故映射为 422 业务错误（文案保留锁定剩余时间提示）。
        try:
            platform_user_id = await AuthService.verify_platform_credentials(
                claim_user, claim_pass or ""
            )
        except UnauthorizedError as exc:
            raise ValidationError(
                code="PLATFORM_CREDENTIAL_INVALID",
                message=f"认领失败：{exc.message}",
            ) from exc
    elif principal.user_id:
        platform_user_id = principal.user_id
    else:
        if not is_key_app:
            raise ForbiddenError(
                code="EXT_IDENTITY_REQUIRED",
                message="请先完成当前应用的授权，再绑定其他应用",
            )
        platform_user_id = await UserService.ensure_ext_platform_user(
            app_id, principal.ext_user_id or body.username
        )

    # 身份锚点 v4.2：key 应用用 introspection 稳定 ID（改名不漂移）；
    # 跨应用不传（空）——由 bind_credential 从登录响应提取稳定用户 ID
    # （userid_jsonpath，默认 userId），提取不到退回登录名
    identity_key = (principal.ext_user_id or "") if is_key_app else ""

    try:
        await UserMcpCredentialService.bind_credential(
            platform_user_id=platform_user_id,
            app_id=app_id,
            username=body.username,
            password=body.password,
            login_config=login_config,
            identity_key=identity_key,
        )
    except PermissionError as exc:
        raise ValidationError(
            code="MCP_CREDENTIAL_INVALID",
            message=str(exc),
        ) from exc

    return await _list_bindings_response(platform_user_id)


@router.get(
    "/my-app-authorizations",
    response_model=MyAuthorizationsResponse,
    summary="查看我的应用授权",
)
async def read_my_authorizations(
    principal: ApiKeyPrincipal = Depends(auth_and_rate_limit),
) -> MyAuthorizationsResponse:
    """查看当前终端用户的授权列表（凭证脱敏）。"""
    return await _list_bindings_response(principal.user_id or "")


@router.delete(
    "/my-app-authorizations/{app_id}",
    response_model=MyAuthorizationsResponse,
    summary="取消授权",
)
async def revoke_app(
    app_id: str,
    principal: ApiKeyPrincipal = Depends(auth_and_rate_limit),
) -> MyAuthorizationsResponse:
    """取消某应用的授权（解绑凭证 + 删身份映射）。

    注意：解绑 key 对应应用会删除身份映射，下次请求将回到首绑门页。
    """
    await UserMcpCredentialService.unbind_credential(
        platform_user_id=principal.user_id or "",
        app_id=app_id,
    )
    return await _list_bindings_response(principal.user_id or "")
