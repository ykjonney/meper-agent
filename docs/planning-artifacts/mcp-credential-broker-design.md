# MCP 凭证经纪设计（Credential Broker v3 — 平台用户归一方案）

> 日期：2026-08-13（v3 重构）
> 状态：方案已确认，待实施
> 关联：[`agent-access-hub.html`](./agent-access-hub.html)（用户授权页 Mock）

---

## 0. 文档目的

定义外部用户通过 Agent 访问 MCP 服务时的**身份识别**、**凭证解析**与**跨域穿透**机制。

核心目标：
- **身份归一**——不管用户从哪个接入方进来，都能识别为同一个平台用户
- **跨域 MCP 穿透**——从 A 服务进来，也能访问 B 服务的 MCP（只要用户绑了 B 的凭证）
- **绑定自服务**——用户自己在平台设置页绑凭证，绑定时自动建立身份映射
- **系统不关心域判定**——所有 MCP 都必须在组里，没有降级，没有 fallback token

---

## 1. 核心问题与方案

### 1.1 v1/v2 的问题

| 版本 | 机制 | 核心缺陷 |
|---|---|---|
| v1（MEPER 自签 token） | 本地查 `mcp_token_credentials` | admin 手工代绑，不可规模化；user_id 绑死在 token 上 |
| v2（`owner:sub` 拼接） | introspection → `user_id = owner:sub` | **跨域身份碎片化**：从 A 进来 user_id=`owner:alice_a`，从 B 进来 user_id=`owner:alice_b`，同一个人绑定关系断裂 |

### 1.2 v3 方案：平台用户归一

**核心思路：引入 `external_identities` 映射表，把各接入方的 sub 归一到同一个平台用户。**

```
同一物理人 alice：
  在 A 服务的 sub = "zhangsan:1001"  ──┐
  在 B 服务的 sub = "zs:1001"        ──┼──→  platform_user_id = "user_001"
                                       │
  user_001 名下持有所有组的凭证 ←──────┘

无论从 A 还是 B 进来，都归一到 user_001，凭证都能查到。
```

**sub 的来源不是用户手填，而是绑账密时从 `login_url` 响应自动提取：**

```
introspection 响应：{ active, sub: "1001", username: "zhangsan", exp }
login_url 响应：    { token: "xxx", userId: "1001", userName: "zhangsan" }

两边都含用户 ID + 用户名 → 按固定规则组合（如 "username:userId" = "zhangsan:1001"）
→ 写入 external_identities
```

---

## 2. 数据模型

### 2.1 `external_identities`（新建）

外部身份 → 平台用户的映射。绑账密时自动生成。

| 字段 | 类型 | 说明 |
|---|---|---|
| `_id` | str | `extid_xxx` |
| `sub` | str | 用户标识组合（`username:userId`），全局唯一 |
| `platform_user_id` | str | 关联平台 User 的 `_id`（`user_xxx`） |
| `created_at` / `updated_at` | str | ISO 时间 |

**唯一索引**：`sub`（sub 跨用户全局唯一，靠 userId+username 组合保证）

**sub 组合规则**（代码写死，暂不做可配置）：
- introspection 返回 `sub`（= userId）+ `username`
- login_url 返回 `userId` + `userName`
- 两边组合格式一致：`f"{username}:{userId}"`

### 2.2 `user_mcp_credentials`（改造，原 `mcp_token_credentials`）

用户自绑的跨域凭证。**按平台用户存，一个用户一条记录。**

| 字段 | 类型 | 说明 |
|---|---|---|
| `_id` | str | `usermcp_xxx` |
| `platform_user_id` | str | 平台用户 `_id` |
| `group_bindings` | dict | key = `mcp_group_id`，value = 凭证对象 |
| `created_at` / `updated_at` | str | ISO 时间 |

**group_bindings 结构**（只有账密）：

```jsonc
{
  "mcpgrp_aaa": {
    "username": "enc:xxxxxx",    // AES-256-GCM 加密
    "password": "enc:xxxxxx"
  }
}
```

**唯一索引**：`platform_user_id`

**与 v1 的差异**：
- 删除 `token`（不再自签通用 token）
- 删除 `api_key_id`（凭证跟平台用户走）
- 删除 `credential_type`（只有账密）
- `mcp_bindings`（per-MCP）→ `group_bindings`（per-Group）
- 查询 key 从 `token` 改为 `platform_user_id`

### 2.3 `mcp_groups`（复用现有 `mcp_categories` 扩展）

在现有 `McpCategory`（UI 分组）基础上，增加凭证相关字段，让它同时承担"身份域分组 + 共享登录配置"的职责。

