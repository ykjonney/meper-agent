---
baseline_commit: NO_VCS
---

# Story 1.5: 密码修改与注销登录

Status: ready-for-dev

## Story

**As a** 已登录用户，
**I want** 修改自己的密码和注销登录，
**So that** 可以定期更新密码保障账户安全，并在使用完毕后安全退出。

## Acceptance Criteria (BDD)

### AC1: 登录用户可以修改自己的密码

**Given** 用户已登录（JWT 有效）
**When** POST `/api/v1/auth/change-password` 提交：
```json
{
  "current_password": "OldPass123",
  "new_password": "NewPass567"
}
```
**Then** 验证当前密码正确 → 更新为新密码 → 返回：
```json
{"message": "密码已修改，请重新登录"}
```
**And** 当前密码错误 → 返回 401 `CURRENT_PASSWORD_MISMATCH`
**And** 新密码强度不足 → 返回 422 `PASSWORD_TOO_SHORT` / `PASSWORD_MISSING_COMPLEXITY`
**And** 新密码与当前密码相同 → 返回 422 `PASSWORD_SAME_AS_CURRENT`
**And** 新密码通过 bcrypt 哈希后存入 MongoDB（不落明文）
**And** 修改成功后**所有现有 refresh_token 立即失效**（Redis 黑名单）

### AC2: 用户注销登录

**Given** 用户持有有效的 refresh_token
**When** POST `/api/v1/auth/logout` 提交：
```json
{
  "refresh_token": "..."
}
```
**Then** 该 refresh_token 加入 Redis 黑名单，失效时间 = token 剩余 TTL
**And** 后续使用该 refresh_token 调用 `/auth/refresh` 返回 401 `TOKEN_REVOKED`
**And** 返回 200：
```json
{"message": "已注销"}
```
**And** 重复注销同一 token 返回 200（幂等）
**And** 无效 token 格式也返回 200（不泄露有效性信息）

### AC3: Token 黑名单检查

**Given** refresh_token 已被注销
**When** POST `/api/v1/auth/refresh` 携带该 token
**Then** 返回 401 `TOKEN_REVOKED`
**And** 黑名单在 token 过期后自动清除（Redis TTL 自然过期）
**And** `AuthService.refresh_token` 方法在解码后立即检查黑名单

### AC4: 安全约束（延续 NFR-S2）

**Given** 密码修改和注销流程
**When** 处理密码、Token 等敏感信息
**Then** 密码不以任何形式记录到日志
**And** Token 内容不记录到日志
**And** 审计日志记录操作（不记录密码/token 内容）：
  - `password_changed` — 记录 user_id、time
  - `user_logout` — 记录 user_id、token_hash_prefix（前 8 字符）

---

## Tasks / Subtasks

### 阶段 1：Schema 定义

- [x] **T1** 定义密码修改和登出 Schemas（AC: #1, #2）
  - [x] T1.1 在 `app/schemas/auth.py` 新增 `ChangePasswordRequest`：`{current_password: str, new_password: str}`
  - [x] T1.2 新增 `LogoutRequest`：`{refresh_token: str}`
  - [x] T1.3 新增 `MessageResponse`：`{message: str}`（通用消息响应，可复用）

### 阶段 2：AuthService 扩展

- [x] **T2** 实现密码修改业务逻辑（AC: #1, #4）
  - [x] T2.1 在 `AuthService` 新增 `async def change_password(user_id: str, current_password: str, new_password: str) -> None`
    - 调用 `UserService.get_user_by_id(user_id)` 获取当前用户文档
    - 使用 `verify_password(current_password, doc.password_hash)` 验证当前密码 → 不匹配则 `UnauthorizedError(CURRENT_PASSWORD_MISMATCH)`
    - `validate_password_strength(new_password)` → 强度不足则 `ValidationError`
    - 检查 `verify_password(new_password, doc.password_hash)` → 相同则 `ValidationError(PASSWORD_SAME_AS_CURRENT)`
    - `hash_password(new_password)` → MongoDB `update_one` 更新 `password_hash` + `updated_at`
    - 调用 `AuthService._invalidate_all_refresh_tokens(user_id)` 使所有 refresh_token 失效
    - 审计日志（loguru）：`"password_changed"` + user_id（不记录密码）

### 阶段 3：Token 黑名单机制

