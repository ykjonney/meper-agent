---
baseline_commit: NO_VCS
---

# Story 1.4: 用户管理与 RBAC 权限控制

Status: review

## Story

**As a** 平台管理员，
**I want** 通过管理界面管理用户账户、分配角色，并且所有 API 端点根据角色进行权限控制，
**So that** 不同角色的用户只能访问其授权范围内的功能，确保平台安全性。

## Acceptance Criteria (BDD)

### AC1: 管理员可以查看用户列表

**Given** 管理员已登录（JWT 有效且 role=admin）
**When** GET `/api/v1/admin/users`（支持分页、筛选）
**Then** 返回用户列表：
```json
{
  "items": [
    {
      "id": "user_01HXYZ...",
      "username": "zhangsan",
      "email": "zhangsan@example.com",
      "role": "developer",
      "status": "active",
      "created_at": "2026-01-01T00:00:00",
      "updated_at": "2026-01-01T00:00:00",
      "last_login_at": "2026-06-01T08:00:00"
    }
  ],
  "total": 10,
  "page": 1,
  "page_size": 20
}
```
**And** 响应不包含 `password_hash` 字段
**And** 支持按 `username`、`role`、`status` 进行筛选
**And** 支持分页参数 `page`（默认 1）和 `page_size`（默认 20，最大 100）

### AC2: 管理员可以创建新用户

**Given** 管理员已登录
**When** POST `/api/v1/admin/users` 提交：
```json
{
  "username": "lisi",
  "email": "lisi@example.com",
  "password": "Strong1234",
  "role": "developer"
}
```
**Then** 创建成功返回 201：
```json
{
  "id": "user_01HABC...",
  "username": "lisi",
  "email": "lisi@example.com",
  "role": "developer",
  "status": "active",
  "created_at": "...",
  "updated_at": "..."
}
```
**And** 不返回 `password_hash`
**And** 用户名重复 → 409 `USERNAME_CONFLICT`
**And** 邮箱重复 → 409 `EMAIL_CONFLICT`
**And** 密码强度不足 → 422 `PASSWORD_TOO_SHORT` / `PASSWORD_MISSING_COMPLEXITY`

### AC3: 管理员可以更新用户信息（角色/状态）

**Given** 管理员已登录
**When** PATCH `/api/v1/admin/users/{user_id}` 提交：
```json
{
  "role": "operator",
  "status": "disabled"
}
```
**Then** 更新成功返回 200，返回完整用户信息
**And** 只更新请求中提供的字段（部分更新）
**And** 不允许将自己降级为非 admin 角色（防止权限自杀）
**And** 不允许将最后一位管理员降级或禁用
**And** 用户不存在 → 404 `USER_NOT_FOUND`

### AC4: 管理员可以删除用户

**Given** 管理员已登录
**When** DELETE `/api/v1/admin/users/{user_id}`
**Then** 删除成功返回 204 No Content
**And** 不允许删除自己
**And** 用户不存在 → 404 `USER_NOT_FOUND`

### AC5: 管理员可以重置用户密码

**Given** 管理员已登录
**When** POST `/api/v1/admin/users/{user_id}/reset-password` 提交：
```json
{
  "new_password": "NewStrong5678"
}
```
**Then** 重置成功返回 200：
```json
{"message": "密码已重置"}
```
**And** 新密码必须通过强度校验（同 Story 1.2 AC2 标准）
**And** 不记录新密码到日志（NFR-S2）

### AC6: RBAC 权限装饰器保护资源

**Given** 受 RBAC 保护的 API 端点
**When** 非授权角色访问
**Then** 返回 403 Forbidden：
```json
{"error": {"code": "FORBIDDEN", "message": "权限不足，需要 admin 角色"}}
```
**And** `Depends(require_role("admin"))` 装饰器可用
**And** `Depends(require_role("developer"))` 装饰器可用
**And** `Depends(require_role("operator"))` 装饰器可用
**And** 支持多角色：`Depends(require_any_role("admin", "developer"))`

### AC7: 四角色权限矩阵定义

**Given** 平台权限模型
**Then** 各角色权限如下：

| 功能模块 | admin | developer | operator | viewer |
|---------|-------|-----------|----------|--------|
| 用户管理 | ✅ CRUD | ❌ | ❌ | ❌ |
| Agent 管理 | ✅ 全部 | ✅ CRUD | ❌ | ❌ |
| Agent 对话/查看 | ✅ 全部 | ✅ 全部 | ✅ 已授权 | ✅ 查看 |
| 工作流管理 | ✅ 全部 | ✅ CRUD | ❌ | ❌ |
| 工具中心 | ✅ 全部 | ✅ CRUD | ❌ | ❌ |
| 知识库 | ✅ 全部 | ✅ CRUD | ❌ | ❌ |
| 执行日志 | ✅ 全部 | ✅ 本人 | ✅ 本人 | ❌ |
| API Key | ✅ 管理 | ❌ | ❌ | ❌ |
| 系统设置 | ✅ 管理 | ❌ | ❌ | ❌ |