| 字段 | 类型 | 说明 |
|---|---|---|
| `_id` | str | `mcpgrp_xxx`（现 `mcpc_xxx`，前缀可保留或迁移） |
| `name` | str | 组名（现有） |
| `description` | str | 描述（现有） |
| `sort` | int | 排序权重（现有） |
| `login_config` | dict | **新增**：共享登录配置 |
| `auth_type` | str | **新增**：session 注入方式 `bearer_token` / `api_key` / `basic` |
| `header_name` | str | **新增**：`api_key` 型的自定义 header 名，默认 `X-API-Key` |
| `created_at` / `updated_at` | str | 现有 |

**MCP 与组的关联**：通过 `McpConnection.category_id` 反查（一个 MCP 属于一个组）。**所有 MCP 都必须在组里**——不在任何组的 MCP 被调用时返回错误（配置不完整）。

**login_config 结构**：

```jsonc
{
  "login_url": "https://factory.example.com/api/login",
  "method": "POST",
  "username_field": "username",       // 请求体字段名（默认 username）
  "password_field": "password",       // 请求体字段名（默认 password）
  "token_jsonpath": "data.token",     // 从响应取 session token 的 JSONPath
  "userid_jsonpath": "userId",        // 从响应取 userId 的 JSONPath（用于组合 sub）
  "username_jsonpath": "userName",    // 从响应取 userName 的 JSONPath（用于组合 sub）
  "session_ttl": 7200                 // session 缓存秒数
}
```

> **与现有 McpConnection.login_config 的关系**：McpConnection 上现有的 `login_config` 迁移到 McpGroup。McpConnection 不再持有 login_config。

### 2.4 `McpConnection` 变更

| 字段 | 处理 |
|---|---|
| `category_id` | **保留**（现有，指向所属组） |
| `login_config` | **迁移到 McpGroup**（数据迁移） |
| 其他字段 | 不变（内部路径仍用 `auth_config` 静态凭证） |

### 2.5 `ApiKey` 扩展

新增 introspection 端点配置：

| 字段 | 类型 | 说明 |
|---|---|---|
| `introspect_url` | str \| None | 接入方的 token introspection 端点 |

> 不需要 `introspect_token`。旧版实现（`user_auth_service.py`）是裸调 introspection 端点（POST form-encoded `token=xxx`，无 Authorization 头），新版沿用。

introspection 请求（复用旧版 `UserAuthService`，RFC 7662 简化版）：

```
POST {introspect_url}
Content-Type: application/x-www-form-urlencoded

token={接入方token}
```

响应：

```json
{
  "active": true,
  "sub": "1001",
  "username": "zhangsan",
  "exp": 1693440000
}
```

> `sub`（接入方用户 ID）+ `username` 组合为 `f"{username}:{sub}"`，用于查 `external_identities`。

---

## 3. 完整调用链路

### 3.1 配置阶段（用户在平台设置页，一次性操作）

```
用户登录平台（平台 JWT，user_001）
  │
  设置页 → 绑 group_b 的账密：
    填 username: "zs001", password: "yyy"
    │
    系统调 group_b.login_url：
      POST login_url { username: "zs001", password: "yyy" }
      │
      ├─ 登录失败 → 报错，不保存
      └─ 登录成功，响应：
           { token: "session_xxx", userId: "1001", userName: "zhangsan", ... }
           │
           ├─ ① 提取 userId + userName → 组合 sub = "zhangsan:1001"
           │   → external_identities 写入 { sub, platform_user_id: "user_001" }
           │     （如果已存在相同 sub → 不重复写入）
           │
           └─ ② 账密加密存入
                 user_mcp_credentials.group_bindings["group_b"]
                 = { username: enc("zs001"), password: enc("yyy") }
```

### 3.2 运行时：从 client 发起到 MCP 调用

