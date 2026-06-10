---
baseline_commit: NO_VCS
---

# Story 5.3: MCP 连接管理

**Epic:** Epic 5 — 工具系统
**Status:** ready-for-dev
**Story ID:** 5-3
**Story Key:** 5-3-mcp-connection-management

## Story

As a 开发者，
I want 配置 MCP 服务连接，自动发现并管理通过 MCP 协议暴露的工具，
So that 外部系统的能力可通过 MCP 快速集成到平台，Agent 运行时可统一调用。

> **关键背景**：
> - Tool 数据模型（`models/tool.py`）已设计 `source` 字段支持 `"mcp"` 来源
> - `langchain-mcp-adapters>=0.2.2` 和 `mcp==1.27.2` 已在 `pyproject.toml` 中安装
> - 前端 `pages/mcp-page.tsx` 已存在 Mock 版本（含 MCP 服务器列表、状态展示、添加/编辑/删除按钮）
> - Story 5-1 完成了 Markdown Skill 注册到 `tools` 集合，MCP 工具也注册到同一个 `tools` 集合
> - MCP 连接信息存储在独立的 `mcp_connections` 集合，与 `tools` 集合通过 `mcp_connection_id` 关联
> - 本 Story 做 MCP **连接管理和工具发现**，不做工具执行（执行在 Story 5-2 Agent 执行引擎中实现）

## Acceptance Criteria

### AC1: MCP 连接数据模型
**Given** 平台需要管理 MCP 服务器连接
**When** 审查 `backend/app/models/mcp_connection.py`
**Then** 定义 `ConnectionStatus(StrEnum)` 枚举：`CONNECTING` / `CONNECTED` / `DISCONNECTED` / `ERROR`
**And** 定义 `AuthType(StrEnum)` 枚举：`NONE` / `API_KEY` / `BEARER_TOKEN` / `BASIC`
**And** 定义 `McpConnection` Pydantic 模型包含字段：
  - `id: str`（格式 `mcp_{ULID}`，alias `_id`）
  - `name: str`（唯一，连接名称）
  - `description: str`（可选描述）
  - `url: str`（MCP 服务地址，如 `http://localhost:8080/mcp`）
  - `protocol: str`（传输协议：`"sse"` / `"streamable-http"`）
  - `auth_type: AuthType`（认证方式）
  - `auth_config: dict`（认证配置，如 API Key 值等，敏感信息加密存储）
  - `timeout: int`（超时秒数，默认 30）
  - `status: ConnectionStatus`（连接状态）
  - `status_message: str`（状态详情/错误信息）
  - `last_connected_at: str`（上次成功连接时间）
  - `tool_count: int`（发现的工具数量，默认 0）
  - `created_at: str`
  - `updated_at: str`

### AC2: MCP 连接 CRUD API
**Given** 平台后端已部署
**When** 开发者通过 API 操作 MCP 连接
**Then** 提供以下端点：
  - `POST /api/v1/mcp/connections` — 创建连接配置
  - `GET /api/v1/mcp/connections` — 列表查询（分页、status 过滤、name 搜索）
  - `GET /api/v1/mcp/connections/{id}` — 获取连接详情
  - `PUT /api/v1/mcp/connections/{id}` — 更新连接配置
  - `DELETE /api/v1/mcp/connections/{id}` — 删除连接（同时清理关联的 MCP 工具）
**And** 所有端点需 JWT 认证 + RBAC（admin/developer 可写，viewer+ 可读）
**And** name 唯一（在创建和更新时校验）

### AC3: 连接测试
**Given** 开发者创建或编辑 MCP 连接配置
**When** 调用 `POST /api/v1/mcp/connections/{id}/test`
**Then** 使用 MCP Python SDK 连接目标服务器
**And** 执行 `initialize()` 握手
**And** 成功时返回 `{"success": true, "server_info": {...}, "tool_count": N}`
**And** 失败时返回 `{"success": false, "error": "具体错误信息"}`

### AC4: 工具自动发现
**Given** MCP 服务连接成功
**When** 调用 `POST /api/v1/mcp/connections/{id}/discover`
**Then** 调用 `session.list_tools()` 获取该服务暴露的所有工具
**And** 每个工具自动注册到 `tools` 集合，`source` 设为 `"mcp"`
**And** 工具的 `input_schema` 从 MCP Tool 的 `inputSchema` 字段映射
**And** 工具通过 `mcp_connection_id` 字段关联到 MCP 连接
**And** 新增的工具状态为 `DRAFT`，需要手动激活
**And** 已存在的同名工具（同 connection_id + tool_name）更新 schema 而非重复创建
**And** 被移除的工具（远程不再提供）标记为 `INACTIVE`

