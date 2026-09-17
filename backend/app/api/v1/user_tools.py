"""组织工具库 REST API（ToB 治理模型：「工具库 / 我创建的」）。

治理流程：tool:write 用户创建 → submit → admin 审查（approve→published）
→ admin 配置凭证（org_user_args，sensitive 加密）→ admin 开启
（校验 published + 定义完整 + 凭证完整）→ Agent 绑定 / 工作流直调。

- GET  /user-tools/enabled     可用工具全集（Agent 绑定/工作流节点候选）
- GET  /user-tools/marketplace 组织工具库目录（浏览 + 治理状态；无安装语义）
- POST /user-tools             创建（tool:write）
- GET/PUT/DELETE /user-tools/{id}   详情 / 编辑（owner|admin）/ 删除
- POST /user-tools/forge/stream     工具工坊 agent（SSE：生成→测试→保存闭环）
- POST /user-tools/forge/{id}/resume 恢复工坊 interrupt（凭证/澄清答复）
- POST /user-tools/test-run    试跑草稿定义（不落库）
- POST /user-tools/test-cases  AI 生成测试用例
- POST /user-tools/{id}/test-run 试跑已保存工具（工具节点调试）
- POST /user-tools/{id}/submit 提交发布审查（owner）
- GET/POST /user-tools/admin/review   管理员审核台
- PUT  /user-tools/{id}/args   配置工具级凭证（owner|admin）
- POST /user-tools/{id}/enable 开启/停用（admin，三重校验）
- POST /user-tools/{id}/vote   目录投票（组织内反馈信号）
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
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


class ToolTestRunRequest(BaseModel):
    """试跑一次工具定义（不落库、不要求 published/enabled）。"""

    definition: dict = Field(..., description="{name, source, code, endpoint, llm_args_schema}")
    params: dict = Field(default_factory=dict, description="运行参数（对应 llm_args_schema）")
    user_args: dict = Field(default_factory=dict, description="试跑凭证（ad hoc，不持久化）")


class ToolTestCaseRequest(BaseModel):
    """AI 按工具定义生成测试用例。"""

    definition: dict = Field(...)
    model_id: str = Field(default="")


class ForgeStreamRequest(BaseModel):
    """工具工坊 agent 对话（SSE）——新会话或续接。"""

    message: str = Field(default="", max_length=8000)
    model_id: str = Field(default="", description="生成模型（model_ 前缀；空 = 平台默认）")
    mode: str = Field(default="create", description="create（新建，save=create）| edit（修改，save=update）")
    tool_id: str = Field(default="", description="edit 模式：要修改的工具 id（已保存定义注入对话）")
    forge_id: str = Field(default="", description="续接既有工坊会话")


class ForgeResumeRequest(BaseModel):
    """恢复被 ask_clarification 暂停的工坊会话。"""

    answer: dict | str = Field(..., description="凭证表单答复（dict）或文本答复")


class SavedToolTestRequest(BaseModel):
    """试跑已保存的工具（工具节点调试）：参数 + 可选凭证覆盖。"""

    params: dict = Field(default_factory=dict)
    user_args: dict = Field(default_factory=dict, description="临时覆盖组织凭证（不持久化）")


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
    """创建工具（tool:write——ToB 治理：有权限的人才能创建）。

    admin 创建即 published（免自审）；开启仍需配凭证后显式操作。
    """
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
            is_admin=current_user.role == "admin",
        ))
    except UserToolError as exc:
        raise ValidationError(code="USER_TOOL_INVALID", message=exc.message) from exc


@router.post("/test-run")
async def test_run_tool(
    body: ToolTestRunRequest,
    current_user: UserResponse = Depends(require_permission("tool:write")),
) -> dict:
    """试跑一次工具定义（tool:write——与创建同权限，治理链的验证环节）。

    不落库、不要求 published/enabled；code 走既有沙箱隔离（60s 超时）；
    试跑凭证即填即用不持久化。
    """
    from app.services.tool_tester import run_once as test_run_once

    try:
        return await test_run_once(body.definition, body.params, body.user_args)
    except UserToolError as exc:
        raise ValidationError(code="TOOL_TEST_FAILED", message=exc.message) from exc


@router.post("/test-cases")
async def generate_test_cases(
    body: ToolTestCaseRequest,
    current_user: UserResponse = Depends(require_permission("tool:write")),
) -> dict:
    """AI 按工具定义生成测试用例（仅 params；凭证由用户在试跑时另填）。"""
    from app.services.tool_tester import generate_cases

    try:
        return await generate_cases(body.definition, body.model_id.strip())
    except UserToolError as exc:
        raise ValidationError(code="TOOL_TEST_FAILED", message=exc.message) from exc


@router.post("/forge/stream")
async def forge_stream(
    body: ForgeStreamRequest,
    current_user: UserResponse = Depends(require_permission("tool:write")),
) -> StreamingResponse:
    """工具工坊 agent（SSE）——LLM 自主「生成 → 测试 → 修正 → 保存」闭环。

    会话进程内（InMemorySaver）：forge_id 续接；进程重启即失效（重新开始）。
    新会话经 ``X-Forge-Id`` 响应头返回 forge_id；done 帧附草稿/保存态。
    """
    from app.services.tool_forge_service import ToolForgeService

    try:
        event_queue, forge_id = await ToolForgeService.stream(
            current_user.id,
            message=body.message,
            model_id=body.model_id.strip(),
            mode=body.mode.strip() or "create",
            tool_id=body.tool_id.strip(),
            forge_id=body.forge_id.strip(),
            is_admin=current_user.role == "admin",
        )
    except UserToolError as exc:
        raise ValidationError(code="TOOL_FORGE_INVALID", message=exc.message) from exc

    async def _event_stream():
        try:
            while True:
                item = await event_queue.get()
                if item is None:
                    break
                yield item
        finally:
            # 断连 ≠ 取消：后台任务继续执行完（与 agents stream 同语义）
            pass

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Forge-Id": forge_id},
    )


@router.post("/forge/{forge_id}/resume")
async def forge_resume(
    forge_id: str,
    body: ForgeResumeRequest,
    current_user: UserResponse = Depends(require_permission("tool:write")),
) -> StreamingResponse:
    """恢复工坊会话的 interrupt（ask_clarification 凭证/澄清答复）。"""
    from app.services.tool_forge_service import ToolForgeService

    try:
        event_queue = await ToolForgeService.resume(forge_id, body.answer)
    except UserToolError as exc:
        raise ValidationError(code="TOOL_FORGE_INVALID", message=exc.message) from exc

    async def _event_stream():
        try:
            while True:
                item = await event_queue.get()
                if item is None:
                    break
                yield item
        finally:
            pass

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Forge-Id": forge_id},
    )


@router.post("/{tool_id}/test-run")
async def test_run_saved_tool(
    tool_id: str,
    body: SavedToolTestRequest,
    current_user: UserResponse = Depends(require_permission("tool:write")),
) -> dict:
    """试跑已保存的工具（工具节点调试用，tool:write）。

    定义按 id 从库加载（uto_ 要求 published+enabled，与生产直调同治理口径）；
    凭证默认用工具级组织配置，user_args 可临时覆盖（不持久化）。
    """
    from app.services.tool_tester import run_saved_once

    try:
        return await run_saved_once(tool_id, body.params, body.user_args)
    except UserToolError as exc:
        raise ValidationError(code="TOOL_TEST_FAILED", message=exc.message) from exc


@router.get("/{tool_id}")
async def get_tool_detail(
    tool_id: str,
    current_user: UserResponse = Depends(get_current_user),
) -> dict:
    doc = await UserToolService.get_tool(tool_id)
    if doc is None or not await UserToolService.can_view(
        current_user.id, doc, is_admin=current_user.role == "admin"
    ):
        raise NotFoundError(code="USER_TOOL_NOT_FOUND", message=f"Tool {tool_id} 不存在")
    item = _to_item(doc)
    # 凭证弹窗回显（owner/admin 可配置凭证，均可回显）：sensitive 字段为
    # enc: 密文（不可反推），非敏感为明文；列表/目录等其余出口仍统一剔除。
    if current_user.role == "admin" or doc.get("owner_user_id") == current_user.id:
        item["org_user_args"] = doc.get("org_user_args") or {}
    return item


@router.put("/{tool_id}")
async def update_my_tool(
    tool_id: str,
    body: ToolUpdateRequest,
    current_user: UserResponse = Depends(require_permission("tool:write")),
) -> dict:
    """编辑（owner 或 admin；已发布的编辑回 private 且需重新开启）。"""
    # 不能用 Depends(require_any_role("admin")) 探测 admin——它对非 admin
    # 直接抛 403，owner 本人会被拦在 handler 外。角色在 handler 内判定，
    # owner 校验交给 update_tool（is_admin 覆盖）。
    is_admin = current_user.role == "admin"
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
) -> dict:
    is_admin = current_user.role == "admin"
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
    current_user: UserResponse = Depends(require_permission("tool:write")),
) -> dict:
    """配置工具级统一凭证（owner 或 admin；sensitive 加密，全使用点共用）。"""
    try:
        await UserToolService.save_org_args(
            current_user.id, tool_id, body.user_args,
            is_admin=current_user.role == "admin",
        )
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