```
[浏览器宿主页]
  chat-widget.js: resolveUserToken()
    → 读 cookie "x-mep-token" → 接入方 token
    ↓ postMessage(agentflow:config, { apiKey: "af_live_xxx", userToken: <接入方token> })

[iframe: frontend-client]
  发请求 header：
    Authorization: Bearer af_live_xxx       ← 接入方 API Key
    X-User-Token: <接入方token>              ← 用户在接入方的 token
  POST /api/v1/ext/agents/{agent_id}/invoke/stream

[backend — 鉴权阶段]
  get_api_key_principal（auth_apikey.py）
    │
    ├─ ① 校验 API Key → owner_user_id
    │
    ├─ ② introspection（★ 改造：替代本地 verify_token）
    │    POST ApiKey.introspect_url, form: token=<接入方token>
    │    → { active: true, sub: "1001", username: "zhangsan" }
    │    → 组合 sub = "zhangsan:1001"
    │
    ├─ ③ 登录时检查（★ 新增）
    │    external_identities.findOne({ sub: "zhangsan:1001" })
    │    ├─ 不存在 → 401 "未绑定平台身份，请先在设置页绑定 MCP 凭证"
    │    └─ 存在 → platform_user_id = "user_001"
    │
    └─ principal.user_id = "user_001"
       principal.token_record_id = "user_001"
       principal.user_token = <接入方token>     ← 保留原始 token

[backend — Agent 执行]
  AgentExecutionService.stream(agent_id, user_id="user_001", user_token=<接入方token>)
    │
    ↓ resolve_harness_context（context.py）
      set_user_token_context(<接入方token>)
      set_token_record_id_context("user_001")     ← 平台用户 ID
      加载 Agent 配置的 MCP 工具（interceptor 已挂载）

[backend — LLM 调 MCP，interceptor 拦截]
  _user_token_interceptor（loader.py）
    record_id = get_token_record_id_context()  → "user_001"（非空 = 外部路径）
    server_name = request.server_name          → "B服务MCP"
    │
    └─ cred = await _resolver.resolve("user_001", "B服务MCP")

[backend — 凭证解析 resolve（★ 改造重点）]
  UserCredentialResolver.resolve(platform_user_id, server_name)
    │
    ├─ ① server_name → conn_id（按 name 查 mcp_connections）
    │
    ├─ ② conn_id → 属于哪个组（查 mcp_categories，category_id 匹配）
    │    ├─ 不在任何组 → 返回 None（配置不完整 → isError）
    │    └─ 找到组 group_b → 继续
    │
    ├─ ③ 查用户对该组的绑定
    │    user_mcp_credentials.findOne({ platform_user_id: "user_001" })
    │    → group_bindings["group_b"]
    │    ├─ 没绑定 → 返回 None（interceptor 生成 isError 结果给 Agent）
    │    └─ 有绑定 → 解密账密 → 继续
    │
    ├─ ④ 查/换 session（Redis 缓存）
    │    cache_key = "mcp:session:user_001:group_b"
    │    ├─ Redis 命中 → 用缓存 session
    │    └─ miss → 用 group_b.login_config + 账密 POST login_url 换 session
    │              → 写 Redis（TTL = session_ttl）
    │
    └─ return { auth_type: group_b.auth_type, token: session, header_name: group_b.header_name }

[backend — 凭证注入 MCP 请求]
  _cred_to_headers(cred)
    bearer_token → { "Authorization": "Bearer <session>" }
    api_key      → { "<header_name>": "<session>" }
  request.override(headers=headers) → handler(overridden)

[MCP server] 收到带 session 的请求 → 认证 → 返回结果
  ↓ 结果回流 → ToolMessage → SSE → iframe 渲染
```

### 3.3 两种"未绑定"的处理（关键区别）

| | 登录时检查 | 执行 MCP 时检查 |
|---|---|---|
| **位置** | `get_api_key_principal`（鉴权阶段） | `_user_token_interceptor` → `resolve` |
| **检查什么** | 当前 sub 有没有身份映射 | 用户有没有绑这个组的凭证 |
| **查什么表** | `external_identities` | `user_mcp_credentials.group_bindings` |
| **不通过时** | **401 拒绝整个请求** | 返回 isError 的 CallToolResult 给 Agent |
| **影响范围** | 整个会话进不来 | 单个 MCP 工具调用失败，**不阻断对话** |
| **原因** | 没有 platform_user_id，后续全断 | 只是一个工具没权限，其他工具不受影响 |

---

## 4. 身份识别（Introspection 回调）

### 4.1 流程

```
client 请求 (Authorization: af_live_xxx, X-User-Token: <接入方token>)
  │
  ├─ API Key 校验 → owner_user_id + introspect_url
  │
  ├─ introspection(X-User-Token)
  │   ├─ Redis 缓存（复用旧版 introspection_cache，两级缓存 fresh + stale）
  │   └─ miss → POST introspect_url → { active, sub, username, exp } → 缓存
  │
  ├─ active=false → 401
  ├─ active=true → sub + username → 组合 → "zhangsan:1001"
  │
  └─ 查 external_identities["zhangsan:1001"]
      ├─ 不存在 → 401
      └─ 存在 → platform_user_id
```

### 4.2 复用旧版基础设施

| 组件 | 状态 | 说明 |
|---|---|---|
| `UserAuthService`（`user_auth_service.py`） | **恢复使用** | RFC 7662 introspection 客户端，含 stale fallback |
| `introspection_cache`（`introspection_cache.py`） | **恢复使用** | 两级 Redis 缓存（fresh + stale），减少回调 |
| `McpTokenCredentialService.verify_token` | **废弃** | 本地 meper_token 校验，被 introspection 替代 |
| `get_api_key_principal` 中的本地校验 | **替换** | 改为 introspection + external_identities 查询 |

### 4.3 `get_api_key_principal` 改造（`auth_apikey.py`）