### AC5: 连接健康检查与自动重连
**Given** MCP 连接已建立
**When** 后台定期检查连接状态
**Then** 使用 `session.initialize()` 探测连接是否存活
**And** 连接失败时状态变为 `DISCONNECTED`，关联工具标记为 `INACTIVE`
**And** 按指数退避策略自动重连（初始 5s，最大 5min）
**And** 重连成功后自动触发工具发现同步

### AC6: 数据库索引
**Given** MCP 相关集合写入 MongoDB
**When** 审查 `backend/app/db/indexes.py`
**Then** `mcp_connections` 集合创建索引：
  - `name` 唯一索引（`idx_mcp_conn_name`）
  - `status` 普通索引（`idx_mcp_conn_status`）
**And** `tools` 集合新增索引：
  - `mcp_connection_id` 普通索引（`idx_tools_mcp_conn_id`）
  - `source` 普通索引（`idx_tools_source`）

### AC7: 前端 MCP 页面对接
**Given** 前端 `mcp-page.tsx` 已存在 Mock 版本
**When** 前端调用真实后端 API
**Then** MCP 服务器列表从后端真实加载
**And** 添加 MCP 服务 → 调用 `POST /mcp/connections`
**And** 编辑 MCP 服务 → 调用 `PUT /mcp/connections/{id}`
**And** 删除 MCP 服务 → 确认后调用 `DELETE /mcp/connections/{id}`
**And** 连接测试按钮 → 调用 `POST /mcp/connections/{id}/test`
**And** 发现工具按钮 → 调用 `POST /mcp/connections/{id}/discover`
**And** 状态实时反映后端返回的 connection status

### AC8: 单元测试覆盖
**Given** 本 Story 的所有功能
**When** 运行测试套件
**Then** 覆盖以下场景：
  - McpConnection 模型字段验证
  - 连接 CRUD 全流程
  - name 唯一校验
  - 连接测试（mock MCP SDK）
  - 工具发现与注册（mock list_tools）
  - 工具同步（新增/更新/标记 INACTIVE）
  - 删除连接时级联清理工具
  - 健康检查与状态转换

## Tasks / Subtasks

### 后端（Backend）

