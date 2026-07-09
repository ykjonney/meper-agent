# Story 8.1: API Key 数据模型与认证

**Epic**: 8 — 外部 API 集成
**状态**: backlog
**设计文档**: `docs/planning-artifacts/external-api-design.md`

## 用户故事

As a 平台管理员，
I want 外部系统通过 API Key 认证访问平台能力，
So that 外部集成有独立的认证机制，不依赖用户 JWT 登录。

## Acceptance Criteria

### AC-1: API Key 数据模型

**Given** 平台已部署
**When** 创建 API Key 记录
**Then** MongoDB 中写入以下字段：
- `id`（MongoDB _id）
- `name`（显示名称）
- `key_hash`（bcrypt hash，不存明文）
- `key_prefix`（前 12 位，用于列表展示）
- `owner_user_id`（创建者 user_id）
- `scopes`（权限列表，见下方枚举）
- `bindings`（资源绑定：`agents[]`、`workflows[]`）
- `rate_limit`（每分钟请求上限，默认 60）
- `status`（`active` | `revoked`）
- `expires_at`（可选过期时间）
- `last_used_at`（最后使用时间）
- `created_at`、`updated_at`

### AC-2: API Key 生成规则

**Given** 管理员请求创建 API Key
**When** 生成 Key 值
**Then** 格式为 `af_live_{32位随机字符}`
**And** 完整 Key 仅在创建时返回一次，之后只存储 `key_hash` 和 `key_prefix`
**And** Key 使用 `secrets.token_urlsafe(24)` 生成

### AC-3: Scopes 权限枚举

**Given** API Key 定义了 scopes
**When** 外部系统发起请求
**Then** 系统校验以下 5 种 scope：
- `agents:read` — 查询 Agent 列表和详情
- `agents:invoke` — 调用 Agent（同步/流式）
- `workflows:read` — 查询 Workflow 列表和详情
- `workflows:invoke` — 触发 Workflow
- `executions:read` — 查询 Task 状态和结果

**Given** 请求需要的 scope 不在 API Key 的 scopes 中
**When** 认证校验
**Then** 返回 403 Forbidden，消息 `"API Key 权限不足，需要 {scope} 权限"`

### AC-4: 认证依赖 `get_api_key_principal`

**Given** 外部系统请求头包含 `Authorization: Bearer af_live_xxx`
**When** `get_api_key_principal` 依赖执行
**Then** 解析 Bearer token
**And** 通过 `key_prefix` 快速查找候选 Key（Redis 缓存优先）
**And** bcrypt 验证完整 Key 与 `key_hash` 匹配
**And** 检查 `status == "active"`
**And** 检查 `expires_at` 未过期（如有设置）
**And** 更新 `last_used_at` 时间戳
**And** 返回 `ApiKeyPrincipal` 对象（包含 `key_id`、`scopes`、`bindings`、`owner_user_id`）

**Given** Key 无效、已吊销或已过期
**When** 认证校验
**Then** 返回 401 Unauthorized，消息不透露具体原因（防枚举）

### AC-5: 资源绑定校验

**Given** API Key 配置了 `bindings.agents = ["agent_01"]`
**When** 外部系统请求访问 `agent_02`
**Then** 返回 403 Forbidden，消息 `"API Key 无权访问该 Agent"`

**Given** `bindings.agents` 为空列表
**When** 外部系统请求任意已发布的 Agent
**Then** 允许访问（空 = 不限制）

Workflows 绑定同理。

### AC-6: 实现文件

**Given** 开发完成
**Then** 以下文件已创建并通过测试：
- `app/models/api_key.py` — ApiKey 数据模型
- `app/schemas/api_key.py` — Pydantic schemas
- `app/services/api_key_service.py` — CRUD + 验证逻辑
- `app/core/auth_apikey.py` — `get_api_key_principal` 依赖 + `ApiKeyPrincipal` 类
- `app/core/api_key_cache.py` — Redis 缓存层（key_prefix → 快速查找）