```python
# ① API Key 验证（不变）
doc = await ApiKeyService.verify_key(full_key)

# ② X-User-Token → introspection（替代 v1 的本地 token 校验）
user_token = _extract_bearer_token(request.headers.get("X-User-Token"))
if not user_token:
    raise UnauthorizedError(code="EXT_USER_TOKEN_MISSING")

introspect_url = doc.get("introspect_url")
if not introspect_url:
    raise UnauthorizedError(code="INTROSPECT_URL_NOT_CONFIGURED")

result = await UserAuthService.introspect(introspect_url, user_token)
if not result.active:
    raise UnauthorizedError(code="EXT_USER_TOKEN_INVALID")

# ③ 组合 sub
sub = f"{result.username}:{result.sub}"

# ④ 登录时检查：查 external_identities
identity = await ExternalIdentityService.find_by_sub(sub)
if identity is None:
    raise UnauthorizedError(
        code="EXT_USER_NOT_BOUND",
        message="未绑定平台身份，请先在设置页绑定 MCP 凭证",
    )

# ⑤ 设身份
principal.user_id = identity["platform_user_id"]
principal.token_record_id = identity["platform_user_id"]
principal.user_token = user_token  # 保留原始 token
```

---

## 5. 凭证解析流程

### 5.1 核心逻辑

```python
async def resolve(platform_user_id, server_name):
    """Agent 调 MCP 前的凭证解析。"""

    # 1. server_name → mcp_connection_id
    conn_id = await get_connection_id_by_name(server_name)

    # 2. 查 MCP-X 属于哪个组（通过 category_id 反查）
    group = await find_group_by_connection(conn_id)

    # 3. 没有组 → 配置不完整，返回 None（interceptor 生成 isError 给 Agent）
    if group is None:
        return None

    # 4. 查用户对该组的绑定
    binding = await UserMcpCredentialService.get_binding(platform_user_id, group.id)

    # 5. 没绑定 → 返回 None（interceptor 生成 isError 给 Agent）
    if binding is None:
        return None

    # 6. 有绑定 → Redis 查 session
    cache_key = f"mcp:session:{platform_user_id}:{group.id}"
    session = await redis.get(cache_key)

    if session is None:
        # 7. miss → 用 username/password 换 session
        session = await exchange_session(group.login_config, binding)
        await redis.setex(cache_key, group.login_config["session_ttl"], session)

    # 8. 按 group.auth_type 注入
    return {"auth_type": group.auth_type, "token": session,
            "header_name": group.header_name}
```

### 5.2 harness 层改造

#### CredentialResolver Protocol 改参数名

```python
# packages/harness/.../credential_resolver.py
class CredentialResolver(Protocol):
    async def resolve(
        self,
        platform_user_id: str,    # 平台用户 ID（原 token_record_id，只改名）
        server_name: str,         # MCP 连接名
    ) -> dict[str, Any] | None:
        ...
```

> 现状签名是 `resolve(token_record_id, server_name)`，只改第一个参数名为 `platform_user_id`。不加 fallback_token，不需要降级。

#### interceptor 改造（`loader.py`）

```python
async def _user_token_interceptor(request, handler):
    platform_user_id = get_token_record_id_context()

    # 内部路径（platform_user_id 为空）→ 不介入
    if not platform_user_id or _resolver is None:
        return await handler(request)

    server_name = getattr(request, "server_name", "") or ""
    cred = await _resolver.resolve(platform_user_id, server_name)

    if cred is None:
        # 未绑定 / MCP 不在任何组 → 返回 isError 给 Agent（不阻断对话）
        return _make_error_result(f"用户未绑定该 MCP 服务({server_name})，请在设置页绑定")

    headers = _cred_to_headers(cred)
    if not headers:
        return await handler(request)

    overridden = request.override(headers=headers)
    return await handler(overridden)
```

> **关键变化**：
> - `fallback_token` 从 ContextVar 取（`get_user_token_context`），作为参数传入
> - 未绑定返回 isError（现状已是此行为，不变）
> - MCP 不在任何组时用 fallback_token（新增降级逻辑，在 resolve 内部处理）

### 5.3 session 缓存

| 维度 | 值 |
|---|---|
| Redis key | `mcp:session:{platform_user_id}:{mcp_group_id}` |
| TTL | `group.login_config.session_ttl` |
| 失效时机 | 用户改绑 / admin 改组 login_config |
| 清理 | service 层在 update/delete 时联动清缓存（SCAN `{platform_user_id}:*`） |

---

## 6. sub 组合规则（代码写死）

introspection 和 login_url 返回的用户信息按固定规则组合成 sub，确保两边对上：

```python
# 固定组合规则（代码写死，不做可配置）
def compose_sub(username: str, user_id: str) -> str:
    return f"{username}:{user_id}"
```

**introspection 响应 → sub**：
```python
result = await UserAuthService.introspect(introspect_url, user_token)
sub = compose_sub(result.username, result.sub)
```

**login_url 响应 → sub**（绑账密时）：
```python
login_resp = await do_login(group.login_config, username, password)
user_id = extract_jsonpath(login_resp, group.login_config["userid_jsonpath"])
user_name = extract_jsonpath(login_resp, group.login_config["username_jsonpath"])
sub = compose_sub(user_name, user_id)
```

