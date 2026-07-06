# Story 8.2: API Key 管理界面与内部 API

**Epic**: 8 — 外部 API 集成
**状态**: backlog
**依赖**: Story 8.1
**设计文档**: `docs/planning-artifacts/external-api-design.md`

## 用户故事

As a 管理员，
I want 在平台管理界面中创建和管理 API Key，配置权限和资源绑定，
So that 可以控制外部系统的访问范围和能力。

## Acceptance Criteria

### AC-1: API Key CRUD 内部 API

**Given** 管理员持有有效的 JWT access token
**When** 调用以下端点
**Then** 返回预期结果：

```
POST   /api/v1/api-keys          → 创建，返回完整 Key（仅此一次）
GET    /api/v1/api-keys          → 列表（仅展示 key_prefix，不展示完整 Key）
GET    /api/v1/api-keys/{id}     → 详情
PUT    /api/v1/api-keys/{id}     → 更新（name、scopes、bindings、rate_limit、expires_at）
DELETE /api/v1/api-keys/{id}     → 吊销（status → revoked，非物理删除）
```

所有端点需要 `apikey:manage` 权限（仅 admin 角色）。

### AC-2: 创建 API Key 请求体

```json
{
  "name": "MES 产线 A",
  "scopes": ["agents:invoke", "agents:read", "executions:read"],
  "bindings": {
    "agents": ["agent_ulid_1", "agent_ulid_2"],
    "workflows": []
  },
  "rate_limit": 60,
  "expires_at": "2027-01-01T00:00:00Z"
}
```

**Given** 创建请求
**When** 保存成功
**Then** 响应体包含完整 Key 值：
```json
{
  "id": "key_01H...",
  "name": "MES 产线 A",
  "key": "af_live_a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6",
  "key_prefix": "af_live_a1b2",
  "scopes": ["agents:invoke", "agents:read", "executions:read"],
  "bindings": { "agents": ["agent_ulid_1", "agent_ulid_2"], "workflows": [] },
  "rate_limit": 60,
  "status": "active",
  "expires_at": "2027-01-01T00:00:00Z",
  "created_at": "..."
}
```

### AC-3: 列表接口脱敏

**Given** 管理员查看 API Key 列表
**When** 返回数据
**Then** 每个 Key 仅展示 `key_prefix`（前 12 位），不展示完整 Key
**And** 列表按 `created_at` 倒序

### AC-4: 吊销操作

**Given** 管理员点击吊销某个 API Key
**When** 确认操作
**Then** Key 的 `status` 变为 `revoked`
**And** 使用该 Key 的请求立即返回 401 Unauthorized
**And** 吊销不可撤销（需重新创建）

### AC-5: 前端 API Key 管理页面

**Given** 管理员登录平台
**When** 访问 `/api-keys` 页面
**Then** 展示 API Key 列表：名称、前缀、scopes 标签、状态、创建时间、过期时间
**And** 点击"创建 API Key"弹出创建表单：
  - 名称输入框
  - Scopes 多选（checkbox 列表）
  - Agent 绑定多选（从已发布 Agent 列表中选择，可选）
  - Workflow 绑定多选（从已发布 Workflow 列表中选择，可选）
  - Rate Limit 数字输入（默认 60）
  - 过期时间日期选择（可选）
**And** 创建成功后 Modal 展示完整 Key + 复制按钮
**And** Modal 提示"请妥善保存此 Key，关闭后不会再次显示"
**And** 关闭 Modal 后 Key 值不可再查看

### AC-6: 实现文件

**Given** 开发完成
**Then** 以下文件已创建并通过测试：
- `app/api/v1/api_keys.py` — 内部 API 路由（JWT 认证）
- 前端页面组件（`features/api_key_management/`）