### AC8: 安全约束（NFR-S2）

**Given** 用户管理流程
**When** 处理用户数据
**Then** 密码不以任何形式记录到日志
**And** 管理操作（创建/更新/删除用户、重置密码）记录审计日志
**And** 只有 admin 角色可访问用户管理 API

---

## Tasks / Subtasks

### 阶段 1：Schema 与权限矩阵定义

- [x] **T1** 定义权限矩阵和 RBAC 辅助函数（AC: #6, #7）
  - [x] T1.1 在 `app/core/security.py` 新增 `require_role(required: UserRole)` 工厂函数
  - [x] T1.2 新增 `require_any_role(*roles: UserRole)` 多角色支持
  - [x] T1.3 新增 `ROLE_PERMISSIONS` 权限矩阵常量（基于 AC7 表格）
  - [x] T1.4 新增 `has_permission(user_role: UserRole, permission: str) -> bool` 查询函数

### 阶段 2：用户管理 Schemas

- [x] **T2** 定义用户管理 API Schemas（AC: #1, #2, #3, #5）
  - [x] T2.1 在 `app/schemas/user.py` 新增 `UserUpdate`：可选的 `role`/`status`
  - [x] T2.2 新增 `UserListResponse`：`{items: list[UserResponse], total, page, page_size}`
  - [x] T2.3 新增 `PasswordResetRequest`：`{new_password: str}`
  - [x] T2.4 新增 `PasswordResetResponse`：`{message: str}`

### 阶段 3：管理员 API 业务逻辑

- [x] **T3** 在 UserService 实现管理员需要用到的查询和操作方法（AC: #1-#5）
  - [x] T3.1 新增 `list_users(page, page_size, username, role, status) -> tuple[list[dict], int]`：分页查询 + 计数
  - [x] T3.2 新增 `create_user_by_admin(username, email, password, role) -> dict`：创建用户并返回文档
  - [x] T3.3 新增 `update_user(user_id, updates) -> dict | None`：部分更新（role/status）
  - [x] T3.4 新增 `delete_user(user_id) -> bool`：删除用户
  - [x] T3.5 新增 `reset_password(user_id, new_password) -> bool`：重置密码
  - [x] T3.6 所有方法校验业务规则（不能自杀、最后 admin 保护等）

### 阶段 4：用户管理 API 路由

- [x] **T4** 实现 Admin API 路由（AC: #1-#6, #8）
  - [x] T4.1 创建 `app/api/v1/admin.py`：
  - [x] T4.2 在 `app/api/v1/router.py` 注册 admin_router（prefix `/admin`）
  - [x] T4.3 require_role 依赖注入保护所有 admin 路由

### 阶段 5：测试

- [x] **T5** 创建全面测试（AC: #1-#8）
  - [x] T5.1 创建 `tests/core/test_rbac.py`：
    - 测试 `require_role("admin")` 通过/拒绝
    - 测试 `require_any_role("admin", "developer")` 多角色
    - 测试 `has_permission` 矩阵查询
    - 测试权限边界（非 admin 角色调用 admin 接口）
  - [x] T5.2 创建 `tests/services/test_user_service_admin.py`：
    - 测试 list_users 分页和筛选
    - 测试 create_user_by_admin 成功/冲突
    - 测试 update_user 角色变更/自我保护
    - 测试 delete_user 成功/自我保护/最后 admin 保护
    - 测试 reset_password
  - [x] T5.3 创建 `tests/api/test_admin_users.py`：
    - 测试所有 admin 端点 200 成功
    - 测试非 admin 角色访问返回 403
    - 测试未认证访问返回 401
    - 测试各种业务错误（404、409、422）
    - 测试边界条件（空列表、分页）
  - [x] T5.4 确保所有测试中密码、token 内容不被打印到日志

### 阶段 6：端到端验证

- [x] **T6** 端到端验证（AC: #1-#8 全部）
  - [x] T6.1 运行 `uv run pytest` 确保所有测试通过
  - [x] T6.2 运行 `uv run ruff check .` 确保无 lint 错误
  - [x] T6.3 运行 `uv run mypy app` 确保无类型错误
  - [x] T6.4 验证 OpenAPI 文档 `/api/v1/docs` 显示 admin 端点（带 security lock）

---

## Dev Notes