两边组合规则一致 → 同一个用户在同一次绑定时建立的 sub，和运行时 introspection 返回的组合结果相同。

---

## 7. API 设计

### 7.1 admin API — MCP 分组管理（`/api/v1/mcp-categories`，平台 JWT）

> 复用已实现的 `mcp_categories` API，扩展 `login_config` / `auth_type` / `header_name` 字段的 CRUD。

### 7.2 用户自服务 API — 凭证绑定（`/api/v1/my-mcp-credentials`）

用户登录平台后，自行管理跨域 MCP 组的凭证绑定。**绑定时自动建立 external_identities 映射。**

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/my-mcp-credentials` | 查看自己已绑定的组（凭证 mask） |
| GET | `/my-mcp-credentials/available-groups` | 查看可绑定的 MCP 组列表 |
| PUT | `/my-mcp-credentials/{group_id}` | 绑定/更新某组的账密（★ 调 login_url 验证 + 提取 sub + 写映射） |
| DELETE | `/my-mcp-credentials/{group_id}` | 解绑某组（★ 同时删 external_identities 对应 sub） |

**鉴权**：平台 JWT（`get_current_user`），`user.id` = `platform_user_id`。

**PUT 绑定时内部流程**：
```
1. 从 group 拿 login_config
2. 调 login_url（验证账密）
3. 失败 → 返回错误
4. 成功 → 提取 userId + userName → 组合 sub
5. 写 external_identities（sub → platform_user_id）
6. 加密账密 → 写 user_mcp_credentials.group_bindings[group_id]
7. 清该组的 session 缓存
```

### 7.3 admin API — 用户凭证代管（`/api/v1/mcp-credentials`，平台 JWT，admin only）

admin 可代用户绑定凭证（批量上线场景）。

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/mcp-credentials?platform_user_id=xxx` | 查看某用户的绑定 |
| PUT | `/mcp-credentials/{platform_user_id}/{group_id}` | 代用户绑定（同样调 login_url 验证） |
| DELETE | `/mcp-credentials/{platform_user_id}/{group_id}` | 代用户解绑 |

---

## 8. 前端变更

### 8.1 `chat-widget.js` — 删除登录面板

回到纯 cookie 方案：
- 删除 `loginPanel` / `loginInput` / `loginButton` 相关逻辑
- `resolveUserToken()`：只读 cookie `x-mep-token`
- 清理 `config.userToken` 注入渠道 + `token_invalid` 消息监听联动
- 用户零操作

### 8.2 frontend-studio — MCP 凭证设置页

参考 [`agent-access-hub.html`](./agent-access-hub.html) Mock，新增设置页：
- **路由**：`/settings/mcp-credentials`
- **功能**：
  - 展示可用的 MCP 组卡片（组名、包含的 MCP、认证方式）
  - 用户点击组卡片 → 弹窗填 username/password → 绑定
  - 绑定时前端调 PUT `/my-mcp-credentials/{group_id}`
  - 已绑定的组显示状态 + "重新认证" / "解绑" 按钮
- **数据源**：`GET /my-mcp-credentials/available-groups` + `GET /my-mcp-credentials`

---

## 9. 复用 / 新建 / 废弃 总表

| 能力 | 处理 |
|---|---|
| 内部路径 `/v1/agents/*` + 平台 JWT | **不变** |
| 外部路径 `/ext/*` + API Key | **复用**（接入方维度不变） |
| MCP header 构造（bearer/api_key/basic） | **复用** `loader.py:_cred_to_headers` |
| 凭证加解密 `enc:` + AES-256-GCM | **复用** `app/core/crypto.py` |
| ContextVar + interceptor 管道 | **复用管道，改 interceptor 参数名（token_record_id → platform_user_id）** |
| 旧版 `UserAuthService` + `introspection_cache` | **恢复使用**（v1 废弃了，v3 重新启用） |
| v1 的 `meper_xxx` 自签 token | **废弃** |
| v1 的 `mcp_token_credentials` 模型 | **改造**为 `user_mcp_credentials`（改 group_bindings，查询 key 改 platform_user_id） |
| v1 的 `verify_token` 本地校验 | **废弃**（被 introspection 替代） |
| v1 的 `McpTokenCredentialService` | **改造**为 `UserMcpCredentialService` |
| McpConnection 的 `login_config` | **迁移到 McpGroup** |
| 现有 `McpCategory`（mcp_categories） | **扩展**（加 login_config/auth_type/header_name，承担 MCP 组职责） |
| `external_identities` | **新建**（sub → platform_user_id 映射） |
| `ApiKey.introspect_url` | **新增** |
| 用户自服务绑定 API `/my-mcp-credentials` | **新建** |
| `chat-widget.js` 登录面板 | **删除**（回到纯 cookie） |
| studio 凭证设置页 | **新建** |

