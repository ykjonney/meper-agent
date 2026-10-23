"""System endpoints — offline license activation surface.

无鉴权说明：status/request 只暴露指纹（激活功能本身要显示）与非敏感
授权摘要；install 的防线是 RSA-SHA256 验签——没有厂商私钥签不出能通过
校验的 license，因此无需登录态守卫（未激活时也常常还没有账号）。
"""

from datetime import datetime

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.core import license as lic
from app.core.errors import AppError

router = APIRouter(prefix="/system", tags=["system"])


class LicenseStatusOut(BaseModel):
    activated: bool
    enforced: bool
    dev_mode: bool
    code: str
    fingerprint: str
    licensee: str | None = None
    edition: str | None = None
    license_id: str | None = None
    expires_at: datetime | None = None
    days_left: int | None = None
    expiring_soon: bool = False


def _to_out(status: lic.LicenseStatus) -> LicenseStatusOut:
    payload = status.payload
    return LicenseStatusOut(
        activated=status.ok,
        enforced=status.enforced,
        dev_mode=not status.enforced,
        code=status.code,
        fingerprint=status.fingerprint,
        licensee=payload.licensee if payload else None,
        edition=payload.edition if payload else None,
        license_id=payload.license_id if payload else None,
        expires_at=status.expires_at,
        days_left=status.days_left,
        expiring_soon=status.expiring_soon,
    )


@router.get("/license/status", summary="License 状态（激活向导/警告条数据源）")
async def license_status() -> LicenseStatusOut:
    return _to_out(lic.evaluate_license())


@router.post(
    "/license/install",
    summary="装入 license.key（校验通过后原子落盘并热放行）",
)
async def license_install(request: Request) -> LicenseStatusOut:
    # license.key 原文（text/plain，一行 base64.payload.sig）——裸 str 参数
    # 会被 FastAPI 解释为 query，故直接读 body。
    content = (await request.body()).decode("utf-8", errors="strict")
    status = lic.install_license(content)
    if not status.ok:
        # 校验失败：不落盘，400 + 错误码（前端映射文案）。
        raise AppError(code=status.code, message=status.code, status_code=400)
    return _to_out(status)


@router.get("/license/request", summary="授权申请文件（客户回传厂商签发）")
async def license_request() -> JSONResponse:
    info = lic.license_request_info()
    return JSONResponse(
        content=info,
        headers={
            # 向导端触发浏览器下载为 .json 文件。
            "Content-Disposition": 'attachment; filename="license-request.json"'
        },
    )