- [x] **T3** 实现 Token 黑名单机制（AC: #2, #3, #4）
  - [x] T3.1 在 `AuthService` 新增 `async def _invalidate_refresh_token(token: str) -> None`
    - `decode_token(token)` 解析 payload
    - 计算剩余 TTL：`payload.exp - now`
    - Redis SET `auth:revoked:{token_hash}` = user_id，TTL = 剩余秒数
    - 使用 token 的 SHA256 前 16 字符作为 key（避免存完整 token）
  - [x] T3.2 新增 `async def _invalidate_all_refresh_tokens(user_id: str) -> None`
    - Redis SET `auth:revoked:user:{user_id}` = timestamp, TTL = REFRESH_TOKEN_EXPIRE_DAYS 天
    - 用于密码修改后使该用户的所有 token 失效
  - [x] T3.3 新增 `async def _is_token_revoked(token: str) -> bool`
    - 检查 `auth:revoked:{token_hash}` 是否存在 → revoke
    - 解码 token 获取 user_id，检查 `auth:revoked:user:{user_id}` 是否存在且创建时间 > token.iat → revoke
    - 否则 → 有效
  - [x] T3.4 修改 `AuthService.refresh_token` 方法
    - 在 decode_token 之后、任何业务逻辑之前，调用 `_is_token_revoked`
    - 如果被撤销 → `UnauthorizedError(TOKEN_REVOKED, "Token has been revoked")`

### 阶段 4：登出业务逻辑

- [x] **T4** 实现登出业务逻辑（AC: #2, #4）
  - [x] T4.1 在 `AuthService` 新增 `async def logout(refresh_token: str) -> None`
    - 尝试 decode_token（无效/过期 → 静默返回，不抛异常 — AC2 幂等）
    - 调用 `_invalidate_refresh_token(token)` 加入黑名单
    - 审计日志（loguru）：`"user_logout"` + token_hash_prefix（前 8 字符）

### 阶段 5：API 路由

- [x] **T5** 实现 Auth API 路由扩展（AC: #1, #2）
  - [x] T5.1 在 `app/api/v1/auth.py` 新增路由：
    - `POST /auth/change-password`：接收 `ChangePasswordRequest`
      - Depends: `get_current_user`（需要 JWT 认证）
      - 调用 `AuthService.change_password(current_user.id, body.current_password, body.new_password)`
      - 返回 `MessageResponse(message="密码已修改，请重新登录")`
    - `POST /auth/logout`：接收 `LogoutRequest`
      - 公开端点（无 JWT 要求 — 架构 Decision `/api/v1/auth/*` 为公开 API）
      - 调用 `AuthService.logout(body.refresh_token)`
      - 返回 `MessageResponse(message="已注销")`
  - [x] T5.2 确保 `change-password` 端点在 OpenAPI 文档中显示 security lock

### 阶段 6：测试

- [x] **T6** 创建全面测试
  - [x] T6.1 更新 `tests/services/test_auth_service.py`：
    - `test_change_password_success`：修改密码成功，新密码可登录
    - `test_change_password_wrong_current`：当前密码错误 → CURRENT_PASSWORD_MISMATCH
    - `test_change_password_too_weak`：新密码强度不足 → PASSWORD_*
    - `test_change_password_same_as_current`：新旧密码相同 → PASSWORD_SAME_AS_CURRENT
    - `test_change_password_invalidates_tokens`：修改后旧 refresh_token 无法刷新
    - `test_logout_revokes_token`：登出后 token 被加入黑名单
    - `test_logout_idempotent`：重复登出返回 200
    - `test_logout_invalid_token`：无效 token 登出也返回 200
    - `test_refresh_with_revoked_token`：被撤销的 token 刷新 → TOKEN_REVOKED
    - `test_refresh_after_password_change`：密码修改后全部 token 失效
  - [x] T6.2 更新 `tests/api/test_auth.py`：
    - `test_change_password_200`：修改密码成功
    - `test_change_password_401_unauthorized`：未登录 → 401
    - `test_change_password_422_weak`：密码强度不足 → 422
    - `test_logout_200`：登出成功
    - `test_logout_idempotent`：重复登出 200
    - `test_refresh_after_logout`：登出后 refresh 失败
  - [x] T6.3 验证日志脱敏：密码/token 内容不打印到日志

### 阶段 7：端到端验证

- [x] **T7** 端到端验证（AC: #1-#4 全部）
  - [x] T7.1 运行 `uv run pytest` 确保所有测试通过
  - [x] T7.2 运行 `uv run ruff check .` 确保无 lint 错误
  - [x] T7.3 运行 `uv run mypy app` 确保无类型错误
  - [x] T7.4 验证 OpenAPI 文档 `/api/v1/docs` 显示新端点