---

## 10. 分阶段任务拆解

### 阶段 1：身份识别 + 基础模型

1. **`external_identities` 模型 + service**
   - `models/external_identity.py`、`services/external_identity_service.py`
   - `find_by_sub(sub)` → 返回 platform_user_id
2. **`ApiKey` 加 `introspect_url`**
3. **恢复 `UserAuthService` + introspection_cache 到主链路**
4. **`get_api_key_principal` 改造**：verify_token → introspection → sub 组合 → external_identities 查询
   - **登录时检查**：映射不存在 → 401
5. **sub 组合规则函数**（代码写死 `compose_sub`）
6. **验收**：外部请求 → introspection → sub → external_identities → platform_user_id 正确解析

### 阶段 2：MCP 组 + 凭证模型

7. **`McpCategory` 扩展**（加 login_config / auth_type / header_name）
8. **McpConnection.login_config 迁移到 McpGroup**（数据迁移）
9. **`user_mcp_credentials` 模型改造**
   - 原 `mcp_token_credentials` → `group_bindings`（per-Group）+ `platform_user_id` 查询键
10. **`UserMcpCredentialService`**
    - `get_binding(platform_user_id, group_id)`
    - 绑定时调 login_url 验证 + 提取 sub + 写 external_identities
11. **验收**：用户绑组凭证 → login_url 验证成功 → external_identities 自动生成

### 阶段 3：凭证解析器

12. **harness `CredentialResolver` 改参数**（加 `fallback_token`）
13. **harness interceptor 改**（取 fallback_token，MCP 不在组时降级）
14. **app `UserCredentialResolver` 改造**
    - server_name → conn_id → category_id → group → group_bindings
    - 不在任何组 → 用 fallback_token
    - 在组里没绑 → 返回 None（interceptor 生成 isError）
    - 在组里绑了 → 换 session（Redis 缓存 + group.login_config）
15. **验收 1**：同域 MCP（不在组里）→ 接入方 token 直传 ✓
16. **验收 2**：跨域 MCP（在组里）+ 用户已绑 → session 换取 ✓
17. **验收 3**：跨域 MCP（在组里）+ 用户未绑 → isError 给 Agent ✓
18. **验收 4**：从 A 进来调 B 的 MCP → 跨域穿透 ✓

### 阶段 4：前端

19. **`chat-widget.js` 删登录面板**
20. **studio MCP 凭证设置页**（参考 agent-access-hub.html）
21. **用户自服务 API** `/api/v1/my-mcp-credentials`
22. **验收**：用户在设置页绑组 → 调 agent → 跨域 MCP 可访问 ✓

### 阶段 5：Workflow 路径打通

23. Workflow 节点执行时 `token_record_id_context` 注入适配（platform_user_id）
24. **验收**：外部触发 Workflow → 凭证解析正常 ✓

---

## 11. 默认决策

| 决策点 | 选择 | 理由 |
|---|---|---|
| 身份识别 | introspection 回调 | 用户零操作，接入方已有 token |
| 身份归一 | external_identities（sub → platform_user_id） | 跨域穿透的核心 |
| sub 来源 | 绑账密时从 login_url 响应自动提取 | 用户不手填 sub |
| sub 组合规则 | `username:userId`（代码写死） | introspection 和 login_url 两边对上 |
| sub 唯一性 | 唯一索引兜底 | userId+username 组合保证跨用户不撞名 |
| 凭证类型 | 只有账密 | 用账密换 session 调 MCP |
| 凭证归属 | `platform_user_id` | 跟平台用户走，跨域穿透 |
| 凭证粒度 | per-Group | 同身份域 MCP 归一组，一次绑定整组通用 |
| MCP 组 | 复用 McpCategory 扩展 | 避免两套分组概念打架 |
| 未绑定（登录时） | 401 拒绝 | 没有 platform_user_id 后续全断 |
| 未绑定（执行 MCP 时） | isError 给 Agent | 单个工具失败，不阻断对话 |
| 不在任何组的 MCP | isError（配置不完整） | 所有 MCP 都必须在组里，没有降级 |
| session 缓存 | Redis per platform_user per group | 避免每次调用都重登 |
| introspection 缓存 | Redis fresh + stale fallback（复用旧版） | 减少回调压力 + 容灾 |
| 绑定操作 | 用户自服务（平台设置页） | 不依赖 admin 代绑 |

---

## 12. 风险与权衡

### 12.1 introspection 可用性
- 接入方 introspection 端点不可用 → 外部请求全部 401
- **缓解**：Redis 两级缓存（fresh + stale fallback，复用旧版 `introspection_cache`）

### 12.2 sub 组合一致性
- introspection 和 login_url 返回的字段名可能不同 → 组合不出同一个 sub
- **缓解**：`login_config` 上配 `userid_jsonpath` / `username_jsonpath`，指定从哪个路径取；组合规则代码写死保证一致

