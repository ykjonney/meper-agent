# Client 自助授权 — 本地 E2E 测试指南（embed-demo.html）

> 用 `frontend-client/embed-demo.html`（模拟第三方宿主页）完整走一遍
> 首绑门页、运行时授权卡、凭证失效闭环。流程编号对应
> `docs/client-authorization-flows.md`。

## 0. 架构（本地各角色）

```
浏览器
 ├─ http://localhost:3002/client/embed-demo.html   宿主页（第三方网站）
 │    └─ chat-widget.js（iframe 嵌入）+ cookie x-mep-token（接入方用户 token）
 ├─ http://localhost:3002/client/                  frontend-client（apikey 模式）
 │    └─ /api 代理 → http://127.0.0.1:8000          backend
 └─ http://127.0.0.1:9101                          mock_partner.py（接入方系统）
      ├─ POST /introspect   token 校验（返回 sub 稳定 ID + username）
      └─ POST /login        账密验证（返回 data.token + userId）

 http://127.0.0.1:9102/mcp                          mock_mcp.py（演示应用下的 MCP 资源）
      └─ tools: query_order / who_am_i（Agent 绑定后触发凭证解析链路）

依赖：MongoDB + Redis（backend 需要）
```

## 1. 启动

```bash
# ① 依赖服务（如果没有常驻的）
docker compose -f deploy/docker-compose.yml up -d mongodb redis  # 按实际服务名

# ② mock 接入方系统（终端 1）
cd backend && uv run python scripts/mock_partner.py        # :9101

# ②' mock MCP 服务（终端 1b，测 C2/C3 运行时授权卡必需）
cd backend && uv run python scripts/mock_mcp.py            # :9102

# ③ 后端（终端 2）——make dev-local 不含 client，按需
make dev-local                                               # FastAPI+Celery+studio
# 或只要后端：cd backend && uv run uvicorn app.main:app --reload --port 8000

# ④ client 前端（终端 3，端口必须是 3002——demo 里写死了）
cd frontend-client && npm run dev                            # :3002
```

## 2. 种子数据（一次性）

```bash
cd backend
# 基础（首绑门页/授权面板/解绑可测）
uv run python scripts/seed_e2e_auth.py
# 运行时授权卡（C2/C3）需要 Agent 真的调到该应用的 MCP 工具
# （mock_mcp.py 提供开箱即用的资源，先把它跑起来）：
uv run python scripts/seed_e2e_auth.py --mcp-url http://127.0.0.1:9102/mcp
```

⚠️ `--reset` 会删掉旧 Key 重建——重跑后**必须把新 `af_live_...` 更新进
embed-demo.html**（demo 里注释有说明）。

脚本输出一个 `af_live_...` 完整 Key（只显示一次），粘进
`embed-demo.html` 的 `data-api-key`。

**Agent 准备**：在 studio 建一个 Agent，模型工具里勾上
`e2e-demo-mcp` 的工具，发布。（运行时授权卡测试必需）

**mock 内置账号**（详见 mock_partner.py）：

| 用户 | 密码 | 稳定 ID | 说明 |
|---|---|---|---|
| zhangsan | secret123 | u_10086 | demo 里预填 token 就是这个用户 |
| lisi | pass456 | u_10087 | 换用户测试 |

## 3. 测试用例（对照流程目录）

### B1-① 首绑·自动开通（新用户）

1. 打开 `http://localhost:3002/client/embed-demo.html`
2. 点击 widget 浮标 → iframe 内应出现**首绑门页**（不是死胡同提示页）：
   应用「演示应用（E2E）」+ 只读账号 `zhangsan`
3. 只填密码 `secret123` → 提交 → 自动进入会话
4. 验证：`users` 集合出现 `ext.u_10086.*` 的 ext_user 账号；
   `external_identities` 有 `sub = {appId}:u_10086`（**注意锚是稳定 ID**）

### B1-② 首绑·认领（已有平台账号）

1. `--reset` 清数据后重来（或用 lisi 的 token：先 `POST :9101/admin/token`
   {"username":"lisi"} 拿新 token 换进 demo）
2. 门页展开「已有平台账号？关联」→ 填平台账号+密码+外部密码
3. 验证：进入会话后**历史会话/文件延续**（认领前的数据还在）
4. 反例：平台密码填错 → 门页内报错（不能被弹回 TokenLoginPage）

### C2 运行时授权卡（未授权）