---

## Dev Notes

### 1. 架构对齐（关键决策）

- **Decision 2.1**: JWT access (15min) + refresh (7d)。本 Story 不修改 access_token 机制，但通过 Redis 黑名单使 refresh_token 可撤销。
- **Decision 2.4**: bcrypt 密码哈希（复用 `hash_password` / `verify_password`）。
- **Decision 3.1**: REST 风格，`POST /api/v1/auth/change-password`、`POST /api/v1/auth/logout`。
- **Decision 3.3**: 统一错误响应结构 `{"error": {"code": "...", "message": "..."}}`。
- **API Boundaries**: `/api/v1/auth/*` 为公开 API（logout 端点是公开的，change-password 需要 JWT）。

### 2. Token 黑名单设计

```python
# Redis Key 设计

# 单个 token 撤销（登出时使用）
auth:revoked:{token_hash}    # STRING user_id, TTL = token 剩余秒数
# token_hash = SHA256(token)[:16]（16 字符足以唯一标识）

# 用户级全部 token 撤销（密码修改时使用）
auth:revoked:user:{user_id}  # STRING timestamp, TTL = REFRESH_TOKEN_EXPIRE_DAYS 天

# 判断 token 是否被撤销：
# 1. 检查 auth:revoked:{token_hash} 是否存在 → revoked
# 2. 解析 token 获取 user_id + iat
# 3. 检查 auth:revoked:user:{user_id} 是否存在
# 4. 如果存在且其 timestamp > token.iat → revoked（ilat 之后才发的全局撤销）
# 5. 否则有效
```

### 3. AuthService 扩展方法签名

```python
@staticmethod
async def change_password(user_id: str, current_password: str, new_password: str) -> None:
    """修改当前用户密码。修改后使该用户所有 refresh_token 失效。"""

@staticmethod
async def logout(refresh_token: str) -> None:
    """将 refresh_token 加入黑名单。幂等，无效 token 也返回成功。"""

@staticmethod
async def _invalidate_refresh_token(token: str) -> None:
    """将单个 refresh_token 加入黑名单。"""

@staticmethod
async def _invalidate_all_refresh_tokens(user_id: str) -> None:
    """使指定用户的所有 refresh_token 失效。"""

@staticmethod
async def _is_token_revoked(token: str) -> bool:
    """检查 refresh_token 是否已被撤销。"""
```

### 4. 需要修改的现有方法

- **`AuthService.refresh_token`**（`app/services/auth_service.py`）：在 `decode_token` 之后新增黑名单检查
  ```python
  payload = decode_token(refresh_token)
  # NEW: 黑名单检查
  if await AuthService._is_token_revoked(refresh_token):
      raise UnauthorizedError(code="TOKEN_REVOKED", message="Token has been revoked")
  ```

### 5. 安全注意事项

- **密码修改后全量 token 失效**：防止修改密码后旧 token 仍可用（安全最佳实践）
- **登出幂等**：重复登出、无效 token 登出都返回 200，不泄漏 token 有效性
- **`auth:revoked:user:{user_id}` 的 TTL**：设置为 `REFRESH_TOKEN_EXPIRE_DAYS` 天，确保覆盖所有可能仍存活的 token
- **日志脱敏**：绝不记录 password 或 token 内容；token hash 前缀（前 8 字符）可用于审计关联

### 6. 文件清单（NEW / UPDATE）

| 操作 | 文件路径 | 说明 |
|------|----------|------|
| UPDATE | `backend/app/schemas/auth.py` | 新增 ChangePasswordRequest / LogoutRequest / MessageResponse |
| UPDATE | `backend/app/services/auth_service.py` | 新增 change_password / logout / token 黑名单方法；修改 refresh_token |
| UPDATE | `backend/app/api/v1/auth.py` | 新增 change-password / logout 路由 |
| UPDATE | `backend/tests/services/test_auth_service.py` | 新增 10 个测试 |
| UPDATE | `backend/tests/api/test_auth.py` | 新增 6 个测试 |

### 7. 依赖方向

```
api/v1/auth.py → services/auth_service + schemas/auth + core/security
                     ↓
                services/user_service + db/redis + core/security
```

### 8. 来自 Story 1.3/1.4 的可复用资产

