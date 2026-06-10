---
baseline_commit:
---

# Story 2.1: Agent 数据模型与后端 CRUD API

**Epic:** Epic 2 — Agent 生命周期管理
**Status:** ready-for-dev

## Story

As a 开发者，
I want 可以创建和管理 Agent 的数据模型，并通过 REST API 对 Agent 进行增删改查，
So that 后续的前端页面和 Agent 执行引擎可以基于这些 API 工作。

## Acceptance Criteria

- **AC1:** 开发者通过 API 创建 Agent（传入 name、description、system_prompt 等字段），Agent 记录写入 MongoDB，返回包含 agent_ulid 的完整对象
- **AC2:** 支持通过 `/api/v1/agents` 查询列表（分页），支持按 name、status 筛选
- **AC3:** 支持通过 `/api/v1/agents/{id}` 获取详情
- **AC4:** 支持编辑 Agent 配置（PUT 更新）
- **AC5:** 支持删除 Agent（需检查是否有活跃引用）
- **AC6:** Agent 数据模型包含字段：id、name、description、system_prompt、tool_ids、workflow_ids、knowledge_base_ids、model_config、status、version、created_at、updated_at
- **AC7:** 编辑已发布的 Agent 后不影响正在进行的对话，新对话使用新配置
- **AC8:** 权限控制：读权限需要 viewer+，写权限需要 developer+（对应 ROLE_PERMISSIONS）

## Tasks / Subtasks

- [x] **Model** — 创建 `backend/app/models/agent.py`，定义 AgentStatus 枚举和 Agent Pydantic 模型
- [x] **Schemas** — 创建 `backend/app/schemas/agent.py`，定义 AgentCreate/AgentUpdate/AgentResponse/AgentListResponse
- [x] **Service** — 创建 `backend/app/services/agent_service.py`，实现 CRUD 业务逻辑（含引用检查、版本自增）
- [x] **API** — 创建 `backend/app/api/v1/agents.py`，实现 5 个 REST 端点 + 注册到 router
- [x] **Indexes** — 更新 `backend/app/db/indexes.py`，添加 agents 集合索引
- [x] **Tests (API/Mock)** — 创建 `backend/tests/api/test_agents.py`，mock 层测试所有端点的正确行为、权限、错误情况
- [x] **Tests (Integration)** — 创建 `backend/tests/integration/test_agent_crud.py`，真实 MongoDB 测试 CRUD 完整流程
- [x] **Run & Verify** — 运行完整测试套件，确认无回归

## Dev Notes

- **命名约定**：ID 前缀使用 `agent_`（`generate_id("agent")`）
- **Model config**：使用 Pydantic BaseModel（非 Beanie/MongoEngine），与现有 User 模型保持一致
- **版本管理**：每次 PUT 更新自动递增 version 字段；编辑已发布的 Agent 创建新版本
- **Status 枚举**：`AgentStatus.DRAFT`, `AgentStatus.PUBLISHED`, `AgentStatus.ARCHIVED`
- **service 层**：采用与 `UserService` 一致的 staticmethod 模式，`_collection()` 返回 Motor 集合对象
- **model_config 字段**：存储为 dict，包含 `default_model`, `temperature`, `max_retry`, `routing_rules` 等配置
- **引用检查**：删除时检查是否有活跃 Task 引用该 Agent（预留逻辑，Task 模型尚不存在时仅做日志警告）
- **权限**：list/get 使用 `require_any_role("admin", "developer", "operator", "viewer")`，write 使用 `require_any_role("admin", "developer")`
- **API 风格**：与 admin router 保持一致，使用 FastAPI Depends + response_model + 中文错误消息

## Dev Agent Record

### Implementation Plan

1. 创建 Agent 数据模型（model）
2. 创建 API 请求/响应 schemas
3. 实现 Service 层 CRUD 逻辑
4. 实现 API 端点并注册路由
5. 更新数据库索引
6. 编写 mock 测试
7. 编写 integration 测试
8. 运行验证

### Debug Log

- **Pydantic model_config 冲突**: Pydantic v2 将 `model_config` 作为保留关键字用于 ConfigDict，需要将字段重命名为 `llm_config`
- **HTTP 状态码**: 名称冲突应返回 409 Conflict 而非 422 ValidationError，新增 `ConflictError` 异常类

### Completion Notes

Story 2.1 已完成全部 8 个任务：

1. **Model**: `AgentStatus` 枚举（draft/published/archived）+ `Agent` Pydantic 模型（含所有字段 + 默认值）
2. **Schemas**: `AgentCreate`/`AgentUpdate`/`AgentResponse`/`AgentListResponse`
3. **Service**: `AgentService` 静态方法模式，CRUD + 名称唯一性检查 + 版本自增 + 删除引用警告
4. **API**: 5 个端点（GET/POST list/create + GET/PUT/DELETE by ID）+ 路由注册
5. **Indexes**: 添加 `idx_agents_name`（唯一）+ `idx_agents_status`
6. **Mock 测试**: 19 个测试覆盖全部 5 个端点的正常、空数据、筛选、分页、401、403、404、409、422 情况
7. **Integration 测试**: 含真实 MongoDB 操作的 CRUD 完整流程（需 `--skip-integration` 跳过）
8. **验证**: 全部 117 个测试通过，ruff lint 通过

## File List

**创建的文件:**
- `backend/app/models/agent.py` — Agent 数据模型
- `backend/app/schemas/agent.py` — Agent API 请求/响应 schemas
- `backend/app/services/agent_service.py` — Agent CRUD 服务层
- `backend/app/api/v1/agents.py` — Agent API 端点
- `backend/tests/api/test_agents.py` — Mock 测试（19 个）
- `backend/tests/integration/test_agent_crud.py` — Integration 测试（14 个）

**修改的文件:**
- `backend/app/api/v1/router.py` — 注册 agents router
- `backend/app/db/indexes.py` — 添加 agents 索引
- `backend/tests/integration/conftest.py` — 添加 agents_collection + mock_agent_collection fixtures
- `backend/app/core/errors.py` — 新增 `ConflictError` 类（409）

## Change Log

- 2026-06-09: Story 2.1 首次实现 — Agent 数据模型与后端 CRUD API

## Status

**Status:** done