### 12.3 安全
- 凭证 AES-256-GCM 加密存储（`enc:` 前缀），**不入日志**
- 接入方原始 token 仅内存传递，不落库
- introspection 通过 HTTPS

### 12.4 session 缓存一致性
- 用户改绑 / admin 改组 login_config 时，必须清 Redis session
- service 层在 update/delete 时联动清缓存

### 12.5 向后兼容
- v1 的 `mcp_token_credentials` 需迁移为 `user_mcp_credentials`
- v1 的 `meper_xxx` token 机制废弃，外部鉴权全面切换到 introspection
- **迁移前提**：接入方已提供 introspection 端点；否则外部路径会 401
- McpConnection 的 `login_config` 需迁移到 McpGroup

---

## 13. Client 自助授权（v4.1 增补）

> 解决"未绑定用户必须去 studio 管理后台完成授权"的体验断点。三种能力，
> 一套绑定底座（`UserMcpCredentialService.bind_credential` 不变）：
> 首绑门页（apikey 模式）、运行时按需授权（chat 模式）、jwt 模式授权面板。

### 13.1 鸡生蛋问题与 relaxed 鉴权

未绑定用户在 ext 鉴权链（`authenticate_api_key` ④⑤ 步）就被
401 `EXT_USER_NOT_BOUND` 拒绝，到不了任何授权端点。解法：

- `authenticate_api_key(..., require_bound=False)`：introspection 通过后
  身份映射未建立不抛 401，principal 携带 `ext_username`（introspection
  得到的用户名）。
- `auth_and_rate_limit_allow_unbound`：relaxed 组合依赖（鉴权 + 限流 +
  调用统计与严格版完全一致），仅供 ext 授权端点使用——匿名仍不可达。

### 13.2 ext 授权端点（`/api/v1/ext/my-app-authorizations`）

| 端点 | 鉴权 | 用途 |
|---|---|---|
| `GET /bootstrap` | relaxed | 首绑门页引导（应用信息 + ext_username + bound） |
| `PUT /{app_id}` | relaxed | 绑定/更新账密（首绑门页 + 运行时授权卡片共用） |
| `GET /available-apps` | 完整 | 可授权应用列表（标记 key 应用） |
| `GET /` | 完整 | 脱敏绑定列表 |
| `DELETE /{app_id}` | 完整 | 解绑 |

**PUT 的目标平台账号三选一**：
1. **认领**（`claim_platform_username/password`）：复用平台登录校验
   （锁定检查 / 失败计数 / 停用拒绝，见 `AuthService.verify_platform_credentials`）
   挂到已有平台账号——历史会话/文件延续。仅首次绑定 key 应用时可用
   （已有身份后认领会把凭证挂到别的账号、运行时查不到，403 拒绝）。
2. **已有身份**：`principal.user_id`（更新凭证 / 跨应用按需授权）。
3. **自动开通**：`UserService.ensure_ext_platform_user` 创建 `ext_user`
   角色（空权限）平台账号，username=`ext.{username}.{app_id前8}`，
   随机密码永不外发。

**防冒名规则**：
- key 对应应用：`body.username` 必须等于 `ext_username`（403
  `EXT_USERNAME_MISMATCH`）——introspection 已证明"你是谁"，比 studio
  流程更严。
- 跨应用：username 自由填写，安全性对齐 studio（login_url 验证账密 +
  sub 抢注保护）；但要求已有平台身份（先完成 key 应用首绑）。

### 13.3 运行时按需授权闭环（chat 模式）

```
MCP 工具调用 → resolver 发现未绑定 → 抛 McpCredentialUnbound(app_id, app_name)
  → 拦截器返回 isError 结果：首行 JSON 标记
    {"mcp_credential_error":"UNBOUND","app_id":...,"app_name":...}
    + 文案「请调 request_app_authorization；禁止向用户索要凭证」
  → LLM 调 request_app_authorization(app_id, app_name)
  → interrupt({type:"app_authorization",...}) → SSE InterruptEvent
    (kind=app_authorization) → 前端渲染授权表单卡
  → 用户提交 → 前端先调 PUT 绑定（凭证不进对话）→ resume
  → agent 原轮恢复，重试工具 → 成功
```

关键设计：
- **interrupt 契约**：`request_app_authorization` 的 payload 完全由工具
  参数驱动（LLM 从错误标记里读 app_id/app_name），不读 ContextVar——
  LangGraph 要求节点 resume 时确定性重放。
- **ask_clarification 防冲突**（三道防线之二）：本轮消息里存在未消化
  的 UNBOUND 标记时，tool_wrapper 的 `authorization_guard_veto` 拦下
  ask_clarification 并返回纠正性结果（"改用 request_app_authorization，
  禁止索要凭证"）。标记在最近一次 request_app_authorization 结果之后
  才算未消化（防误伤后续正常追问）。基于 state 消息扫描而非 ContextVar
  （LangGraph 节点任务间上下文可能被复制，写入不保证传播）。