- `app.core.security.get_current_user` ✅（JWT 认证 Depends）
- `app.core.security.hash_password / verify_password / validate_password_strength` ✅
- `app.services.user_service.UserService.get_user_by_id / update_last_login` ✅（async）
- `app.db.redis.get_redis_client` ✅（async Redis 客户端）
- `app.schemas.auth.TokenResponse` ✅
- `app.services.auth_service.AuthService.login / refresh_token` ✅（需修改 refresh_token）
- Redis key `auth:*` 命名约定 ✅（Story 1.3 已确立）

### 9. Redis Key 命名延续

延续 Story 1.3 的 `auth:*` 命名空间：
```
auth:failed:{username}         # Story 1.3 — 失败计数
auth:locked:{username}         # Story 1.3 — 账户锁定
auth:revoked:{token_hash}      # NEW — 单 token 黑名单
auth:revoked:user:{user_id}    # NEW — 用户级全部 token 失效
```

### 10. 与前端交互说明

- **登出流程**：前端调用 `POST /api/v1/auth/logout`（携带 refresh_token）→ 后端黑名单 → 前端清除本地 token store → 跳转登录页
- **密码修改**：前端调用 `POST /api/v1/auth/change-password`（Bearer token 认证）→ 成功后清除本地 token → 跳转登录页
- **401 处理**：前端 axios interceptor 收到 `TOKEN_REVOKED` 错误时，也应清除本地 token 并跳转登录页（同 TOKEN_EXPIRED / TOKEN_INVALID）

### References

- [Source: docs/planning-artifacts/architecture.md#Decision-2.1] — JWT 认证（access + refresh）
- [Source: docs/planning-artifacts/architecture.md#Authentication-Flow] — 登出流程（line 834）
- [Source: docs/planning-artifacts/architecture.md#API-Boundaries] — `/api/v1/auth/*` 边界
- [Source: docs/planning-artifacts/architecture.md#Decision-2.4] — bcrypt 密码哈希
- [Source: docs/planning-artifacts/architecture.md#Decision-3.3] — 统一错误响应结构
- [Source: docs/planning-artifacts/prds/prd-agent-flow-2026-06-05/prd.md#FR-27] — 用户认证与角色管理
- [Source: docs/planning-artifacts/epics.md] — Epic 1: 用户认证与权限管理
- [Source: docs/implementation-artifacts/1-3-user-login-jwt-auth.md] — Story 1.3 JWT 认证实现（复用资产）
- [Source: docs/implementation-artifacts/1-4-user-management-and-rbac.md] — Story 1.4 RBAC + 审计日志

---

## Dev Agent Record

### Agent Model Used

- deepseek-v4-flash (Claude Code)

### Debug Log References

- Ruff F401 修复：`from app.core.config import settings` 在 `_invalidate_refresh_token` 中未使用（仅在 `_invalidate_all_refresh_tokens` 中使用），已移除。

### Completion Notes List

- **T1**: Schema 定义完成。在 `app/schemas/auth.py` 新增 `ChangePasswordRequest`、`LogoutRequest`、`MessageResponse`。
- **T2**: `AuthService.change_password()` 实现完成，包含当前密码验证、新密码强度检查、bcrypt 哈希更新、全量 token 失效。
- **T3**: Token 黑名单机制完全实现。单 token 撤销（`auth:revoked:{hash}`）和用户级撤销（`auth:revoked:user:{id}`）双模式。`refresh_token()` 方法已添加黑名单检查。
- **T4**: `AuthService.logout()` 实现完成，幂等设计（无效 token 也返回成功）。
- **T5**: API 路由 `POST /auth/change-password`（需 JWT）和 `POST /auth/logout`（公开）实现完成。
- **T6**: 16 个新测试（10 个 service + 6 个 API），覆盖所有 AC 和边界情况。修复 `mock_redis` fixture 默认返回 `None`，修复 `mock_user_service` 支持 `_collection()`。
- **T7**: 152 pytest 全通过，ruff 零错误，mypy 零问题，OpenAPI 文档正常显示新端点。

### File List

| 操作 | 文件路径 |
|------|----------|
| UPDATE | `backend/app/schemas/auth.py` |
| UPDATE | `backend/app/services/auth_service.py` |
| UPDATE | `backend/app/api/v1/auth.py` |
| UPDATE | `backend/tests/services/test_auth_service.py` |
| UPDATE | `backend/tests/api/test_auth.py` |
| UPDATE | `docs/implementation-artifacts/sprint-status.yaml` |
