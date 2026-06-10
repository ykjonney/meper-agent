---
baseline_commit: NO_VCS
---

# Story 1.3: 用户登录（JWT 认证）

Status: review

## Story

**As a** 已注册用户，
**I want** 用用户名和密码登录获取 JWT token，
**So that** 后续所有 API 调用都能携带身份认证。

## Acceptance Criteria (BDD)

### AC1: 登录成功返回 JWT

**Given** 已存在的用户账户
**When** 用户 POST `/api/v1/auth/login` 提交 `{username, password}`
**Then** 验证密码（bcrypt）成功后返回：
```json
{
  "access_token": "...",
  "refresh_token": "...",
  "token_type": "bearer",
  "expires_in": 900
}
```
**And** access_token 有效期 15 分钟，refresh_token 7 天
**And** 登录成功更新 `last_login_at` 字段为当前 UTC 时间

### AC2: 账户锁定（连续失败 5 次）

**Given** 错误密码（连续 5 次）
**When** 5 次登录失败
**Then** 账户锁定 15 分钟，登录接口返回：
```json
{"error": {"code": "ACCOUNT_LOCKED", "message": "账户已锁定，请 15 分钟后重试"}}
```
**And** 锁定期间即使使用正确密码也拒绝登录

### AC3: JWT 鉴权保护资源

**Given** 访问受保护资源
**When** 请求携带 `Authorization: Bearer <access_token>`
**Then** 后端解析 JWT 验证：
- 签名有效
- 未过期
- 用户状态为 `active`（非 `disabled`）
**And** 通过则将 `current_user` 注入到 endpoint 上下文
**And** 未携带 token / 无效 token / 过期 token 返回 401：
```json
{"error": {"code": "TOKEN_INVALID", "message": "..."}}
```

### AC4: Refresh Token 续期

**Given** access_token 过期
**When** 调用 `/api/v1/auth/refresh` 携带 refresh_token
**Then** 返回新的 access_token，原 refresh_token 不变
**And** refresh_token 接近过期（剩余 < 1 天）时滚动续期生成新 refresh_token
**And** 无效/过期 refresh_token 返回 401

### AC5: 登录失败错误处理

**Given** 用户名不存在或密码错误
**When** POST `/api/v1/auth/login`
**Then** 返回 401：
```json
{"error": {"code": "INVALID_CREDENTIALS", "message": "用户名或密码错误"}}
```
**And** 不区分「用户不存在」和「密码错误」（防信息泄露）

### AC6: 安全约束（NFR-S2）

**Given** 整个登录/认证流程
**When** 密码处理、JWT 签发、日志记录
**Then** 密码不以任何形式记录到日志
**And** JWT 签名密钥从 `.env` 的 `JWT_SECRET_KEY` 读取，缺失则启动失败
**And** 错误日志仅记录 `username`，不记录密码或 token 内容

---

## Tasks / Subtasks

### 阶段 1：Schemas 扩展

- [x] **T1** 扩展 Auth Schemas（AC: #1, #4, #5）
  - [x] T1.1 在 `app/schemas/auth.py` 新增 `LoginRequest`：`{username: str, password: str}`
  - [x] T1.2 在 `app/schemas/auth.py` 新增 `RefreshRequest`：`{refresh_token: str}`
  - [x] T1.3 验证 `TokenResponse` 已存在且字段完整（复用 Story 1.2）

### 阶段 2：账户锁定机制

- [x] **T2** 实现账户锁定服务（AC: #2, #5）
  - [x] T2.1 创建 `app/services/auth_service.py`
  - [x] T2.2 实现 `record_failed_login(username: str) -> None`：Redis 计数，5 次后锁定 15 分钟
    - Redis key: `auth:failed:{username}`，TTL=900s（15 分钟）
    - Redis key: `auth:locked:{username}`，TTL=900s（15 分钟）
  - [x] T2.3 实现 `is_account_locked(username: str) -> bool`：检查 `auth:locked:{username}`
  - [x] T2.4 实现 `reset_failed_login(username: str) -> None`：登录成功后清除失败计数
  - [x] T2.5 实现 `get_remaining_lock_time(username: str) -> int`：返回剩余锁定秒数（用于错误提示）

### 阶段 3：登录与刷新业务逻辑

