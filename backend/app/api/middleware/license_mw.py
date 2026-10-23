"""License gate middleware — 未激活/失效降级模式的业务 API 拦截。

行为：
- 未强制（源码轨/开发）→ 全放行。
- 拦截范围 = 业务 API 面（/api/、/ws/）——静态托管/根路径放行
  （页面无秘密，激活向导未激活必须可打开；业务数据全在 API 后面）。
- 强制且校验通过 → 放行；到期临近（≤7 天）补 ``X-License-Expiring`` 头。
- 强制且未激活/失效 → 业务 API 一律 403（统一错误信封，message 仅回
  错误码本身——明文文案由前端映射，二进制内不留字符串路标）。
- API 面白名单（未激活也要可用）：license 端点 / health / docs / 头像静态。
- 到期（LIC_E_EXPIRED）额外放行数据导出（``/api/v1/transfer/export``）——
  保留客户带走数据的通道，避免"挟持数据"纠纷；未激活不放行导出。
"""

from datetime import UTC, datetime

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core import license as lic

# 业务 API 面前缀——license 闸门只管这里。静态模式（FastAPI 托管前端）
# 下的页面/资源路径一律放行：页面无秘密，激活向导本身就要未激活可访问；
# Caddy 模式下非 API 路径也从不进 backend。
_API_PREFIXES = ("/api/", "/ws/")
# 前缀匹配即放行（含子路径）。
_ALWAYS_ALLOWED_PREFIXES = (
    "/api/v1/system/license",
    "/api/v1/health",
    "/api/v1/docs",
    "/api/v1/redoc",
    "/api/v1/openapi.json",
    "/api/v1/agent-avatars",
    "/api/v1/skill-avatars",
)
_EXPIRED_ALLOWED_PREFIXES = ("/api/v1/transfer/export",)


def _error_response(code: str, request_id: str) -> JSONResponse:
    return JSONResponse(
        status_code=403,
        content={
            "error": {
                "code": code,
                "message": code,  # 错误码即消息，文案由前端映射
                "details": {},
                "request_id": request_id,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        },
    )


class LicenseMiddleware(BaseHTTPMiddleware):
    """业务 API 的 license 闸门（未激活降级 / 到期停服 / 导出豁免）。"""

    async def dispatch(self, request: Request, call_next):
        status = lic.evaluate_license()
        if not status.enforced:
            return await call_next(request)

        path = request.url.path
        # 非 API 面（静态页面/资源/根路径）：放行。页面无秘密，激活向导
        # 必须未激活可打开；业务保护全部在 API 层。
        if not any(path.startswith(p) for p in _API_PREFIXES):
            return await call_next(request)

        if status.ok:
            response: Response = await call_next(request)
            if status.expiring_soon and status.expires_at is not None:
                # 到期临近标记：客户内部系统可据此提前感知。
                response.headers["X-License-Expiring"] = (
                    status.expires_at.isoformat()
                )
            return response

        if any(path.startswith(p) for p in _ALWAYS_ALLOWED_PREFIXES):
            return await call_next(request)
        if status.code == lic.LIC_E_EXPIRED and any(
            path.startswith(p) for p in _EXPIRED_ALLOWED_PREFIXES
        ):
            return await call_next(request)

        request_id = getattr(request.state, "request_id", "-")
        return _error_response(status.code, request_id)
