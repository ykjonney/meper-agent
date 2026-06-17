# Agent Flow API 文档

> Base URL: `/api/v1`
>
> 所有需要认证的接口请在请求头中携带 `Authorization: Bearer <access_token>`

---

## 目录

- [1. 健康检查](#1-健康检查)
- [2. 认证 (Auth)](#2-认证-auth)
- [3. 用户管理 (Admin)](#3-用户管理-admin)
- [4. 模型管理 (Models)](#4-模型管理-models)
- [5. Agent 管理](#5-agent-管理)
- [6. Agent 执行](#6-agent-执行)
- [7. 会话管理 (Sessions)](#7-会话管理-sessions)
- [8. 工具 / Skill 管理 (Tools)](#8-工具--skill-管理-tools)
- [9. MCP 连接管理](#9-mcp-连接管理)
- [附录: 通用错误响应](#附录-通用错误响应)
- [附录: 角色权限矩阵](#附录-角色权限矩阵)

---

## 1. 健康检查

### `GET /health`

无需认证。用于 k8s liveness / readiness 探针。

**Response** `200`

```json
{ "status": "ok" }
```

---

## 2. 认证 (Auth)

### 2.1 用户登录

`POST /auth/login`

无需认证。

**Request Body**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| username | string | 是 | 用户名 |
| password | string | 是 | 密码 |

**Response** `200`

```json
{
  "access_token": "eyJ...",
  "refresh_token": "eyJ...",
  "token_type": "bearer"
}
```

**Error** `401` — 用户名或密码错误 / 账户已锁定

---

### 2.2 刷新令牌

`POST /auth/refresh`

无需认证。

**Request Body**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| refresh_token | string | 是 | 有效的 refresh token |

**Response** `200` — 同登录响应

**Error** `401` — refresh token 无效或已过期

---

### 2.3 修改密码

`POST /auth/change-password`

需要认证。

**Request Body**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| current_password | string | 是 | 当前密码 |
| new_password | string | 是 | 新密码 (min 8) |

**Response** `200`

```json
{ "message": "密码已修改，请重新登录" }
```

---

### 2.4 注销

`POST /auth/logout`

幂等操作。无需认证。

**Request Body**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| refresh_token | string | 是 | 要注销的 refresh token |

**Response** `200`

```json
{ "message": "已注销" }
```

---

## 3. 用户管理 (Admin)

> 前缀: `/admin`
>
> 所有接口需要 **admin** 角色

### 3.1 用户列表

`GET /admin/users`

**Query Parameters**

| 参数 | 类型 | 说明 |
|------|------|------|
| page | int | 页码 (默认 1) |
| page_size | int | 每页条数 (默认 20, 最大 100) |
| username | string | 可选，按用户名模糊搜索 |
| role | string | 可选，按角色过滤 (`admin` / `developer` / `operator` / `viewer`) |
| status | string | 可选，按状态过滤 (`active` / `locked`) |

**Response** `200`

```json
{
  "items": [
    {
      "id": "user_01H...",
      "username": "admin",
      "email": "admin@example.com",
      "role": "admin",
      "status": "active",
      "created_at": "2026-01-01T00:00:00",
      "updated_at": "2026-01-01T00:00:00",
      "last_login_at": null
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 20
}
```

---

### 3.2 创建用户

`POST /admin/users`

**Request Body**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| username | string | 是 | 用户名 (1-50) |
| email | string | 是 | 邮箱 |
| password | string | 是 | 初始密码 (min 8) |
| role | string | 是 | 角色 (`admin` / `developer` / `operator` / `viewer`) |

**Response** `201` — 返回用户对象

**Errors**
- `409` — 用户名或邮箱冲突
- `422` — 参数校验失败

---

### 3.3 更新用户

`PATCH /admin/users/{user_id}`

部分更新，仅修改提供的字段。

**Request Body**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| role | string | 否 | 新角色 |
| status | string | 否 | 新状态 (`active` / `locked`) |

**Response** `200` — 返回更新后的用户对象

**Errors**
- `404` — 用户不存在
- `422` — 不允许删除自己或最后一个 admin

---

### 3.4 删除用户

`DELETE /admin/users/{user_id}`

**Response** `204` — 无内容

**Errors**
- `404` — 用户不存在
- `422` — 不能删除自己或最后一个 admin

---

### 3.5 重置密码

`POST /admin/users/{user_id}/reset-password`

**Request Body**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| new_password | string | 是 | 新密码 (min 8) |

**Response** `200`

```json
{ "message": "密码已重置" }
```

---

## 4. 模型管理 (Models)

> 前缀: `/models`
>
> 创建/更新/删除需要 **admin** 角色；列表/详情/测试需要 developer+ 角色

### 4.1 模型列表

`GET /models`

**Query Parameters**

| 参数 | 类型 | 说明 |
|------|------|------|
| page | int | 页码 (默认 1) |
| page_size | int | 每页条数 (默认 20, 最大 100) |
| status | string | 可选，按状态过滤 (`active` / `inactive`) |
| provider_tag | string | 可选，按提供商标签过滤 |

**Response** `200`

```json
{
  "items": [
    {
      "id": "model_01H...",
      "model_id": "gpt-4o",
      "name": "GPT-4o",
      "base_url": "https://api.openai.com/v1",
      "api_key": "****",
      "compatibility_type": "openai",
      "auth_type": "bearer",
      "auth_header_format": "Bearer {key}",
      "default_params": {},
      "status": "active",
      "provider_tag": "openai",
      "version": 1,
      "created_at": "2026-01-01T00:00:00",
      "updated_at": "2026-01-01T00:00:00"
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 20
}
```

---

### 4.2 创建模型

`POST /models`

需要 **admin** 角色。

**Request Body**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| model_id | string | 是 | 模型标识 (如 `gpt-4o`)，全局唯一 |
| name | string | 是 | 显示名称 |
| base_url | string | 是 | API 基础 URL |
| api_key | string | 是 | API Key (AES-256 加密存储) |
| compatibility_type | string | 是 | 兼容类型 (`openai` / `anthropic`) |
| auth_type | string | 否 | 认证类型 (`bearer` / `custom`) |
| auth_header_format | string | 否 | 认证头格式 (默认 `Bearer {key}`) |
| default_params | object | 否 | 默认参数 |
| provider_tag | string | 否 | 提供商标签 |

**Response** `201` — 返回模型对象

**Errors**
- `409` — model_id 冲突

---

### 4.3 获取模型详情

`GET /models/{model_id}`

**Response** `200` — 返回模型对象

---

### 4.4 测试模型连通性

`POST /models/{model_id}/test`

发送一个最小探测请求，验证 API Key 和 base_url 是否可用。

**Response** `200`

```json
{
  "success": true,
  "latency_ms": 234,
  "model_reply": "Hello!",
  "error": null
}
```

---

### 4.5 更新模型

`PUT /models/{model_id}`

需要 **admin** 角色。完整替换更新。

**Request Body** — 同创建模型，所有字段均可选。

**Response** `200` — 返回更新后的模型对象

---

### 4.6 删除模型

`DELETE /models/{model_id}`

需要 **admin** 角色。

**Response** `204`

**Errors**
- `404` — 模型不存在
- `409` — 模型被一个或多个 Agent 引用

---

## 5. Agent 管理

> 前缀: `/agents`
>
> 列表/详情需要 viewer+ 角色；创建/更新/删除需要 developer+ 角色

### Agent 状态流转

```
draft ──publish──→ published ──archive──→ archived
  ↑                  |                      |
  └────── (edit) ────┘                      |
  └────────────── (edit) ────────────────────┘
```

### 5.1 Agent 列表

`GET /agents`

**Query Parameters**

| 参数 | 类型 | 说明 |
|------|------|------|
| page | int | 页码 (默认 1) |
| page_size | int | 每页条数 (默认 20, 最大 100) |
| name | string | 可选，按名称模糊搜索 |
| status | string | 可选，按状态过滤 (`draft` / `published` / `archived`) |

**Response** `200`

```json
{
  "items": [ { "...see AgentResponse" } ],
  "total": 1,
  "page": 1,
  "page_size": 20
}
```

---

### 5.2 创建 Agent

`POST /agents`

**Request Body**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| name | string | 是 | Agent 名称 (1-100) |
| description | string | 否 | 描述 (max 500) |
| system_prompt | string | 否 | 系统提示词 (max 10000) |
| saved_system_prompts | array | 否 | 保存的提示词模板列表 |
| skill_ids | string[] | 否 | 绑定的 Skill 工具 ID 列表 |
| mcp_connection_ids | string[] | 否 | 绑定的 MCP 连接 ID 列表 |
| builtin_config | string[] | 否 | 启用的内置工具名称白名单 (`bash` / `read` / `write`) |
| workflow_ids | string[] | 否 | 绑定的工作流 ID 列表 |
| knowledge_base_ids | string[] | 否 | 绑定的知识库 ID 列表 |
| llm_config | object | 否 | 模型配置 |

**saved_system_prompts 子对象**

| 字段 | 类型 | 说明 |
|------|------|------|
| id | string | Prompt ID (空则自动生成) |
| name | string | Prompt 名称 |
| content | string | Prompt 内容 |
| is_active | bool | 是否为当前活跃 Prompt |

**llm_config 子对象**

| 字段 | 类型 | 说明 |
|------|------|------|
| default_model | string | 默认模型引用 (模型 `_id` 或模型名称字符串) |
| temperature | float | 温度 (0.0-2.0, 默认 0.7) |
| max_retry | int | 最大重试次数 (0-10, 默认 3) |

**Response** `201`

```json
{
  "id": "agent_01H...",
  "name": "My Agent",
  "description": "A helpful assistant",
  "system_prompt": "You are a helpful assistant.",
  "saved_system_prompts": [],
  "skill_ids": ["tool_01H..."],
  "mcp_connection_ids": [],
  "builtin_config": ["bash", "read"],
  "workflow_ids": [],
  "knowledge_base_ids": [],
  "llm_config": {
    "default_model": "model_01H...",
    "temperature": 0.7,
    "max_retry": 3
  },
  "status": "draft",
  "version": 1,
  "created_at": "2026-01-01T00:00:00",
  "updated_at": "2026-01-01T00:00:00"
}
```

---

### 5.3 获取 Agent 详情

`GET /agents/{agent_id}`

**Response** `200` — 同上 AgentResponse

---

### 5.4 更新 Agent

`PUT /agents/{agent_id}`

完整替换更新。仅 published 状态的 Agent 自动递增 version。

**Request Body** — 同创建 Agent，额外增加:

| 字段 | 类型 | 说明 |
|------|------|------|
| status | string | 可选，新状态。不传则保持当前状态 |

**Response** `200`

**Errors**
- `404` — Agent 不存在
- `409` — Agent 名称冲突

---

### 5.5 发布 Agent

`POST /agents/{agent_id}/publish`

draft/archived → published。自动递增 version。

**Response** `200` — AgentResponse

---

### 5.6 归档 Agent

`POST /agents/{agent_id}/archive`

published → archived。自动递增 version。

**Response** `200` — AgentResponse

---

### 5.7 复制 Agent

`POST /agents/{agent_id}/duplicate`

创建一份副本，新 Agent 始终为 draft 状态，version = 1。

**Response** `201` — AgentResponse

---

### 5.8 预览 Agent (Dry-run)

`POST /agents/{agent_id}/preview`

不实际调用 LLM。返回完整的系统提示词、消息列表和解析后的工具定义，用于调试 Agent 配置。

**Request Body** (可选)

| 字段 | 类型 | 说明 |
|------|------|------|
| input | string | 模拟用户输入 (默认 "Hello") |
| enable_thinking | bool | 是否启用 thinking 模式 (默认 false) |

**Response** `200`

```json
{
  "agent_id": "agent_01H...",
  "agent_name": "My Agent",
  "model": "gpt-4o",
  "system_prompt": "You are a helpful assistant.\n\n## Available Skills\n...",
  "messages": [
    { "role": "system", "content": "..." },
    { "role": "user", "content": "Hello" }
  ],
  "tools": [
    {
      "name": "load_skill",
      "type": "skill",
      "description": "Load the SKILL.md content of a named skill.",
      "source": "skill_loader",
      "input_schema": { "...JSON Schema..." }
    }
  ],
  "tool_summary": {
    "total": 4,
    "skill": 1,
    "mcp": 1,
    "builtin": 1,
    "workflow": 1
  }
}
```

---

### 5.9 删除 Agent

`DELETE /agents/{agent_id}`

**Response** `204`

**Errors**
- `404` — Agent 不存在

---

## 6. Agent 执行

### 6.1 同步调用

`POST /agents/{agent_id}/invoke`

同步执行 Agent，等待完整结果返回。

**Request Body**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| input | string | 是 | 用户输入文本 (max 50000) |
| session_id | string | 否 | 会话 ID (为空则自动创建新会话) |
| enable_thinking | bool | 否 | 启用 LLM 原生推理 (默认 false) |

**Request Headers**

| Header | 说明 |
|--------|------|
| X-Call-Chain | 可选，JSON 数组字符串，外部调用链 (用于 Agent 间调用追踪) |

**Response** `200`

```json
{
  "output": "Hello! How can I help you?",
  "execution_path": "react",
  "request_id": "uuid-...",
  "agent_id": "agent_01H...",
  "session_id": "session_01H...",
  "step_count": 2
}
```

**Errors**
- `404` — Agent 不存在
- `504` — 执行超时 (>30s)

---

### 6.2 流式调用 (SSE)

`POST /agents/{agent_id}/stream`

通过 Server-Sent Events 流式返回执行过程。

**Request Body** — 同同步调用

**Response** `200` — `Content-Type: text/event-stream`

SSE 事件类型：

| event.type | 说明 |
|------------|------|
| `thinking` | LLM 推理过程 (仅 enable_thinking=true) |
| `tool_call` | 工具调用 (含 tool_name + args) |
| `tool_result` | 工具返回结果 |
| `final_answer` | 最终回答 (完整文本) |
| `final_answer_delta` | 最终回答增量片段 |
| `error` | 执行错误 |
| `done` | 流结束信号 (含 request_id + session_id) |

SSE 事件格式：

```
data: {"type":"thinking","content":"Let me analyze..."}
data: {"type":"tool_call","tool_name":"bash","args":{"command":"ls"}}
data: {"type":"tool_result","tool_name":"bash","content":"file1.txt\nfile2.txt"}
data: {"type":"final_answer_delta","content":"Based on "}
data: {"type":"final_answer_delta","content":"the results..."}
data: {"done":true,"request_id":"uuid-...","session_id":"session_01H..."}
```

**Response Headers**

| Header | 说明 |
|--------|------|
| X-Request-Id | 本次执行请求 ID |
| X-Session-Id | 关联会话 ID |
| Cache-Control | `no-cache` |

---

## 7. 会话管理 (Sessions)

> 前缀: `/sessions`
>
> 所有接口需要认证，且只能访问自己的会话

### 7.1 创建会话

`POST /sessions`

**Request Body**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| agent_id | string | 是 | 关联的 Agent ID |
| title | string | 否 | 会话标题 |

**Response** `201`

```json
{
  "_id": "session_01H...",
  "user_id": "user_01H...",
  "agent_id": "agent_01H...",
  "title": "My conversation",
  "status": "active",
  "message_count": 0,
  "created_at": "2026-01-01T00:00:00",
  "updated_at": "2026-01-01T00:00:00"
}
```

---

### 7.2 会话列表

`GET /sessions`

**Query Parameters**

| 参数 | 类型 | 说明 |
|------|------|------|
| agent_id | string | 可选，按 Agent ID 过滤 |
| page | int | 页码 (默认 1) |
| page_size | int | 每页条数 (默认 20, 最大 100) |

**Response** `200`

```json
{
  "items": [ { "...see SessionResponse" } ],
  "total": 1,
  "page": 1,
  "page_size": 20
}
```

---

### 7.3 获取会话详情 (含消息)

`GET /sessions/{session_id}`

返回会话及其所有消息。

**Response** `200`

```json
{
  "session": { "...SessionResponse..." },
  "messages": [
    {
      "_id": "msg_01H...",
      "session_id": "session_01H...",
      "role": "user",
      "content": "Hello!",
      "timeline_entries": [],
      "created_at": "2026-01-01T00:00:00"
    },
    {
      "_id": "msg_01H...",
      "session_id": "session_01H...",
      "role": "agent",
      "content": "Hello! How can I help you?",
      "timeline_entries": [
        { "type": "thinking", "content": "..." },
        { "type": "tool_call", "tool_name": "bash", "args": {...} },
        { "type": "tool_result", "tool_name": "bash", "content": "..." },
        { "type": "final_answer", "content": "Hello! How can I help you?" }
      ],
      "created_at": "2026-01-01T00:00:00"
    }
  ]
}
```

---

### 7.4 删除会话

`DELETE /sessions/{session_id}`

删除会话及其所有消息。

**Response** `204`

---

## 8. 工具 / Skill 管理 (Tools)

> 前缀: `/tools`
>
> 列表/详情/文件浏览需要 viewer+ 角色；上传/更新/删除需要 developer+ 角色

### Skill 文件存储机制

Skill 文件 (SKILL.md + scripts + templates 等) 存储在本地文件系统 `SKILLS_DIR/{skill_name}/` 下，
MongoDB 仅保留注册元数据 (name, description, tags 等)。Agent 执行时通过 `load_skill` 工具从磁盘读取 SKILL.md 内容，
并注入绝对路径提示，使 Agent 可以通过 bash/read 工具访问辅助文件。

### 8.1 内置工具列表

`GET /tools/builtin`

返回系统内置工具的静态列表 (bash / read / write)。

**Response** `200`

```json
[
  {
    "name": "bash",
    "description": "Execute shell commands",
    "parameters": { "...JSON Schema..." }
  }
]
```

---

### 8.2 工具列表

`GET /tools`

**Query Parameters**

| 参数 | 类型 | 说明 |
|------|------|------|
| page | int | 页码 (默认 1) |
| page_size | int | 每页条数 (默认 20, 最大 100) |
| name | string | 可选，按名称模糊搜索 |
| source | string | 可选，按来源过滤 (`markdown` / `mcp` / `builtin`) |
| mcp_connection_id | string | 可选，按 MCP 连接 ID 过滤 |

**Response** `200`

```json
{
  "items": [
    {
      "id": "tool_01H...",
      "name": "my-skill",
      "description": "A powerful skill",
      "input_schema": {},
      "output_schema": {},
      "instructions": "",
      "source": "markdown",
      "source_file": "my-skill",
      "mcp_connection_id": "",
      "version": 1,
      "tags": [],
      "files": [
        { "path": "SKILL.md", "content": "", "size": 1234 },
        { "path": "scripts/search.py", "content": "", "size": 567 }
      ],
      "created_at": "2026-01-01T00:00:00",
      "updated_at": "2026-01-01T00:00:00"
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 20
}
```

> `files` 列表中的 `content` 在列表视图中为空字符串，需要通过文件内容接口获取。

---

### 8.3 获取工具详情

`GET /tools/{tool_id}`

**Response** `200` — 同上 ToolResponse

---

### 8.4 上传 Skill 文件

`POST /tools/upload`

`Content-Type: multipart/form-data`

支持两种模式:

**目录模式** — 文件以 `目录名/` 为前缀，目录下必须包含 `SKILL.md`:

```
my-skill/
├── SKILL.md          ← 入口文件 (必须)
├── scripts/
│   └── search.py
└── templates/
    └── output.md
```

**单文件模式** — 独立的 `.md` 文件:

```
device.md             ← 单个 Markdown Skill 文件
```

SKILL.md 格式:

```markdown
---
name: my-skill
description: What this skill does
parameters:
  - name: query
    type: string
    description: Search query
    required: true
---

# 详细说明

Skill 的使用说明和示例...
```

**Request** — `files` 字段，支持多文件上传

**Response** `200`

```json
{
  "created": [ { "...ToolResponse..." } ],
  "errors": [
    { "filename": "bad.md", "error": "Missing YAML frontmatter" }
  ]
}
```

**Errors**
- `413` — 文件过大 (>1MB) 或目录总大小超限 (>10MB)

---

### 8.5 获取文件树

`GET /tools/{tool_id}/files`

返回目录型 Skill 的文件树结构 (层级嵌套)。

**Response** `200`

```json
{
  "tool_id": "tool_01H...",
  "files": [
    {
      "key": "SKILL.md",
      "title": "SKILL.md",
      "is_leaf": true,
      "children": null,
      "size": 1234
    },
    {
      "key": "scripts",
      "title": "scripts",
      "is_leaf": false,
      "children": [
        {
          "key": "scripts/search.py",
          "title": "search.py",
          "is_leaf": true,
          "children": null,
          "size": 567
        }
      ],
      "size": 0
    }
  ]
}
```

---

### 8.6 获取文件内容

`GET /tools/{tool_id}/files/{file_path}`

从磁盘读取指定文件的内容。

**Example** `GET /tools/tool_01H.../files/scripts/search.py`

**Response** `200`

```json
{
  "path": "scripts/search.py",
  "content": "import requests\n...",
  "size": 567
}
```

---

### 8.7 更新文件内容

`PUT /tools/{tool_id}/files/{file_path}`

写入磁盘。如果更新的文件是 `SKILL.md`，会自动重新解析 YAML frontmatter 并更新 MongoDB 中的 name / description / instructions 等元数据。

**Request Body**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| content | string | 是 | 新的文件内容 (min 1) |

**Response** `200` — 同文件内容响应

---

### 8.8 更新工具元数据

`PUT /tools/{tool_id}`

目前仅支持更新 tags。自动递增 version。

**Request Body**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| tags | string[] | 否 | 新标签列表 |

**Response** `200` — ToolResponse

---

### 8.9 删除工具

`DELETE /tools/{tool_id}`

同时清理磁盘上的 Skill 文件目录。如果工具被 Agent 引用则拒绝删除。

**Response** `204`

**Errors**
- `404` — 工具不存在
- `409` — 工具被一个或多个 Agent 引用

---

## 9. MCP 连接管理

> 前缀: `/mcp/connections`
>
> 列表/详情需要 viewer+ 角色；创建/更新/删除/测试/发现需要 developer+ 角色

### 9.1 创建 MCP 连接

`POST /mcp/connections`

**Request Body**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| name | string | 是 | 连接名称 |
| description | string | 否 | 描述 |
| url | string | 是 | MCP 服务器 URL |
| protocol | string | 否 | 协议 (`streamable-http` / `sse` / `stdio`) |
| auth_type | string | 否 | 认证类型 (`none` / `bearer` / `custom`) |
| auth_config | object | 否 | 认证配置 (api_key 等敏感字段自动脱敏) |
| timeout | int | 否 | 超时秒数 (默认 30) |
| default_params | object | 否 | 默认参数 |

**Response** `201`

```json
{
  "id": "mcpconn_01H...",
  "name": "My MCP Server",
  "description": "",
  "url": "http://localhost:3001/mcp",
  "protocol": "streamable-http",
  "auth_type": "none",
  "auth_config": {},
  "timeout": 30,
  "default_params": {},
  "status": "disconnected",
  "status_message": "",
  "last_connected_at": "",
  "tool_count": 0,
  "created_at": "2026-01-01T00:00:00",
  "updated_at": "2026-01-01T00:00:00"
}
```

---

### 9.2 MCP 连接列表

`GET /mcp/connections`

**Query Parameters**

| 参数 | 类型 | 说明 |
|------|------|------|
| page | int | 页码 |
| page_size | int | 每页条数 |
| name | string | 可选，按名称模糊搜索 |
| status | string | 可选，按状态过滤 (`connected` / `disconnected` / `error`) |

**Response** `200`

---

### 9.3 获取连接详情

`GET /mcp/connections/{connection_id}`

**Response** `200` — 同上

---

### 9.4 更新连接

`PUT /mcp/connections/{connection_id}`

**Request Body** — 同创建，所有字段均可选。

**Response** `200`

---

### 9.5 删除连接

`DELETE /mcp/connections/{connection_id}`

级联删除该连接下所有已发现的 MCP 工具。

**Response** `204`

---

### 9.6 测试连接

`POST /mcp/connections/{connection_id}/test`

尝试连接 MCP 服务器并更新状态。

**Response** `200`

```json
{
  "success": true,
  "latency_ms": 50,
  "tool_count": 5,
  "error": null
}
```

---

### 9.7 发现工具

`POST /mcp/connections/{connection_id}/discover`

从 MCP 服务器发现工具并注册到工具池。

**Response** `200`

```json
{
  "discovered": 5,
  "registered": 5,
  "removed": 0,
  "tools": [
    { "name": "search", "description": "Search the web" }
  ]
}
```

---

## 附录: 通用错误响应

所有 API 在发生错误时返回统一格式:

```json
{
  "error_code": "TOOL_NOT_FOUND",
  "message": "工具 tool_01H... 不存在",
  "details": {}
}
```

**通用 HTTP 状态码**

| 状态码 | 说明 |
|--------|------|
| 400 | 请求参数错误 |
| 401 | 未认证 (缺少或无效 JWT) |
| 403 | 权限不足 (角色不够) |
| 404 | 资源不存在 |
| 409 | 冲突 (名称重复、资源被引用) |
| 413 | 请求体过大 |
| 422 | 参数校验失败 |
| 500 | 服务器内部错误 |
| 504 | 执行超时 |

---

## 附录: 角色权限矩阵

| 角色 | 说明 | 权限范围 |
|------|------|----------|
| **admin** | 系统管理员 | 全部操作 + 用户管理 + 模型管理 |
| **developer** | 开发者 | Agent/Tool/MCP/Session 全部操作 + 模型测试 |
| **operator** | 运维人员 | Agent 执行 + 列表/详情查看 |
| **viewer** | 只读用户 | 仅列表/详情查看 |

| 操作 | admin | developer | operator | viewer |
|------|-------|-----------|----------|--------|
| 用户管理 CRUD | ✅ | - | - | - |
| 模型创建/更新/删除 | ✅ | - | - | - |
| 模型列表/详情/测试 | ✅ | ✅ | - | - |
| Agent 创建/更新/删除 | ✅ | ✅ | - | - |
| Agent 列表/详情 | ✅ | ✅ | ✅ | ✅ |
| Agent 执行 (invoke/stream) | ✅ | ✅ | ✅ | ✅ |
| Tool 上传/更新/删除 | ✅ | ✅ | - | - |
| Tool 列表/详情 | ✅ | ✅ | ✅ | ✅ |
| MCP 连接管理 | ✅ | ✅ | - | - |
| MCP 连接列表/详情 | ✅ | ✅ | ✅ | ✅ |
| Session 管理 (自己的) | ✅ | ✅ | ✅ | ✅ |
