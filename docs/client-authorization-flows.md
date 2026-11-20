# Client 自助授权 — 全流程目录（v4.2）

> 本文枚举身份锚点 + 自助授权体系下的**所有流程**，含正常路径、边界
> 路径与异常路径。架构设计见 `mcp-credential-broker-design.md` §13/§14。
> 术语：**key 应用** = API Key 绑定的应用（iframe 嵌入方）；**跨应用** =
> agent 工具所属的其他应用；**稳定 ID** = introspection `sub` 或登录响应
> `userId`（`userid_jsonpath` 提取）；**锚** = `external_identities.sub`
> 的 `{app_id}:{identity_key}`。

## 目录

- [A. 鉴权与身份解析](#a-鉴权与身份解析)
- [B. 首次授权（首绑）](#b-首次授权首绑)
- [C. 运行时工具调用（chat 模式）](#c-运行时工具调用chat-模式)
- [D. 侧边栏授权面板](#d-侧边栏授权面板)
- [E. 凭证/用户名变更场景矩阵](#e-凭证用户名变更场景矩阵)
- [F. 异常与边界流程](#f-异常与边界流程)

---

## A. 鉴权与身份解析

### A1. apikey 模式（每个 ext 请求）

```
Authorization: Bearer af_live_xxx + X-User-Token
  │
  ① API Key 校验（bcrypt）────────── 失败 → 401 APIKEY_INVALID
  ② X-User-Token 必填 ────────────── 缺失 → 401 EXT_USER_TOKEN_MISSING
  ③ Key 绑定 app_id + 应用存在 ────── 失败 → 401 APP_ID_MISSING / APP_NOT_FOUND
  ④ introspect_url 已配置 ─────────── 缺失 → 401 INTROSPECT_URL_NOT_CONFIGURED
  ⑤ introspection（Redis fresh/stale 缓存）
  │    inactive / 无 username ─────── → 401 EXT_USER_TOKEN_INVALID
  ⑥ stable_id = sub（优先）or username
  ⑦ 身份解析（双查）：
  │    sub = {app}:{stable_id}
  │    ├─ 命中 ─────────────────────→ user_id = platform_user_id ✓
  │    └─ miss 且 stable_id ≠ username（存量兼容）
  │         查老 sub = {app}:{username}
  │         ├─ 命中 → 在线升级：upsert 新 sub 指向同一 platform_user_id
  │         │         + 删老映射 ───→ ✓（老用户无感迁移）
  │         └─ miss
  │              require_bound=true ─→ 401 EXT_USER_NOT_BOUND → B1 首绑门页
  │              require_bound=false ─→ relaxed 通过（仅授权端点），
  │                                principal 携带 ext_username + ext_user_id
  ⑧ 限流（Redis 滑动窗口）────────── 超限 → 429
```

### A2. jwt 模式（独立部署 client / studio）

```
登录（POST /auth/login）→ JWT access/refresh → 401 自动刷新重试
用户即平台 User，直接调 /my-app-authorizations*（无身份解析问题）
```

---

## B. 首次授权（首绑）

### B1. apikey 首绑门页（401 not_bound 触发）

```
main.tsx 收到 EXT_USER_NOT_BOUND
  → 渲染 BindingGatePage（替代死胡同提示页）
  → GET /ext/my-app-authorizations/bootstrap（relaxed）
       返回 { app: {id, name, has_login_config}, ext_username, bound }
  → 页面：应用名 + 只读账号（= introspection username，锁死防冒名）

  路径①（默认，新用户）：只填外部系统密码
  路径②（折叠展开，老用户）：+ 平台账号 + 平台密码（认领）
        │
        ▼
  PUT /ext/my-app-authorizations/{app_id}（relaxed）
```

**PUT 端点内部流程：**

```
① 应用存在 + login_config 已配置
     否 → 404 APPLICATION_NOT_FOUND / 422 APPLICATION_NO_LOGIN_CONFIG
② key 应用防冒名：body.username == ext_username
     否 → 403 EXT_USERNAME_MISMATCH
③ claim 字段校验（成对出现，否则 422）
④ 目标平台账号解析（三选一）：
   a. 带 claim（仅首次绑 key 应用可用）：
      已有身份 → 403 EXT_CLAIM_NOT_ALLOWED；非 key 应用 → 403
      AuthService.verify_platform_credentials（复用登录校验，只验不发 token）：
        锁定中 ────→ 422 PLATFORM_CREDENTIAL_INVALID（含剩余时间）
        账密错误 ──→ 失败计数（5 次锁 15 分钟，admin 豁免）→ 422
        账号停用 ──→ 422
        通过 ──────→ 挂到该已有账号（历史会话/文件延续）
   b. 已有身份（principal.user_id）→ 挂当前账号（更新凭证/跨应用场景）
   c. 都没有 → 仅 key 应用允许：
      ensure_ext_platform_user(app_id, ext_user_id)
        身份已存在 → 幂等返回
        不存在 ──→ 自动开通 ext_user 账号（空权限、随机密码永不外发、
                   username = ext.{identity_key}.{app前8}）
⑤ bind_credential：
   _verify_credentials：POST login_url 验证账密 + 按 userid_jsonpath
                        （默认 userId）提取稳定用户 ID
     登录失败 ──→ 422 MCP_CREDENTIAL_INVALID
   identity_key 三级优先链：
     ① 显式传入（key 应用 = introspection sub）
     ② 登录响应提取的 userId（跨应用/jwt 模式）
     ③ 表单登录名（兜底）
   upsert sub = {app}:{identity_key}（抢注保护，他人已绑 → 409）
   加密账密 + identity_key 存入 app_bindings
   清 Redis session 缓存
⑥ 成功 → 前端清 authError → 重新 bootstrap → 进入会话
```

### B2. jwt 模式首绑（授权面板）

```
侧边栏「应用授权」→ available-apps 选择应用 → 填 username+password
→ PUT /my-app-authorizations/{app_id}（平台 JWT）
→ bind_credential 同上（identity_key 走 ②登录响应 userId → ③登录名）
```

---

## C. 运行时工具调用（chat 模式）

### C1. 正常路径（已授权且凭证有效）

```
agent 调 MCP 工具 → 拦截器（harness loader）
  ├─ 内部路径（无 token_record_id，如 studio 测试）→ 透传，用连接静态凭证
  └─ 外部路径 → resolver.resolve(platform_user_id, server_name)
       conn 不存在 ────────────→ isError（配置问题）
       auth_type=none ─────────→ 公共放行（免认证连接）
       conn → 反查 app（不在任何应用且需认证 → FORBIDDEN isError，引导找管理员）
       查用户 binding
         无 ──────────────────→ McpCredentialUnbound → C2
       session：Redis 缓存命中 → 直接用
                miss → login_url 兑换（存档账密）
                  失败 ────────→ McpCredentialInvalid → C3
       按 auth_type 注入 header（bearer/api_key/basic）→ 调 MCP → 结果
```

### C2. UNBOUND 闭环（未授权，interrupt 版主路径）

```
拦截器返回 isError，首行 JSON 标记 + 指令文案：
  {"mcp_credential_error":"UNBOUND","app_id":"...","app_name":"..."}
  「请调 request_app_authorization…禁止向用户索要凭证」
    │
    ▼ LLM 遵循指令
request_app_authorization(app_id, app_name, reason)
    → interrupt({type:"app_authorization",...}) 挂起 graph
    → SSE InterruptEvent(kind=app_authorization)
    → 前端聊天流内渲染授权表单卡
    │
    ├─ 用户提交 username+password
    │     → 前端先调 PUT 绑定（凭证不进对话/LLM 上下文）
    │         失败 → 卡片内提示，可重试
    │         成功 → resume（合成 tool_result「授权已完成，请重试」）
    │              → agent 原轮恢复 → 重试工具 → C1 ✓
    │
    └─ 用户点「暂不授权」→ dismiss（合成「用户暂不授权」）
          → agent 优雅降级（解释局限/换路径完成任务）
```

### C3. INVALID 闭环（凭证失效：改了密码/用户名）

同 C2，差异点：

| | C2 UNBOUND | C3 INVALID |
|---|---|---|
| 触发 | binding 不存在 | 兑换 session 失败（PermissionError） |
| 身份 | — | 不受影响（锚 = 稳定 ID） |
| 标记值 | `"UNBOUND"` | `"INVALID"`（detail 带失败原因） |
| 卡片文案 | 「请完成授权后继续」 | 「凭证已失效（可能修改过密码或用户名），请输入最新的」 |

### C4. ask_clarification 防冲突（三道防线之二）

```
本轮消息里存在未消化的凭证错误标记
（= 最近一次 request_app_authorization 结果之后仍有标记）
  → LLM 误调 ask_clarification（索要凭证的倾向）
  → tool_wrapper 的 authorization_guard_veto 拦截
  → 返回纠正性 tool_result：「改用 request_app_authorization，
     禁止通过对话索要账号密码」
  → LLM 自纠 → 回到 C2/C3 正轨
```

三道防线：① 错误文本指令（最可靠通道）→ ② guard veto（本条）→ ③ 前端结构化卡片引导。

### C5. 前端兜底卡（LLM 未调工具，三道防线之三）

```
tool_result(status=error) 的 JSON 标记被前端解析（parseUnboundMarker）
  → 流结束（done）且授权 interrupt 未发生
  → 弹静态授权卡（fallback 模式，errorKind 区分 UNBOUND/INVALID 文案）
  → 用户提交 → PUT 绑定成功
  → 自动重发最后一条用户消息（开新一轮，凭证已就位）
  → 新一轮走 C1 ✓（非 resume——当时 graph 未挂起）
```

### C6. workflow 模式（无人值守）

```
request_app_authorization / ask_clarification 均剥离（execution_context=workflow）
未绑定/凭证失效 → isError 原样返回 LLM → agent 节点按失败分支处理
（合理假设继续 / abort_workflow 诚实终止），不弹卡、不暂停
```

---

## D. 侧边栏授权面板

```
打开（两种模式都有）→ 加载绑定列表（脱敏）+ available-apps
  ├─ 绑定/更新：选应用 → 填账密 → PUT
  │     key 应用（apikey 模式）：username 锁定 ext_username 只读
  │     其他应用：username 自由填写（login_url 验证兜底）
  └─ 解绑：DELETE → 删凭证 + 删身份映射
        解绑 key 应用 → 下次请求 401 not_bound → 回首绑门页（UI 有提示）
```

---

## E. 凭证/用户名变更场景矩阵

| # | 场景 | 身份锚 | 身份 | 用户体验 |
|---|---|---|---|---|
| E1 | key 应用改密码（有 sub） | sub | 不变 | 缓存过期后工具报 INVALID → 聊天内更新 → 恢复 |
| E2 | key 应用改密码（无 sub） | username（未变） | 不变 | 同 E1 |
| E3 | key 应用改用户名（有 sub） | sub | 不变 | 账密里用户名旧 → INVALID → 填新用户名+密码 → 恢复 |
| E4 | key 应用改用户名（无 sub） | username（变了） | **漂移** | 401 → 首绑门页 → 认领（知道平台账密）或自动开新号（老数据割裂 → F6 运维迁移） |
| E5 | 跨应用改密码（有 userId 提取） | userId | 不变 | INVALID 闭环更新 |
| E6 | 跨应用改用户名（有 userId 提取） | userId | 不变 | 重新绑一次：sub 不变、指向同一账号，凭证更新 ✓ |
| E7 | 跨应用改用户名（无 userId 提取） | 登录名 | 换锚 | 新登录名绑定 → 新 sub 指向同一 platform_user_id（老映射成无害死数据）✓ |

补充：**session 缓存期内（默认 3600s）旧凭证被外部系统吊销** → MCP 返回
401，对拦截器不透明 → 等 TTL 过期后走 E1/E5 的 INVALID 闭环（敏感场景
可调小 `login_config.session_ttl`）。

---

## F. 异常与边界流程

### F1. 抢注冲突（409）

```
sub 已被其他平台用户绑定（只有知道该外部账密的人做得到）
→ ExternalIdentityService.upsert 抛 ConflictError → 409
→ 提示「已绑定到其他平台账号，如需转移请先由对方解绑」
并发首绑：两个请求各开一个账号，后到者 409 → 前端提示重试
```

### F2. 认领爆破防护

```
claim 密码错误 → 失败计数（Redis，5 次 / 15 分钟）
→ 锁定期间 claim 一律 422（含剩余时间）
→ admin/超管豁免计数（防爆破锁死管理入口，与登录一致）
```

### F3. relaxed 端点安全性

```
仍要求：有效 API Key（bcrypt）+ introspection active + 限流
匿名 / 无效 Key / 无效 token 一律 401——「放宽」仅指不要求已绑定
```

### F4. 存量用户在线升级（双查）

见 A1-⑦。接入方补上 sub 字段后，老用户首次请求自动切到稳定 ID 锚，
无需重绑、无感迁移。

### F5. 自动开通账号治理

```
ext_user 角色空权限（进不了任何管理页面）；随机密码永不外发
admin 可在用户管理按角色筛选查看；不使用可解绑后删除
```

### F6. 用户名迁移（运维手册，E4 兜底）

```
无 sub 且用户改名的存量场景：
admin 修改 external_identities——老 sub 的 platform_user_id 复制到新 sub
（或改写 sub 字段）。user_mcp_credentials 按 platform_user_id 关联，不动。
用户下次进入身份即连续，更新一次凭证即可。
```

### F7. 接入方无 sub 字段

```
stable_id 自动退回 username（行为与 v4.1 完全一致）
推动接入方按 RFC 7666 补 sub → 补齐即自动生效（F4 升级路径）
```

---

## 流程与文件的对应关系（速查）

| 流程 | 关键代码 |
|---|---|
| A1 鉴权/双查 | `app/core/auth_apikey.py` |
| B1 首绑门页 | `ext/my_app_authorizations.py` + `BindingGatePage.tsx` |
| B1④a 认领 | `services/auth_service.py: verify_platform_credentials` |
| B1④c 自动开通 | `services/user_service.py: ensure_ext_platform_user` |
| B1⑤ 绑定/提取/优先链 | `services/user_mcp_credential_service.py` |
| C1 兑换 | `engine/mcp/user_credential_resolver.py` + harness `mcp/loader.py` |
| C2/C3 授权工具 | harness `interaction/app_authorization.py` |
| C4 veto | harness `graph/nodes/tool_wrapper.py` |
| C5 兜底解析 | `frontend-client/src/api/authorizations.ts: parseUnboundMarker` |
| 事件流 kind | `adapters/app_event.py` + `adapters/stream_events.py` + `use-chat.ts` |