### 1. 架构对齐（关键决策）

- **Decision 2.3**: RBAC 手写装饰器 + Depends 注入（`Depends(require_role("admin"))`）
- **Decision 2.1**: JWT access_token payload 已包含 `role` 字段（Story 1.2 实现）
- **Decision 3.3**: 统一错误响应结构 `{"error": {"code": "...", "message": "..."}}`
- **Decision 3.1**: 纯 REST 风格，`/api/v1/admin/users` 为管理员专有命名空间

### 2. require_role 实现模式

```python
from fastapi import Depends
from app.core.security import get_current_user
from app.models.user import UserRole

async def require_role(role: UserRole) -> "RequireRole":
    """Factory: returns a Depends callable that checks user role."""
    async def _check(current_user: UserResponse = Depends(get_current_user)) -> UserResponse:
        if current_user.role != role:
            raise ForbiddenError(code="FORBIDDEN", message=f"权限不足，需要 {role.value} 角色")
        return current_user
    return _check


async def require_any_role(*roles: UserRole):
    """Factory: returns a Depends callable that accepts any of the given roles."""
    async def _check(current_user: UserResponse = Depends(get_current_user)) -> UserResponse:
        if current_user.role not in roles:
            raise ForbiddenError(code="FORBIDDEN", message=f"权限不足，需要以下角色之一：{', '.join(r.value for r in roles)}")
        return current_user
    return _check
```

### 3. 路由使用方式

```python
from app.core.security import get_current_user, require_role
from app.models.user import UserRole

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(get_current_user)])

@router.get("/users", response_model=UserListResponse)
async def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    username: str | None = Query(None),
    role: UserRole | None = Query(None),
    status: UserStatus | None = Query(None),
    current_user: UserResponse = Depends(require_role(UserRole.ADMIN)),
) -> UserListResponse:
    ...
```

### 4. 业务规则保护

- **禁止权限自杀**: 不允许 admin 用户将自己的 role 从 admin 改为非 admin。必须在代码中显式检查 `current_user.id == target_user.id` 且 `updates.role` 为非 admin → 返回 422。
- **最后 admin 保护**: 当尝试降级或禁用最后一位 admin 时，需先查询当前 admin 数量。如果只剩 1 个 admin 且操作目标是该 admin，拒绝操作。
- **不能删除自己**: `DELETE /admin/users/{user_id}` 当 user_id == current_user.id 时返回 422。

### 5. 分页查询模式

```python
@staticmethod
async def list_users(
    page: int = 1,
    page_size: int = 20,
    username: str | None = None,
    role: str | None = None,
    status: str | None = None,
) -> tuple[list[dict], int]:
    col = UserService._collection()
    filter_query: dict = {}
    if username:
        filter_query["username"] = {"$regex": username, "$options": "i"}
    if role:
        filter_query["role"] = role
    if status:
        filter_query["status"] = status

    total = await col.count_documents(filter_query)
    cursor = col.find(filter_query)
    # Exclude password_hash; sort by created_at desc
    cursor = cursor.sort("created_at", -1).skip((page - 1) * page_size).limit(page_size)
    items = await cursor.to_list(length=page_size)
    return items, total
```

### 6. 文件清单（NEW / UPDATE）

| 操作 | 文件路径 | 说明 |
|------|----------|------|
| UPDATE | `backend/app/core/security.py` | 新增 require_role / require_any_role / ROLE_PERMISSIONS / has_permission |
| UPDATE | `backend/app/schemas/user.py` | 新增 UserUpdate / UserListResponse / PasswordResetRequest / PasswordResetResponse |
| UPDATE | `backend/app/services/user_service.py` | 新增 list_users / create_user_by_admin / update_user / delete_user / reset_password |
| NEW | `backend/app/api/v1/admin.py` | Admin API 路由（用户管理 CRUD + 密码重置） |
| UPDATE | `backend/app/api/v1/router.py` | 注册 admin_router |
| NEW | `backend/tests/core/test_rbac.py` | RBAC 权限装饰器测试 |
| NEW | `backend/tests/services/test_user_service_admin.py` | UserService 管理员操作测试 |
| NEW | `backend/tests/api/test_admin_users.py` | Admin API 集成测试 |

### 7. 依赖方向

```
api/v1/admin.py → services/user_service + core/security + schemas/user
                      ↓
                 db/mongodb + models/user
```

### 8. 异步约束（延续 Story 1.2/1.3 约定）

- MongoDB：使用 `motor` 的 `AsyncIOMotorCollection`（全 awaitable）
- Service 层方法签名：所有方法 async
- FastAPI Depends：async

### 9. 可复用资产