- **前端兜底**（三道防线之三）：LLM 未调工具直接文字收尾时，前端解析
  tool_result 错误文本中的 JSON 标记，弹静态授权卡（fallback），提交
  绑定后自动重发最后一条用户消息（非 resume）。
- workflow 模式不注入该工具（无人值守语义，未绑定保持 isError 现状）。

### 13.4 安全要点汇总

- relaxed 端点仍要求：有效 API Key（bcrypt）+ introspection active +
  Redis 限流——匿名不可达
- **密码只走结构化表单 → 绑定 API，永不进入对话/LLM 上下文**
  （错误文本指令 + guard veto + 卡片引导三道防线）
- 认领复用平台登录校验与 Redis 锁定，无法爆破他人平台账号
- 自动开通账号无管理端权限（`ext_user` 空权限），密码不外发

---

## 14. 身份锚点 v4.2：稳定用户 ID + 凭证失效闭环

> 解决"用户在外部系统改用户名/密码后身份漂移"的问题。核心原则：
> **身份锚点用不可变的业务主键，可变的登录名/密码只是凭证。**

### 14.1 锚点规则

- `external_identities.sub = {app_id}:{identity_key}`，`identity_key` 三级优先链：
  1. **key 应用**：introspection 的 `sub`（RFC 7666 标准的稳定用户 ID，
     见 `IntrospectionResult.sub`），缺失时退回 `username`（与 v4.1 行为
     一致，自动降级，无需配置）。
  2. **跨应用/jwt 模式**：登录响应提取的稳定用户 ID——`login_config.userid_jsonpath`
     （默认 `userId`，空串显式禁用；studio 应用编辑页可配）。绑定验证账密时
     `_verify_credentials` 顺带按路径提取，数值型 ID 转字符串；提取不到
     退回登录名（不报错）。
  3. **兜底**：表单登录名（v4.1 行为）。
- `user_mcp_credentials.app_bindings.{app_id}` 新增 `identity_key` 字段
  （明文，非凭证），解绑时据此组 sub 删映射；旧数据无此字段退回 username。
- **登录凭证与身份解耦**：binding 里的 username/password 只用于 login_url
  验证与 session 兑换，改名/改密后变旧 → 兑换失败 → INVALID 闭环（下节）。

### 14.2 存量兼容（在线升级，不全员重绑）

`authenticate_api_key` 双查：
1. `find_by_sub({app}:{stable_id})` —— 新维度
2. miss 且 `stable_id != username` → `find_by_sub({app}:{username})` —— 老 sub
3. 命中老 sub → upsert 新 sub 指向同一 `platform_user_id` + 删除老映射

老用户首次请求即无感迁移；接入方无 sub 字段时 stable_id=username，行为
与 v4.1 完全一致。

### 14.3 凭证失效闭环（INVALID）

```
用户改了外部系统密码/用户名
  → 身份映射不受影响（sub 以稳定 ID 为锚）
  → 存的账密变旧：缓存过期后兑换 session 失败（PermissionError）
  → resolver 包装为 McpCredentialInvalid(app_id, app_name, detail)
  → 拦截器错误标记 mcp_credential_error="INVALID" + 文案
    「凭证已失效…请调 request_app_authorization 请用户更新凭证」
  → LLM 调工具 → interrupt → 前端弹卡（文案提示输入最新凭证）
  → 用户输入新账密 → PUT 绑定（重新验证 + 清 session 缓存）
  → resume → agent 重试工具 → 恢复 ✅
```

与 UNBOUND 共用同一闭环（工具/卡片/前端兜底解析均按
`mcp_credential_error` key 识别，值区分 UNBOUND/INVALID）。

### 14.4 已知局限与运维手册

- **缓存期内旧 session 被外部系统吊销**：MCP server 返回的 401 对拦截器
  不透明，暂不做结构化——靠 session TTL（默认 3600s，可调小
  `login_config.session_ttl`）过期后走 INVALID 闭环。
- **跨应用绑定后该应用独立接入**：跨应用 sub 锚取决于 `userid_jsonpath`
  提取——默认 `userId` 命中登录响应时与 key 应用同级（稳定 ID 锚）；
  未命中退回登录名，该应用后续独立接入且用户已改名时需重绑一次
  （新 sub 指向同一 platform_user_id，凭证重新验证即可，无需运维）。
- **用户名迁移（运维）**：跨应用锚点或接入方无 sub 的存量场景中，用户
  改名导致新身份查不到旧绑定时，admin 可直接修改
  `external_identities`：将老 sub 的 `platform_user_id` 复制到新 sub
  （或改写 sub 字段），即完成迁移；`user_mcp_credentials` 按
  platform_user_id 关联，无需变动。用户随后在授权卡片更新一次凭证即可。