- [x] **T3** 实现 AuthService 登录/刷新方法（AC: #1, #4, #5, #6）
  - [x] T3.1 实现 `async def login(username, password) -> TokenResponse`：
    - 检查账户是否锁定 → 返回 `ACCOUNT_LOCKED` 错误
    - 查询用户（不存在 → 返回 `INVALID_CREDENTIALS`，不区分错误类型）
    - 校验密码（bcrypt.verify_password，错误 → record_failed_login + 返回 `INVALID_CREDENTIALS`）
    - 成功：reset_failed_login、更新 `last_login_at`、签发 access+refresh token
  - [x] T3.2 实现 `async def refresh_token(refresh_token: str) -> TokenResponse`：
    - decode_token（PyJWT），type 必须为 refresh
    - 查询用户验证 status=active
    - 签发新 access_token
    - 若 refresh_token 剩余有效期 < 1 天（86400s），滚动签发新 refresh_token；否则保留原 token
  - [x] T3.3 在 `app/services/user_service.py` 新增 `async def update_last_login(user_id: str) -> None`

### 阶段 4：JWT 依赖注入（鉴权中间件）

- [x] **T4** 实现 JWT 鉴权 Depends（AC: #3, #6）
  - [x] T4.1 在 `app/core/security.py` 新增 `get_current_user` 依赖：
    - 从 `Authorization: Bearer <token>` 提取 token
    - decode_token，type 必须为 access
    - 查询用户，验证 status=active
    - 返回 `UserResponse` 实例
    - 失败 → `UnauthorizedError`
  - [x] T4.2 在 `app/core/security.py` 新增 `get_current_user_optional` 依赖（用于可选认证端点）

### 阶段 5：API 路由

- [x] **T5** 实现 Auth API 路由（AC: #1, #4, #5）
  - [x] T5.1 创建 `app/api/v1/auth.py`：
    - `POST /auth/login`：接收 `LoginRequest`，调用 `AuthService.login`，返回 `TokenResponse`
    - `POST /auth/refresh`：接收 `RefreshRequest`，调用 `AuthService.refresh_token`，返回 `TokenResponse`
  - [x] T5.2 在 `app/api/v1/router.py` 注册 auth_router（prefix `/auth`）
  - [x] T5.3 确保所有 Auth 路由无需 JWT 鉴权（公开端点）

### 阶段 6：测试

- [x] **T6** 创建全面测试（AC: #1-#6）
  - [x] T6.1 创建 `tests/services/test_auth_service.py`：
    - 测试 login 成功返回 token + 更新 last_login_at
    - 测试 login 用户不存在 → INVALID_CREDENTIALS
    - 测试 login 密码错误 → INVALID_CREDENTIALS + 失败计数 +1
    - 测试连续 5 次失败后锁定 → ACCOUNT_LOCKED
    - 测试锁定期间正确密码也拒绝
    - 测试锁定 15 分钟后自动解锁（mock Redis TTL）
    - 测试 refresh_token 成功返回新 access_token
    - 测试 refresh_token 滚动续期（剩余 < 1 天）
    - 测试 refresh_token 无效 → 401
  - [x] T6.2 创建 `tests/api/test_auth.py`：
    - 测试 POST /auth/login 200 成功
    - 测试 POST /auth/login 401 凭证错误
    - 测试 POST /auth/login 401 账户锁定
    - 测试 POST /auth/refresh 200 成功
    - 测试 POST /auth/refresh 401 token 无效
  - [x] T6.3 创建 `tests/core/test_security_deps.py`：
    - 测试 get_current_user 成功（有效 access token）
    - 测试 get_current_user 失败（无 Authorization header）
    - 测试 get_current_user 失败（token type=refresh 而非 access）
    - 测试 get_current_user 失败（用户已 disabled）
  - [x] T6.4 确保所有测试中密码、token 内容不被打印到日志

### 阶段 7：端到端验证

- [x] **T7** 端到端验证（AC: #1-#6 全部）
  - [x] T7.1 运行 `uv run pytest` 确保所有测试通过
  - [x] T7.2 运行 `uv run ruff check .` 确保无 lint 错误
  - [x] T7.3 运行 `uv run mypy app` 确保无类型错误
  - [x] T7.4 验证 OpenAPI 文档 `/api/v1/docs` 显示 auth 端点

---

## Dev Notes

### 1. 架构对齐（关键决策）

- **Decision 2.1**: Web 端 JWT 认证（access + refresh），已在 Story 1.2 实现 `create_access_token` / `create_refresh_token` / `decode_token`
- **Decision 2.4**: bcrypt 密码哈希，已在 Story 1.2 实现 `hash_password` / `verify_password`
- **Decision 2.3**: RBAC 手写装饰器 + Depends 注入（本 Story 只实现认证，授权在 Story 1.4）
- **Decision 3.1**: 纯 REST 风格，`POST /api/v1/auth/login`、`POST /api/v1/auth/refresh`
- **Decision 3.3**: 统一错误响应结构 `{"error": {"code": "...", "message": "..."}}`