- [ ] **T1: MCP 连接数据模型** (AC: #1)
  - [ ] 新建 `backend/app/models/mcp_connection.py`
  - [ ] 定义 `ConnectionStatus(StrEnum)` 枚举
  - [ ] 定义 `AuthType(StrEnum)` 枚举
  - [ ] 定义 `McpConnection` Pydantic 模型（参考 `models/tool.py` 模式）

- [ ] **T2: Tool 模型扩展** (AC: #4)
  - [ ] 修改 `backend/app/models/tool.py` — 添加 `mcp_connection_id: str` 字段（默认空字符串）
  - [ ] 修改 `backend/app/schemas/tool.py` — `ToolResponse` 添加 `mcp_connection_id` 字段

- [ ] **T3: MCP 连接 Schema 定义** (AC: #2)
  - [ ] 新建 `backend/app/schemas/mcp_connection.py`
  - [ ] `McpConnectionCreate` — 创建请求
  - [ ] `McpConnectionUpdate` — 更新请求
  - [ ] `McpConnectionResponse` — 响应体
  - [ ] `McpConnectionListResponse` — 分页列表
  - [ ] `McpTestResult` — 连接测试结果
  - [ ] `McpDiscoverResult` — 工具发现结果

- [ ] **T4: MCP 客户端封装** (AC: #3, #4, #5)
  - [ ] 新建 `backend/app/engine/tool/mcp_client.py`
  - [ ] 实现 `McpConnectionManager` 类：
    - `async test_connection(connection: dict) -> McpTestResult` — 测试连接
    - `async discover_tools(connection: dict) -> list[dict]` — 发现工具并注册到 tools 集合
    - `async check_health(connection: dict) -> bool` — 健康检查
  - [ ] 使用 MCP Python SDK 的 `streamable_http_client` / `sse_client` 传输
  - [ ] 使用 `ClientSession` + `initialize()` 握手
  - [ ] 认证支持：无认证 / API Key（header）/ Bearer Token / Basic Auth
  - [ ] 连接池管理：`dict[str, ClientSession]` 按连接 ID 缓存活跃 session

- [ ] **T5: MCP 连接 Service 层** (AC: #2, #4)
  - [ ] 新建 `backend/app/services/mcp_connection_service.py`
  - [ ] `McpConnectionService` 静态方法类
  - [ ] CRUD 方法（参考 `tool_service.py` 模式）
  - [ ] `test_connection(conn_id)` — 调用 mcp_client 测试并更新状态
  - [ ] `discover_tools(conn_id)` — 调用 mcp_client 发现并注册工具
  - [ ] `sync_tools_on_reconnect(conn_id)` — 重连后同步工具
  - [ ] `delete_connection_cascade(conn_id)` — 级联删除关联工具

- [ ] **T6: MCP 连接 API 端点** (AC: #2, #3, #4)
  - [ ] 新建 `backend/app/api/v1/mcp.py`
  - [ ] `POST /mcp/connections` — 创建连接
  - [ ] `GET /mcp/connections` — 列表查询
  - [ ] `GET /mcp/connections/{id}` — 连接详情
  - [ ] `PUT /mcp/connections/{id}` — 更新连接
  - [ ] `DELETE /mcp/connections/{id}` — 删除连接（级联）
  - [ ] `POST /mcp/connections/{id}/test` — 测试连接
  - [ ] `POST /mcp/connections/{id}/discover` — 发现工具
  - [ ] 在 `router.py` 注册 mcp_router

- [ ] **T7: 健康检查后台任务** (AC: #5)
  - [ ] 修改 `backend/app/api/v1/health.py` — 添加 MCP 连接状态端点
  - [ ] （可选）Celery 定时任务检查所有 MCP 连接健康状态

- [ ] **T8: 数据库索引注册** (AC: #6)
  - [ ] 修改 `backend/app/db/indexes.py`
  - [ ] 添加 `mcp_connections` 集合索引
  - [ ] 添加 `tools` 集合的 `mcp_connection_id` 和 `source` 索引

- [ ] **T9: 单元测试** (AC: #8)
  - [ ] 新建 `backend/tests/models/test_mcp_connection.py`
  - [ ] 新建 `backend/tests/engine/test_mcp_client.py`
  - [ ] 新建 `backend/tests/services/test_mcp_connection_service.py`
  - [ ] 新建 `backend/tests/api/test_mcp.py`

### 前端（Frontend）

- [ ] **T10: MCP API 服务层** (AC: #7)
  - [ ] 新建 `frontend/src/services/mcp-api.ts`
  - [ ] 类型定义：`McpConnection / ConnectionStatus / AuthType` 等
  - [ ] API 方法：`list / get / create / update / remove / test / discover`
  - [ ] Query key factory

- [ ] **T11: MCP 页面对接真实 API** (AC: #7)
  - [ ] 修改 `frontend/src/pages/mcp-page.tsx`
  - [ ] 删除 Mock 数据，改用 TanStack Query 加载真实 MCP 连接列表
  - [ ] 添加 MCP 连接表单（Drawer 或 Modal）：name / url / protocol / auth_type / timeout
  - [ ] 连接测试按钮 → 调用 test API
  - [ ] 发现工具按钮 → 调用 discover API
  - [ ] 删除确认 → 调用 remove API
  - [ ] 状态 Tag 颜色根据 connection status 动态显示

## Dev Notes

### 技术栈与约定

**后端：**
- Python 包管理：**uv**（`uv run pytest`）
- MCP SDK：`mcp==1.27.2`（已安装）+ `langchain-mcp-adapters>=0.2.2`（已安装）
- MCP 传输协议：SSE (`sse_client`) 和 Streamable HTTP (`streamable_http_client`)
- 数据库：Motor 异步 MongoDB
- 日志：`loguru.logger`

**前端：**
- TanStack Query + Axios（参考 `agent-api.ts` 模式）
- Ant Design 组件（参考 `models-page.tsx` 的 Drawer/Modal 模式）

### MCP Python SDK 用法速查

```python
from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamable_http_client

# SSE 传输
async with sse_client(url="http://server/mcp/sse") as (read, write):
    async with ClientSession(read, write) as session:
        await session.initialize()
        tools = await session.list_tools()
        result = await session.call_tool("tool_name", arguments={"key": "value"})

# Streamable HTTP 传输
async with streamable_http_client(url="http://server/mcp") as (read, write, _):
    async with ClientSession(read, write) as session:
        await session.initialize()
        tools = await session.list_tools()
```

**MCP Tool 对象结构**（`list_tools()` 返回）：
```python
class Tool:
    name: str           # 工具名称
    description: str    # 工具描述
    inputSchema: dict   # JSON Schema 格式的输入参数定义
```

### 关键架构约束

1. **Tool 模型 `source` 字段**：已有 `"markdown"` 来源，MCP 工具设为 `"mcp"`
2. **统一工具池**：MCP 工具和 Markdown Skill 都存储在 `tools` 集合，Agent 配置时不感知来源差异
3. **连接信息独立存储**：MCP 连接配置存在 `mcp_connections` 集合，工具通过 `mcp_connection_id` 关联
4. **认证配置安全**：`auth_config` 中的敏感信息（API Key 等）应加密存储或至少不明文返回给前端
5. **MVP 范围**：本 Story 不实现 OAuth 认证（复杂度高），只支持 None / API Key / Bearer / Basic 四种简单认证

### 回归防护

**不能破坏的现有行为：**
1. 现有 Tool CRUD API 正常工作
2. Markdown Skill 上传流程不受影响
3. Agent 的 `tool_ids` 字段语义不变
4. 现有测试套件全部通过
5. `_resolve_tools()` 占位实现不变（Story 5-2 实现工具注入）

### 敏感信息处理

MCP 连接的 `auth_config` 可能包含 API Key、Bearer Token 等敏感信息：
- 存储时可以考虑加密（MVP 阶段先明文存储，后续加固）
- API 响应中 `auth_config` 的敏感字段用 `***` 脱敏显示
- 不在前端日志或网络请求中暴露完整密钥

### 文件清单

**后端新建的文件：**
- `backend/app/models/mcp_connection.py` — MCP 连接数据模型
- `backend/app/schemas/mcp_connection.py` — MCP 连接 Schema
- `backend/app/services/mcp_connection_service.py` — MCP 连接 Service
- `backend/app/api/v1/mcp.py` — MCP 连接 API 端点
- `backend/app/engine/tool/mcp_client.py` — MCP 客户端封装
- `backend/tests/models/test_mcp_connection.py` — 模型测试
- `backend/tests/engine/test_mcp_client.py` — MCP 客户端测试
- `backend/tests/services/test_mcp_connection_service.py` — Service 测试
- `backend/tests/api/test_mcp.py` — API 测试

**后端修改的文件：**
- `backend/app/models/tool.py` — 添加 `mcp_connection_id` 字段
- `backend/app/schemas/tool.py` — `ToolResponse` 添加 `mcp_connection_id`
- `backend/app/api/v1/router.py` — 注册 mcp_router
- `backend/app/db/indexes.py` — 添加 mcp_connections 和 tools 新索引

**前端新建的文件：**
- `frontend/src/services/mcp-api.ts` — MCP API 服务层

**前端修改的文件：**
- `frontend/src/pages/mcp-page.tsx` — Mock 改为真实 API 对接

### Dependencies

无需新增后端依赖（`mcp` 和 `langchain-mcp-adapters` 已安装）。

### References

- [Source: docs/planning-artifacts/epics.md#Story-3.2] — MCP 连接管理 Story 定义
- [Source: docs/planning-artifacts/architecture.md#engine/tool] — 工具引擎目录规划
- [Source: docs/planning-artifacts/architecture.md#Important-Gap-2] — MCP 连接生命周期缺口
- [Source: backend/app/models/tool.py] — Tool 模型（`source` 字段已预留 `"mcp"`）
- [Source: backend/app/engine/tool/skill_parser.py] — Skill 解析器（参考模式）
- [Source: backend/app/services/tool_service.py] — Tool Service（参考模式）
- [Source: backend/app/api/v1/tools.py] — Tool API（参考模式）
- [Source: frontend/src/pages/mcp-page.tsx] — 前端 MCP 页面（Mock，待对接）
- [Source: modelcontextprotocol/python-sdk] — MCP Python SDK 文档

### 不做的事

- **不做工具执行** — MCP 工具的实际调用在 Story 5-2（Agent 执行引擎）
- **不做 `_resolve_tools()` 实现** — 工具注入 Agent 运行时在 Story 5-2
- **不做 OAuth 认证** — MVP 只支持 None/API Key/Bearer/Basic，OAuth 后续扩展
- **不做 Celery 定时健康检查** — MVP 用按需检查（前端手动触发或 API 调用时检查），定时任务后续加
- **不做 WebSocket 传输** — MCP 传输协议只支持 SSE 和 Streamable HTTP

## Change Log

- 2026-06-10: Story 5-3 创建 — MCP 连接管理
- 2026-06-10: Story 5-3 实现完成 — 全部 10 个 task 完成，48 个后端测试通过，前端 TS 零错误，状态推进到 review

## Status

**Status:** review
