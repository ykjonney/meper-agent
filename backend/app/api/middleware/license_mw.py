"""License gate middleware — 未激活/失效降级模式的业务 API 拦截。

行为：
- 未强制（源码轨/开发）→ 全放行。
- 拦截范围 = 业务 API 面（/api/、/ws/）——静态托管/根路径放行
  （页面无秘密，激活向导未激活必须可打开；业务数据全在 API 后面）。
- 强制且校验通过 → 放行；到期临近（≤7 天）补 ``X-License-Expiring`` 头。
- 强制且未激活/失效 → 业务 API 一律 403（统一错误信封，message 仅回
  错误码本身——明文文案由前端映射，二进制内不留字符串路标）。
- API 面白名单（未激活也要可用）：license 端点 / health / 头像静态。
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
# 前缀匹配即放行（含子路径）。docs/redoc/openapi 不在白名单：生产构建
# 它们已被 main.py 按 APP_ENV 关闭；此处不放行保证"万一未来有人重开
# docs，未激活降级态同样进不去"（fail closed）。
_ALWAYS_ALLOWED_PREFIXES = (
    "/api/v1/system/license",
    "/api/v1/health",
    "/api/v1/agent-avatars",
    "/api/v1/skill-avatars",
)
_EXPIRED_ALLOWED_PREFIXES = ("/api/v1/transfer/export",)

# 构建期由 scripts/build_compiled.py 注入（安全报告修复 1+2）：
# - _BUILT_LICENSE_SHA256：app.core.license 产物（strip 后）的 sha256。
# - _BUILT_LICENSE_ENFORCED：构建期强制真值（"True"/"False"）。判定输入
#   不来自任何 import——meta_path 拦截只能替换被导入的模块对象，改不了
#   本模块自带的常量，报告路径 3（拦截 build_flags 翻转总开关）由此失效。
# 源码轨保持占位符——占位符 = 未注入 = 不强制。
_BUILT_LICENSE_SHA256 = "__LICENSE_SO_SHA256__"
_BUILT_LICENSE_ENFORCED = "__LICENSE_ENFORCED__"


def _build_enforced() -> bool:
    """构建期强制真值（占位符字符串按"未注入 = 不强制"处理）。"""
    return _BUILT_LICENSE_ENFORCED == "True"


def _license_module_intact() -> bool:
    """license 模块完整性自检：必须是构建期登记的编译产物。

    三层，缺一即 fail closed：
    1. 构建期内联真值判强制——拦截 build_flags 无法关闭本检查；
    2. 物理定位产物文件：以本模块 ``__file__`` 为锚点向上找 ``app/core/``，
       不走 import 系统——``importlib.util.find_spec`` 对已加载模块返回
       ``sys.modules[name].__spec__``，被替换的假模块可伪造 origin 指向
       真 .so 骗过校验（报告进阶路径 2）；
    3. ``sys.modules`` 一致性：已加载的 app.core.license 的
       ``__spec__.origin`` 必须解析到同一物理文件——假模块 origin 缺失
       或乱指在此暴露。
    """
    if not _build_enforced():
        return True  # dev 源码轨：不强制不校验
    import hashlib
    import sys
    from pathlib import Path

    expected = _BUILT_LICENSE_SHA256
    if expected.startswith("__"):
        return False  # 占位符未注入（源码轨误配强制模式）

    # 2. 物理定位（本模块未被替换时 __file__ 不可伪造）
    core_dir: Path | None = None
    for anc in Path(__file__).resolve().parents:
        if anc.name == "app" and (anc / "core").is_dir():
            core_dir = anc / "core"
            break
    if core_dir is None:
        return False

    physical: Path | None = None
    candidates = [
        *sorted(core_dir.glob("license.*.so")),
        *sorted(core_dir.glob("license.*.pyc")),
        *sorted((core_dir / "__pycache__").glob("license.*.pyc")),
    ]
    for cand in candidates:
        try:
            if hashlib.sha256(cand.read_bytes()).hexdigest() == expected:
                physical = cand.resolve()
                break
        except OSError:
            continue
    if physical is None:
        return False  # 无匹配哈希的编译产物（.py 替换 / 篡改 / 缺失）

    # 3. 内存模块与物理文件一致性
    mod = sys.modules.get("app.core.license")
    origin = getattr(getattr(mod, "__spec__", None), "origin", None)
    if not origin:
        return False
    try:
        return Path(origin).resolve() == physical
    except OSError:
        return False


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
        build_enforced = _build_enforced()
        path = request.url.path

        # 非 API 面（静态页面/资源/根路径）：放行。页面无秘密，激活向导
        # 必须未激活可打开；业务保护全部在 API 层。
        if not any(path.startswith(p) for p in _API_PREFIXES):
            return await call_next(request)

        # 矛盾检测（安全报告修复 2）：构建期强制而 license 模块谎报
        # 不强制——模块被替换/欺骗的直接证据。license 端点仍放行
        # （激活向导是管理员恢复的唯一通道）。
        if build_enforced and not status.enforced:
            if any(path.startswith(p) for p in _ALWAYS_ALLOWED_PREFIXES):
                return await call_next(request)
            request_id = getattr(request.state, "request_id", "-")
            return _error_response("LIC_E_INTEGRITY", request_id)

        # 双不强制（dev 源码轨 / dev 构建）→ 全放行。status.enforced 参与
        # 判定：LICENSE_ENFORCE_EXTRA（env 加强）在非强制构建上仍生效。
        if not (build_enforced or status.enforced):
            return await call_next(request)

        # 完整性链：license 模块文件被替换时在此独立发现（每请求微秒级
        # sha256）。错误码字面量内联——不 import 被质疑的模块。license
        # 端点仍放行（激活向导是管理员恢复的唯一通道）。
        if not _license_module_intact():
            if any(path.startswith(p) for p in _ALWAYS_ALLOWED_PREFIXES):
                return await call_next(request)
            request_id = getattr(request.state, "request_id", "-")
            return _error_response("LIC_E_INTEGRITY", request_id)

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