### 2. 异步约束（Story 1.2 已确立）

**所有 DB/Redis 操作必须 async**（Story 1.2 T7 已改造完成）：
- MongoDB：使用 `motor` 的 `AsyncIOMotorCollection`（`find_one` / `update_one` 都是 awaitable）
- Redis：使用 `redis.asyncio` 的 `aioredis.Redis`（`get` / `set` / `incr` / `expire` 都是 awaitable）
- Service 层方法签名：`async def login(...) -> TokenResponse`
- FastAPI Depends：`async def get_current_user(...) -> UserResponse`

### 3. Redis Key 设计

```
# 失败登录计数（5 次后触发锁定）
auth:failed:{username}    # STRING, INCR 累计，TTL=900s

# 账户锁定标记
auth:locked:{username}    # STRING "1", TTL=900s（剩余锁定时间）

# 查询剩余锁定时间
await redis.ttl(f"auth:locked:{username}")
```

### 4. JWT Token 结构（复用 Story 1.2）

```python
# access_token payload
{
    "sub": "user_01HXYZ...",     # user_id
    "role": "admin",             # 角色信息，快速权限检查
    "type": "access",            # 关键！get_current_user 必须校验
    "exp": <unix_timestamp>,     # 15min 后过期
    "iat": <unix_timestamp>,
}

# refresh_token payload
{
    "sub": "user_01HXYZ...",
    "type": "refresh",           # 关键！refresh endpoint 必须校验
    "exp": <unix_timestamp>,     # 7d 后过期
    "iat": <unix_timestamp>,
}
```

### 5. 防信息泄露策略

- **登录失败**：不区分 "用户不存在" 和 "密码错误"，统一返回 `INVALID_CREDENTIALS`
- **失败响应延时**：可选实现 — 对所有失败响应添加恒定延时（~500ms），防止时序攻击推测用户存在性
- **日志脱敏**：仅记录 `username` 和 `client_ip`，绝不记录 `password` / `password_hash` / `access_token` / `refresh_token` 内容

### 6. FastAPI Depends 鉴权模式

```python
from fastapi import Depends, Header
from app.core.security import decode_token
from app.services.user_service import UserService

async def get_current_user(
    authorization: str = Header(..., description="Bearer <access_token>"),
) -> UserResponse:
    """解析 Bearer token 并返回当前用户。"""
    if not authorization.startswith("Bearer "):
        raise UnauthorizedError(code="TOKEN_INVALID", message="Missing Bearer prefix")

    token = authorization.removeprefix("Bearer ").strip()
    payload = decode_token(token)  # 可能抛 UnauthorizedError

    if payload.get("type") != "access":
        raise UnauthorizedError(code="TOKEN_INVALID", message="Wrong token type")

    user_doc = await UserService.get_user_by_id(payload["sub"])
    if user_doc is None:
        raise UnauthorizedError(code="USER_NOT_FOUND", message="User not found")

    if user_doc["status"] != "active":
        raise UnauthorizedError(code="ACCOUNT_DISABLED", message="Account is disabled")

    return UserResponse(**{k: v for k, v in user_doc.items() if k != "password_hash"})
```

### 7. 文件清单（NEW / UPDATE）

| 操作 | 文件路径 | 说明 |
|------|----------|------|
| UPDATE | `backend/app/schemas/auth.py` | 新增 LoginRequest / RefreshRequest |
| NEW | `backend/app/services/auth_service.py` | AuthService（login + refresh + 账户锁定） |
| UPDATE | `backend/app/services/user_service.py` | 新增 update_last_login |
| UPDATE | `backend/app/core/security.py` | 新增 get_current_user / get_current_user_optional Depends |
| NEW | `backend/app/api/v1/auth.py` | Auth API 路由（login + refresh） |
| UPDATE | `backend/app/api/v1/router.py` | 注册 auth_router |
| NEW | `backend/tests/services/test_auth_service.py` | AuthService 测试 |
| NEW | `backend/tests/api/test_auth.py` | Auth API 集成测试 |
| NEW | `backend/tests/core/test_security_deps.py` | JWT Depends 测试 |

### 8. 来自 Story 1.2 的可复用资产