前提：Agent 绑了 e2e-demo-mcp 工具；用户已过首绑（或故意不绑应用凭证
——首绑后从侧边栏「应用授权」里取消授权，即可重演 UNBOUND）。

1. 对话："帮我用工具查点东西" → Agent 调 MCP → 工具报错（标记 UNBOUND）
2. **聊天流内出现授权表单卡**（账号+密码+完成授权/暂不授权）
3. 填 `zhangsan / secret123` → 提交 → **原轮自动恢复**，工具重试成功
4. 反例 A：点「暂不授权」→ Agent 换方式回应（不硬等）
5. 反例 B：观察 LLM 有时直接文字收尾 → 前端兜底卡出现 → 提交后
   自动重发上一条消息（C5，需要多试几次才能碰到）

### C2' 跨应用授权卡（Agent 调到**其他应用**的工具）

前提：mock_partner（A/B 双系统）+ mock_mcp 两个实例在跑；种子带
`--second-app`；Agent 同时勾了 `e2e-demo-mcp`（query_order）和
`e2e-demo-mcp-b`（query_inventory）的工具；用户已完成应用 A 的首绑。

1. 对话："查一下 SKU-2001 的库存" → Agent 调 B 的工具 → B 未授权
2. **聊天内弹出「演示应用 B」的授权卡**——注意：跨应用卡里**账号可自由
   填写**（不像 key 应用锁死；B 系统账号与 A 无关）
3. 填 B 系统账号 `wangwu / pass789` → 提交 → 原轮恢复，返回库存
4. 验证：`external_identities` 多出 `sub = {appB}:u_20001`（锚 =
   B 登录响应提取的 userId），指向**同一个** platform_user_id（身份归一）
5. 反例：B 的账号密码填错 → 卡片内报错（绑定 API 的 login_url 验证失败）

跨应用的凭证失效/改名：admin 端点带 `"system":"b"` 即可
（如 `POST /admin/password -d '{"username":"wangwu","new_password":"x","system":"b"}'`）。

### C3 凭证失效闭环（改密码 → INVALID）

```bash
# 模拟用户在外部系统改密码
curl -X POST localhost:9101/admin/password \
  -H 'Content-Type: application/json' \
  -d '{"username":"zhangsan","new_password":"newpass999"}'
```

1. 等待 session TTL 过期（种子脚本设了 300s；可清 Redis 的
   `mcp:session:*` 立即触发）
2. 再让 Agent 调工具 → 卡片文案应为**「凭证已失效…请输入最新的」**（INVALID）
3. 填新密码 `newpass999` → 恢复
4. 改回：`curl ... -d '{"username":"zhangsan","new_password":"secret123"}'`

### E3 改用户名（稳定 ID 锚）

```bash
curl -X POST localhost:9101/admin/rename \
  -H 'Content-Type: application/json' \
  -d '{"username":"zhangsan","new_username":"zhangsan_new"}'
```

1. 刷新宿主页重新进入 → **不掉身份**（sub = u_10086 不变，不回首绑门页）
2. 调工具 → INVALID 卡（账密里用户名旧了）→ 填 `zhangsan_new / 密码` → 恢复
3. （对照实验：无 sub 的接入方会回首绑门页——本 mock 始终返回 sub，
   如需对照可临时删掉 introspect 响应里的 sub 字段）

### D 授权面板

1. 侧边栏用户区「🛡 应用授权」→ 列表显示已绑定应用（密码脱敏）
2. key 应用：账号输入框灰掉（锁 introspection 用户名）
3. 更新凭证 / 取消授权 → 解绑后下次请求回到首绑门页（UI 有提示）

## 4. 常见卡点排查

| 现象 | 原因 |
|---|---|
| iframe 显示 no_token | demo 的 cookie 名与 `data-token-cookie` 不一致（已修复为 `x-mep-token`）；或 token 无效 |
| 401 token_invalid | mock 没起 / ApiKey.introspect_url 没指向 :9101/introspect |
| 401 not_bound 循环 | 首绑 PUT 失败——看 mock /login 是否返回 success:false |
| 授权卡不出现（工具直接成功） | 用户已绑定 + session 缓存有效——解绑或清 `mcp:session:*` |
| 授权卡不出现（工具报错但没卡） | Agent 没绑 MCP 工具 / 工具不属于演示应用 |
| INVALID 一直不触发 | session TTL 未到——清 Redis 或等 300s |
| demo 打开是 404 | 确认 client 端口 3002（vite.config base=/client/，访问 /client/embed-demo.html） |
