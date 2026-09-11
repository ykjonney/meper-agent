"""组织工具库 REST API（ToB 治理模型：「工具库 / 我创建的」）。

治理流程：tool:write 用户创建 → submit → admin 审查（approve→published）
→ admin 配置凭证（org_user_args，sensitive 加密）→ admin 开启
（校验 published + 定义完整 + 凭证完整）→ Agent 绑定 / 工作流直调。

- GET  /user-tools/enabled     可用工具全集（Agent 绑定/工作流节点候选）
- GET  /user-tools/marketplace 组织工具库目录（浏览 + 治理状态；无安装语义）
- POST /user-tools             创建（tool:write）
- GET/PUT/DELETE /user-tools/{id}   详情 / 编辑（owner|admin）/ 删除
- POST /user-tools/{id}/submit 提交发布审查（owner）
- GET/POST /user-tools/admin/review   管理员审核台
- PUT  /user-tools/{id}/args   配置工具级凭证（admin）
- POST /user-tools/{id}/enable 开启/停用（admin，三重校验）
- POST /user-tools/{id}/fork   复制已发布工具为自己的草稿
- POST /user-tools/{id}/vote   目录投票（组织内反馈信号）
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.core.errors import NotFoundError, ValidationError
from app.core.security import get_current_user, require_any_role, require_permission
from app.schemas.user import UserResponse
from app.services.user_tool_service import UserToolError, UserToolService

router = APIRouter(prefix="/user-tools", tags=["user-tools"])


class ToolDefinition(BaseModel):
    """工具定义本体（创建/编辑共用）。"""

    name: str = Field(..., description="工具名（组织内唯一）")
    description: str = Field(default="", max_length=500)
    source: str = Field(..., description="openapi | code")
    user_args_schema: dict = Field(default_factory=dict)
    llm_args_schema: dict = Field(default_factory=dict)
    endpoint: dict = Field(default_factory=dict, description="HTTP endpoint 定义（openapi）")
    code: str = Field(default="", description="Python 代码（code）")
    output_schema: dict = Field(default_factory=dict, description="返回字段声明——下游 {{node.result.字段}} 精确引用")
    tags: list[str] = Field(default_factory=list)


class ToolUpdateRequest(BaseModel):
    """编辑请求——None 字段保持不变。"""

    name: str | None = None
    description: str | None = None
    user_args_schema: dict | None = None
    llm_args_schema: dict | None = None
    endpoint: dict | None = None
    code: str | None = None
    output_schema: dict | None = None
    tags: list[str] | None = None


class ToolArgsRequest(BaseModel):
    """工具级统一凭证——sensitive 明文由后端加密存储。"""

    user_args: dict = Field(default_factory=dict)


class EnableRequest(BaseModel):
    enabled: bool = Field(..., description="开启=可被 Agent/工作流使用（admin 三重校验）")


class VoteRequest(BaseModel):
    value: int = Field(..., description="1 = 👍 | -1 = 👎")


class ReviewRequest(BaseModel):
    action: str = Field(..., description="approve | reject")
    reason: str = Field(default="", description="驳回理由（展示给作者）")


def _to_item(doc: dict) -> dict:
    """Mongo doc → 响应 dict（id 替代 _id；凭证字段脱敏剔除）。"""
    item = dict(doc)
    item["id"] = item.pop("_id", "")
    item.pop("org_user_args", None)  # 凭证不回传
    return item


@router.get("/enabled")
async def list_enabled_tools(
    _: UserResponse = Depends(require_permission("tool:read")),
) -> list[dict]:
    """可用工具全集（官方 active + 组织库 published&enabled）——
    Agent 绑定与工作流节点的候选列表。"""
    return [_to_item(d) for d in await UserToolService.list_enabled_tools()]


@router.get("/marketplace")
async def marketplace(
    q: str = Query(default=""),
    limit: int = Query(default=50, ge=1, le=100),
    current_user: UserResponse = Depends(get_current_user),
) -> list[dict]:
    """组织工具库目录：官方 + 已发布用户工具（含治理状态，无安装语义）。"""
    items = await UserToolService.marketplace(current_user.id, q=q, limit=limit)
    for it in items:
        it.pop("org_user_args", None)
    return items


@router.get("/admin/review")
async def list_for_review(
    status: str = Query(default="submitted"),
    _: UserResponse = Depends(require_any_role("admin")),
) -> list[dict]:
    return [_to_item(d) for d in await UserToolService.list_for_review(status)]


@router.post("")
async def create_my_tool(
    body: ToolDefinition,
    current_user: UserResponse = Depends(require_permission("tool:write")),
) -> dict:
    """创建工具（tool:write——ToB 治理：有权限的人才能创建）。"""
    try:
        return _to_item(await UserToolService.create_tool(
            current_user.id,
            name=body.name,
            description=body.description,
            source=body.source,
            user_args_schema=body.user_args_schema,
            llm_args_schema=body.llm_args_schema,
            endpoint=body.endpoint,
            code=body.code,
            output_schema=body.output_schema,
            tags=body.tags,
        ))
    except UserToolError as exc:
        raise ValidationError(code="USER_TOOL_INVALID", message=exc.message) from exc


@router.get("/{tool_id}")
async def get_tool_detail(
    tool_id: str,
    current_user: UserResponse = Depends(get_current_user),
) -> dict:
    doc = await UserToolService.get_tool(tool_id)
    if doc is None or not await UserToolService.can_view(current_user.id, doc):
        raise NotFoundError(code="USER_TOOL_NOT_FOUND", message=f"Tool {tool_id} 不存在")
    item = _to_item(doc)
    # admin 凭证弹窗回显：sensitive 字段为 enc: 密文（不可反推），非敏感为明文；
    # 列表/目录等其余出口仍统一剔除。
    if current_user.role == "admin":
        item["org_user_args"] = doc.get("org_user_args") or {}
    return item


@router.put("/{tool_id}")
async def update_my_tool(
    tool_id: str,
    body: ToolUpdateRequest,
    current_user: UserResponse = Depends(require_permission("tool:write")),
    admin_check: UserResponse = Depends(require_any_role("admin")),
) -> dict:
    """编辑（owner 或 admin；已发布的编辑回 private 且需重新开启）。"""
    is_admin = admin_check is not None
    try:
        return _to_item(await UserToolService.update_tool(
            current_user.id,
            tool_id,
            name=body.name,
            description=body.description,
            user_args_schema=body.user_args_schema,
            llm_args_schema=body.llm_args_schema,
            endpoint=body.endpoint,
            code=body.code,
            output_schema=body.output_schema,
            tags=body.tags,
            is_admin=is_admin,
        ))
    except UserToolError as exc:
        raise ValidationError(code="USER_TOOL_INVALID", message=exc.message) from exc


@router.delete("/{tool_id}")
async def delete_my_tool(
    tool_id: str,
    current_user: UserResponse = Depends(require_permission("tool:write")),
    admin_check: UserResponse = Depends(require_any_role("admin")),
) -> dict:
    is_admin = admin_check is not None
    try:
        await UserToolService.delete_tool(current_user.id, tool_id, is_admin=is_admin)
        return {"ok": True}
    except UserToolError as exc:
        raise NotFoundError(code="USER_TOOL_NOT_FOUND", message=exc.message) from exc


@router.post("/{tool_id}/submit")
async def submit_tool(
    tool_id: str,
    current_user: UserResponse = Depends(require_permission("tool:write")),
) -> dict:
    try:
        return _to_item(await UserToolService.submit_for_review(current_user.id, tool_id))
    except UserToolError as exc:
        raise ValidationError(code="USER_TOOL_INVALID", message=exc.message) from exc


@router.post("/admin/review/{tool_id}")
async def review_tool(
    tool_id: str,
    body: ReviewRequest,
    reviewer: UserResponse = Depends(require_any_role("admin")),
) -> dict:
    try:
        return _to_item(await UserToolService.review_tool(tool_id, body.action, reviewer.id, body.reason))
    except UserToolError as exc:
        raise ValidationError(code="USER_TOOL_INVALID", message=exc.message) from exc


@router.put("/{tool_id}/args")
async def save_org_args(
    tool_id: str,
    body: ToolArgsRequest,
    admin: UserResponse = Depends(require_any_role("admin")),
) -> dict:
    """配置工具级统一凭证（admin；sensitive 加密，全使用点共用）。"""
    try:
        await UserToolService.save_org_args(admin.id, tool_id, body.user_args)
        return {"ok": True}
    except UserToolError as exc:
        raise ValidationError(code="USER_TOOL_INVALID", message=exc.message) from exc


@router.post("/{tool_id}/enable")
async def enable_tool(
    tool_id: str,
    body: EnableRequest,
    admin: UserResponse = Depends(require_any_role("admin")),
) -> dict:
    """开启/停用（admin）——开启三重校验：published + 定义完整 + 凭证完整。"""
    try:
        return _to_item(await UserToolService.enable_tool(admin.id, tool_id, body.enabled))
    except UserToolError as exc:
        raise ValidationError(code="USER_TOOL_ARGS_INCOMPLETE", message=exc.message) from exc


@router.post("/{tool_id}/fork")
async def fork_tool(
    tool_id: str,
    current_user: UserResponse = Depends(require_permission("tool:write")),
) -> dict:
    """复制为我的草稿（derived_from 溯源）。"""
    try:
        return _to_item(await UserToolService.fork(current_user.id, tool_id))
    except UserToolError as exc:
        raise ValidationError(code="USER_TOOL_INVALID", message=exc.message) from exc


@router.post("/{tool_id}/vote")
async def vote_tool(
    tool_id: str,
    body: VoteRequest,
    current_user: UserResponse = Depends(get_current_user),
) -> dict:
    try:
        return await UserToolService.vote(current_user.id, tool_id, body.value)
    except UserToolError as exc:
        raise ValidationError(code="USER_TOOL_INVALID", message=exc.message) from exc