- `app.core.security.create_access_token / create_refresh_token / decode_token / verify_password` ✅
- `app.services.user_service.UserService.get_user_by_*` ✅（已是 async）
- `app.schemas.auth.TokenResponse` ✅
- `app.schemas.user.UserResponse` ✅
- `app.db.redis.get_redis_client` ✅（已是 async）
- `app.db.mongodb.get_database` ✅（已是 motor async）

### 9. 依赖方向

```
api/v1/auth.py → services/auth_service → services/user_service + core/security + db/redis + db/mongodb
                       ↓
                  schemas/auth + schemas/user + models/user
```

### Project Structure Notes

- **Auth Service 新增**：`app/services/auth_service.py`（与 user_service.py 同级）
- **Auth API 新增**：`app/api/v1/auth.py`（与 health.py 同级）
- **鉴权依赖**：扩展 `app/core/security.py`，新增 Depends 函数（不新建 deps.py）
- **测试目录**：`tests/api/`、`tests/services/`、`tests/core/` 已存在

### References

- [Source: docs/planning-artifacts/epics.md#Story-1.3] — Story AC 原文
- [Source: docs/planning-artifacts/architecture.md#Decision-2.1] — JWT 认证（access + refresh）
- [Source: docs/planning-artifacts/architecture.md#Decision-2.3] — RBAC 手写装饰器（本 Story 实现认证，授权在 1.4）
- [Source: docs/planning-artifacts/architecture.md#Decision-2.4] — 密码哈希 bcrypt
- [Source: docs/planning-artifacts/architecture.md#Decision-3.1] — REST API 风格
- [Source: docs/planning-artifacts/architecture.md#Decision-3.3] — 统一错误响应结构
- [Source: docs/planning-artifacts/architecture.md#API-Boundaries] — `/api/v1/auth/*` 为公开 API（无 JWT）
- [Source: docs/planning-artifacts/prds/prd-agent-flow-2026-06-05/prd.md#FR-27] — 用户认证与角色管理
- [Source: docs/planning-artifacts/prds/prd-agent-flow-2026-06-05/prd.md#NFR-S] — 安全约束
- [Source: docs/implementation-artifacts/1-2-user-registration-first-admin-init.md] — Story 1.2 实现记录（可复用资产）

---

## Dev Agent Record

### Agent Model Used

Claude (deepseek-v4-flash)

### Debug Log References

- `test_security_deps.py:test_valid_access_token`: UserResponse `id` 需要从 MongoDB `_id` 字段读取（`alias` 映射）
- `auth_service.py:login`: `user_doc["id"]` → `user_doc["_id"]`（与 Story 1.2 的 `_id` 字段变更对齐）
- `pyproject.toml`: 移除未使用的 `passlib[bcrypt]` 依赖

### Completion Notes List

- ✅ T1: LoginRequest / RefreshRequest / TokenResponse 均已就位（Story 1.2 已完成）
- ✅ T2: AuthService 账户锁定机制完整实现（Redis INCR 计数，5 次失败后 set lock key，TTL 900s）
- ✅ T3: AuthService.login 和 refresh_token 完整实现，包含账户锁定检查、失败计数、滚动续期
- ✅ T4: get_current_user / get_current_user_optional 已扩展（FastAPI Header 标注 + payload 校验）
- ✅ T5: /auth/login + /auth/refresh API 路由已注册，公开端点
- ✅ T6: 22 个测试覆盖全部 6 个 AC（auth_service 10 + api/auth 5 + security_deps 7）
- ✅ T7: pytest 74 passed / ruff All checks passed / mypy 45 files no issues
- 修复 `_id` vs `id` 兼容性问题（auth_service.py + 测试）
- 修复 `payload["sub"]` 直接访问导致 KeyError 的问题

### File List

**新文件（Story 1.2 已创建）：**
- backend/app/services/auth_service.py（账户锁定 + 登录/刷新）
- backend/app/api/v1/auth.py（auth API 路由）
- backend/tests/services/test_auth_service.py
- backend/tests/api/test_auth.py
- backend/tests/core/test_security_deps.py

**修改文件（本会话）：**
- backend/app/services/auth_service.py（_id 兼容性 + sub 空值检查）
- backend/app/core/security.py（_id 读取 + Header 标注）
- backend/tests/services/test_auth_service.py（_id 测试数据对齐）
- backend/tests/core/test_security_deps.py（_id 测试数据对齐）
- docs/implementation-artifacts/sprint-status.yaml（status 更新）