- `app.core.security.get_current_user` ✅（已实现，返回 UserResponse）
- `app.models.user.UserRole` ✅（已包含 4 角色 Enum）
- `app.models.user.UserStatus` ✅（active/disabled）
- `app.schemas.user.UserResponse` ✅（无 password_hash）
- `app.schemas.user.UserCreate` ✅（含密码强度校验）
- `app.services.user_service.UserService.get_user_by_id` ✅

### 10. 审计日志说明

管理操作应记录结构化的审计日志（使用 loguru）：
```python
logger.info("admin_user_created", admin_user=current_user.username, target_user=username, target_role=role)
logger.info("admin_user_updated", admin_user=current_user.username, target_user_id=user_id, changes=updates)
logger.info("admin_user_deleted", admin_user=current_user.username, target_user_id=user_id)
logger.info("admin_password_reset", admin_user=current_user.username, target_user_id=user_id)
```
绝不记录密码原文或新密码哈希到日志。

### References

- [Source: docs/planning-artifacts/epics.md#Epic-1] — 平台基础建设（FR-27, FR-28）
- [Source: docs/planning-artifacts/architecture.md#Decision-2.3] — RBAC 手写装饰器 + Depends 注入
- [Source: docs/planning-artifacts/architecture.md#Decision-3.3] — 统一错误响应结构
- [Source: docs/planning-artifacts/prds/prd-agent-flow-2026-06-05/prd.md#FR-27] — 用户认证与角色管理
- [Source: docs/planning-artifacts/ux-designs/ux-agent-flow-2026-06-08/EXPERIENCE.md] — 侧边栏角色过滤（/users admin only）
- [Source: docs/planning-artifacts/ux-designs/ux-agent-flow-2026-06-08/DESIGN.md] — 角色颜色令牌（admin=red, developer=blue, operator=green, viewer=gray）
- [Source: docs/implementation-artifacts/1-3-user-login-jwt-auth.md] — 已有 JWT 认证实现（get_current_user）
- [Source: docs/implementation-artifacts/1-2-user-registration-first-admin-init.md] — 已有 UserService 实现

---

## Dev Agent Record

### Agent Model Used

deepseek-v4-flash (Claude Code CLI)

### Debug Log References

- 测试中双重 `patch` 同一函数时，第二个 `patch` 覆盖第一个，导致 mock 失效。
  解决方案：使用单 `patch` + 基于参数判断的 `side_effect` 函数。
- Motor cursor 的 `find()` 是同步方法，返回 cursor 对象（非 coroutine），不能使用 `AsyncMock`。

### Completion Notes List

- ✅ T1-T3 完成：security.py 添加 require_role / require_any_role / ROLE_PERMISSIONS / has_permission；schemas/user.py 添加 UserUpdate / UserListResponse / PasswordResetRequest / PasswordResetResponse；user_service.py 添加 list_users / create_user_by_admin / update_user / delete_user / reset_password 五项管理方法，含自降级保护、最后 admin 保护、密码强度校验
- ✅ T4 完成：创建 app/api/v1/admin.py 含 5 个 admin 端点（GET/POST users、PATCH/DELETE users/{id}、POST reset-password），全部 require_role(ADMIN) 保护；注册到 router.py
- ✅ T5 完成：23 个核心 RBAC 测试 + 18 个 service 层测试 + 13 个 API 集成测试 = 54 个新测试，全部通过
- ✅ T6 完成：pytest 128/128 通过，ruff 0 errors，mypy 0 errors，OpenAPI 文档显示全部 admin 端点

### File List

| 操作 | 文件路径 | 说明 |
|------|----------|------|
| UPDATE | `backend/app/core/security.py` | 新增 require_role / require_any_role / ROLE_PERMISSIONS / has_permission |
| UPDATE | `backend/app/schemas/user.py` | 新增 UserUpdate / UserListResponse / PasswordResetRequest / PasswordResetResponse |
| UPDATE | `backend/app/services/user_service.py` | 新增 list_users / create_user_by_admin / update_user / delete_user / reset_password 五项管理方法 |
| NEW | `backend/app/api/v1/admin.py` | Admin API 路由（用户管理 CRUD + 密码重置） |
| UPDATE | `backend/app/api/v1/router.py` | 注册 admin_router |
| UPDATE | `backend/pyproject.toml` | 添加 B008 到 ruff ignore list |
| NEW | `backend/tests/core/test_rbac.py` | 23 个 RBAC 权限装饰器测试 |
| NEW | `backend/tests/services/test_user_service_admin.py` | 18 个 UserService 管理员操作测试 |
| NEW | `backend/tests/api/test_admin_users.py` | 13 个 Admin API 集成测试 |
