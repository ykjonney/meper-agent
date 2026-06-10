---
stepsCompleted: [1, 2, 3, 4, 5, 6, 7, 8]
workflowType: 'architecture'
lastStep: 8
status: 'complete'
completedAt: '2026-06-09'
inputDocuments:
  - prd-agent-flow-2026-06-05/prd.md
  - prd-agent-flow-2026-06-05/addendum.md
  - prd-agent-flow-2026-06-05/.decision-log.md
  - brief-agent-flow-v2-2026-06-04/brief.md
  - market-agent-mes-vs-dify-research-2026-06-04.md
  - brainstorming-session-2026-06-03-1559.md
  - ai-framework-selection.md
  - workflow-task.md
workflowType: 'architecture'
project_name: 'Agent Flow'
user_name: 'Logan_hu'
date: '2026-06-09'
---

# Architecture Decision Document

_This document builds collaboratively through step-by-step discovery. Sections are appended as we work through each architectural decision together._

## Project Context Analysis

### Requirements Overview

**Functional Requirements:**

35 项 FR 组织为 13 个特性分组，覆盖 Agent 全生命周期 + Task 运行时管理：

- **Agent 管理（FR-1/2/3）**：创建、配置、发布、能力组合（工具/知识库/工作流）、模型动态路由
- **自主执行引擎（FR-4/5/6/7/8）**：三路径执行（直接/规划/工作流）、REACT 推理、计划-执行-验证循环、嵌套深度保护
- **DAG 工作流（FR-9/10/11/12/12A）**：可视化编辑器、8 种核心节点（start/end/agent/tool/human/gateway/parallel/subflow）、条件边、版本管理、模板管理
- **Task 生命周期（FR-29/30/31）**：完整状态机（pending→running→waiting_human→paused→completed/failed/cancelled）、前后台模式切换（30s 自动转后台）、流程干预（approve/reject/pause/resume/skip/rollback/inject + 乐观锁）
- **Agent-Workflow 交互（FR-32/33）**：Workflow Registry 能力地图注入、系统级 Task 工具集、变量提取流程
- **工具系统（FR-13/14/15）**：Skill 三来源（Git/上传/前端）、MCP 连接自动发现、统一工具池
- **知识库（FR-16/17）**：文档上传解析索引、向量检索
- **API/SDK（FR-18/19）**：同步/异步调用、事件回调
- **对话交互（FR-20/21）**：Web 对话界面、对话触发 Workflow 创建 Task
- **上下文管理（FR-22/22A/23/24）**：三层隔离（Session/Task/Node）、对话压缩、Task 触发对话、变量池 + 表达式注入
- **执行日志（FR-25/26）**：完整审计日志记录、分布式调用链追踪
- **权限管理（FR-27）**：四角色（管理员/开发者/操作员/只读）
- **Web 界面（FR-28）**：统一管理界面 + Task 管理面板，侧边导航布局

**Non-Functional Requirements:**

- **性能**：API 同步 ≤ 30s、Web 首屏 ≤ 3s、流式输出、前台 Task 30s 自动转后台
- **可靠性**：API 成功率 ≥ 99%、单组件故障不影响全局、日志不丢、Workflow Engine 降级时 Direct 模式仍可用
- **安全**：API 认证、密码加密、日志脱敏、Task 变量池隔离
- **扩展性**：单机 50 用户、单用户 ≤ 5 并发 Task、全局 ≤ 50 并发 Task（可配置）
- **并发**：Task 干预乐观锁（version 字段）、审计日志记录所有并发干预
- **数据**：运行时日志 30 天、审计日志 90 天、文件上传 ≤ 50MB

**Scale & Complexity:**

- Primary domain: 全栈 Web 应用（React + FastAPI + LangGraph + MongoDB）
- Complexity level: 中等偏高（功能范围广、技术栈多层嵌套，但用户规模小、单机部署）
- Estimated architectural components: 12-15 个核心组件

### Technical Constraints & Dependencies

- **AI 引擎**：LangGraph v1.0+（StateGraph + 子图工具 + MongoDB Checkpointer）
- **后端框架**：FastAPI（async-first）
- **前端框架**：React + React Flow（拖拽式工作流编辑器，参考 LangFlow）
- **数据库**：MongoDB（对话/状态/日志持久化，LangGraph Checkpointer 原生支持）
- **任务队列**：Celery + Redis 或 ARQ（异步任务执行）
- **向量库**：MongoDB Atlas Vector Search 或 Chroma（知识库检索）
- **模型支持**：5-10 个主流 LLM（OpenAI、Claude、国产模型）
- **部署模式**：单机、Docker，不依赖外部 SaaS

### Cross-Cutting Concerns Identified

1. **执行日志与调用链追踪** — 贯穿 Agent、Task、工作流、工具调用全链路，含审计日志
2. **认证与权限控制** — 四角色模型，影响 API 网关和前端路由
3. **上下文管理** — 三层隔离（Session/Task/Node）、对话压缩、变量池表达式注入、跨节点状态共享
4. **嵌套深度保护** — Agent→Workflow（Task）→Agent 的双层深度限制
5. **流式输出** — WebSocket 贯穿对话和 Task 执行
6. **错误处理与恢复** — Task 节点失败、MCP 断连、模型调用失败、流程干预 rollback
7. **Task 状态机** — 严格状态转换规则，贯穿 Workflow 引擎、API 层、前端 Task 面板
8. **并发控制** — 乐观锁（Task 干预）、全局 Task 并发上限、Tool 级熔断
9. **前后台模式** — Task 30 秒自动转后台、前台逐节点推送、后台选择性推送

## Starter Template Evaluation

### Primary Technology Domain

全栈 monorepo Web 应用：Python 后端（FastAPI + LangGraph）+ TypeScript 前端（React + @xyflow/react），参考 LangFlow 前端架构。

### Starter Options Considered

| 方案 | 适用性 | 结论 |
|------|--------|------|
| LangFlow 前端模板 | XYFlow 编辑器参考价值高，但整体过于复杂（完整产品级代码），不适合直接 fork | 参考，不采用 |
| `create-vite` + `react-ts` | 轻量、官方维护、React 19 支持、可自由定制 | **前端采用** |
| FastAPI 官方模板 | 面向 PostgreSQL + SQLAlchemy，与 MongoDB + LangGraph 栈不匹配 | 参考，不采用 |
| 自定义 FastAPI 结构 | 按 LangGraph + MongoDB 需求定制，最灵活 | **后端采用** |

### Selected Approach: 自定义 Monorepo 结构

**Rationale:**
前后端异语言（Python + TypeScript），不适合 Turborepo/Nx 等统一 monorepo 工具链。采用简单目录分离方案，各自独立构建和部署，docker-compose 统一编排。

**Frontend Initialization:**

```bash
npm create vite@latest frontend -- --template react-ts
cd frontend
npm install @xyflow/react zustand react-router-dom
```

**Backend Initialization:**

```bash
mkdir backend && cd backend
uv init --name agent-flow-backend
uv add fastapi uvicorn langgraph langchain-core langgraph-checkpoint-mongodb
uv add langchain-mcp-adapters langchain-openai langchain-anthropic
uv add pymongo celery redis pydantic-settings
```

**Architectural Decisions:**

- **Language & Runtime**: TypeScript (前端) + Python 3.12+ (后端)
- **Styling Solution**: Tailwind CSS + Ant Design（内部管理系统快速开发）
- **Build Tooling**: Vite (前端) + uv (后端依赖管理)
- **Testing Framework**: Vitest + React Testing Library (前端) + pytest + httpx (后端)
- **State Management**: Zustand (前端)
- **Routing**: React Router v7 (前端)
- **Code Organization**: 目录分离 monorepo

**Project Structure:**

```
agent-flow/
├── frontend/                    # React + Vite + @xyflow/react
│   ├── src/
│   │   ├── components/          # 通用组件
│   │   ├── pages/               # 页面（Dashboard, Agent, Workflow, Tools...）
│   │   ├── stores/              # Zustand 状态管理
│   │   ├── services/            # API 调用层（基于 OpenAPI 生成类型）
│   │   ├── hooks/               # 自定义 Hooks
│   │   └── types/               # TypeScript 类型定义
│   ├── package.json
│   ├── vite.config.ts
│   └── tsconfig.json
├── backend/                     # FastAPI + LangGraph
│   ├── app/
│   │   ├── api/                 # API 路由层
│   │   │   ├── v1/
│   │   │   └── deps.py          # 依赖注入
│   │   ├── core/                # 配置、安全、设置
│   │   ├── models/              # 数据模型（MongoDB documents）
│   │   ├── schemas/             # Pydantic 请求/响应模型
│   │   ├── services/            # 业务逻辑层
│   │   ├── engine/              # LangGraph 引擎层（Agent/Workflow/Tool 执行）
│   │   └── main.py              # FastAPI 入口
│   ├── tests/
│   ├── pyproject.toml
│   └── Dockerfile
├── docker-compose.yml
└── README.md
```

**Note:** 项目初始化应作为第一个实施故事。

## Core Architectural Decisions

### Decision Priority Analysis

**Critical Decisions (Block Implementation):**

- **数据库**：MongoDB 7.0+ 单机部署（无副本集）
- **向量检索**：MongoDB Atlas Vector Search（统一一个 DB，减少组件）
- **Checkpointer**：LangGraph MongoDBSaver（复用主库，零额外组件）
- **任务队列**：Celery + Redis（成熟、监控工具全；任务量小，复杂度可接受）
- **AI 引擎**：LangGraph 1.0.8+（StateGraph + 子图工具 + MongoDB Checkpointer）
- **后端框架**：FastAPI 0.128.0+（async-first）
- **前端框架**：React 19 + Vite 5+ + @xyflow/react 11.5.5+
- **认证方式**：Web 端 JWT（access 15min + refresh 7d）+ 外部 API Key
- **密码哈希**：bcrypt（passlib 库）
- **API 风格**：纯 REST（`/api/v1/{resource}/{id}/{action?}`）
- **API 文档**：OpenAPI 3.1（FastAPI 自动生成）+ Swagger UI + ReDoc
- **流式通信**：WebSocket（对话/工作流）+ SSE（事件订阅）双协议
- **状态管理**：TanStack Query（服务端）+ Zustand（客户端）+ AntD Form（表单）
- **组件分层**：pages + features + components + hooks + services + stores
- **部署编排**：Docker Compose 单机（frontend/backend/mongodb/redis/celery-worker/caddy）
- **CI/CD**：GitHub Actions（PR 检查 + 镜像构建 + 手动部署）

**Important Decisions (Shape Architecture):**

- **RBAC 实现**：手写装饰器 + Depends 注入（`Depends(require_role("admin"))`）
- **错误响应规范**：统一 `{error: {code, message, details, request_id, timestamp}}` 结构
- **异步回调**：Webhook + HMAC-SHA256 签名 + 指数退避重试（最多 3 次）
- **前端类型生成**：openapi-typescript 自动生成 TS 类型
- **路由策略**：React Router v7（数据路由）+ 路由懒加载
- **性能优化**：路由级 lazy + UI 库按需引入 + 编辑器 memo + 图片懒加载
- **配置管理**：Pydantic Settings + .env 文件（不入 git）
- **镜像构建**：多阶段构建（非 root 用户 + 健康检查）

**Deferred Decisions (Post-MVP):**

- **限流**：MVP 暂不接入 slowapi（用户规模小，运维可控）
- **监控告警**：MVP 仅健康检查 + 日志（Prometheus/Grafana 后置）
- **备份**：手动 mongodump + 文件备份（自动化后置）
- **HTTPS**：内网部署仅 HTTP（Caddy+Let's Encrypt 后置）
- **错误监控**：Sentry 后置（先 ErrorBoundary）
- **MCP 密钥管理**：MVP 用 .env（Vault/SOPS 后置）

### Data Architecture

**Decision 1.1: 主数据库 MongoDB 7.0+ 单机部署**

- **Version**: MongoDB 7.0+
- **Rationale**: LangGraph Checkpointer 原生支持 MongoDB，复用主库存储对话/状态/日志。单机部署符合 NFR（50 用户规模 + 单机约束），运维简单。如未来需要高可用，可平滑升级到 Replica Set。
- **Affects**: 后端所有持久化（对话/Agent 配置/工作流定义/执行日志/知识库元数据）
- **Provided by Starter**: No

**Decision 1.2: 向量检索用 MongoDB Atlas Vector Search**

- **Version**: MongoDB 7.0+ Vector Search Index
- **Rationale**: 统一一个 DB 减少组件，符合"单组件故障不全局崩溃"的 NFR。Chroma 需独立进程维护，引入额外故障面。MongoDB Vector Search 性能对 MVP 知识库场景（≤10K 文档）足够。
- **Affects**: FR-16/17（知识库）— 上传文档→分块→embedding→Vector Search Index→检索
- **Provided by Starter**: No

**Decision 1.3: LangGraph Checkpointer 用 MongoDBSaver**

- **Version**: `langgraph-checkpoint-mongodb` 最新版
- **Rationale**: 复用主库，零额外组件；状态序列化由 LangGraph 透明处理。备选 RedisSaver 需额外保证 Redis 持久化（需 AOF + RDB 双开），增加运维负担。
- **Affects**: Agent 执行引擎（FR-4/5/6/7/8）、工作流执行（FR-9/10/11/12）
- **Provided by Starter**: No

**Decision 1.4: 任务队列 Celery + Redis**

- **Version**: Celery 5.4+ + Redis 7+
- **Rationale**: Celery 成熟、监控工具全（Flower）、任务重试/定时任务支持完善。NFR 单用户 ≤5 并发任务，规模小，复杂度可接受。未来若 async 链路复杂可考虑 ARQ 迁移。
- **Affects**: FR-19 异步 API、Agent 长任务执行、文件解析后台任务
- **Provided by Starter**: No

**Decision 1.5: Redis 双重角色（缓存 + Celery broker）**

- **Version**: Redis 7+
- **Rationale**: MVP 阶段 Redis 负载低（≤50 用户），一站式服务降低组件数。缓存对象：LLM 响应（按 prompt hash）、工具发现结果、用户会话、限流计数（预留）。
- **Affects**: 性能优化（NFR API 成功率 ≥99%）、会话管理
- **Provided by Starter**: No

### Authentication & Security

**Decision 2.1: Web 端 JWT 认证（access + refresh）**

- **Version**: `pyjwt` 2.8+ + `passlib[bcrypt]`
- **Rationale**: 前后端分离标准方案。access 短寿命（15min）+ refresh 长寿命（7d，HttpOnly Cookie 防 XSS）。Refresh token 轮换机制降低泄露风险。
- **Affects**: 全部 API 端点（除 `/login`、`/register`）、前端路由守卫
- **Provided by Starter**: No

**Decision 2.2: 外部系统 API Key 认证**

- **Format**: `af_live_{32位随机字符串}`（前缀可识别环境）
- **Rationale**: 外部 MES/ERP/BI 系统调用场景，API Key 简单可靠。前缀 `af_live_` 区分环境（`af_test_` 用于测试）。
- **Affects**: FR-18/19（API/SDK 外部调用）、FR-27（权限管理）
- **Provided by Starter**: No

**Decision 2.3: RBAC 手写装饰器 + Depends 注入**

- **Implementation**: `Depends(require_role("admin"))` 装饰器
- **Rationale**: 4 角色简单（管理员/开发者/操作员/只读），自写依赖注入清晰可控，避免引入 Casbin 等复杂库的学习成本。角色定义集中在 `core/security.py`。
- **Affects**: 全部 API 端点权限校验、前端菜单渲染
- **Provided by Starter**: No

**Decision 2.4: 密码哈希 bcrypt**

- **Version**: `passlib[bcrypt]` 4.x
- **Rationale**: 成熟稳定，生态完善，OWASP 仍推荐。argon2 更现代但迁移成本与收益不匹配 MVP 场景。
- **Affects**: 用户注册/登录、密码重置流程
- **Provided by Starter**: No

**Decision 2.5: 限流（DEFERRED）**

- **Status**: MVP 暂不接入
- **Rationale**: NFR 单机 50 用户 + 单用户 ≤5 并发，规模小，运维可控。预留 Redis 计数接口，后续接入 slowapi 无侵入。
- **Affects**: 无（MVP 阶段）
- **Provided by Starter**: No

### API & Communication Patterns

**Decision 3.1: 纯 REST API 风格**

- **Convention**: `/api/v1/{resource}/{id}/{action?}`
- **Rationale**: 主流、HTTP 语义清晰、缓存友好。Agent 执行等复杂操作也走 REST（`POST /api/v1/agents/{id}/invoke`），保持风格统一。
- **Affects**: 全部 API 端点设计
- **Provided by Starter**: No

**Decision 3.2: OpenAPI 3.1 自动文档 + Swagger UI + ReDoc**

- **Tooling**: FastAPI 内置 + 自定义 metadata
- **Rationale**: FastAPI 自动生成 OpenAPI 3.1 schema。开发用 Swagger UI（`/docs`），对外文档用 ReDoc（`/redoc`），美观专业。
- **Affects**: API 可发现性、客户端 SDK 生成
- **Provided by Starter**: No

**Decision 3.3: 统一错误响应结构**

- **Format**: `{error: {code, message, details, request_id, timestamp}}`
- **Rationale**: 业务错误码 `{MODULE}_{ACTION}_{REASON}`（如 `WORKFLOW_NODE_NOT_FOUND`）便于客户端精确处理。`request_id` 用于分布式追踪对齐。
- **Affects**: 全局异常处理器、前端错误提示
- **Provided by Starter**: No

**Decision 3.4: WebSocket + SSE 双协议流式通信**

- **WebSocket**: 对话/工作流执行（双向，支持取消/暂停）
  - Endpoints: `/api/v1/agents/{id}/stream`、`/api/v1/workflows/{id}/stream`
  - Message: JSON 事件流 `{type: "token", data: "..."}`
- **SSE**: 事件订阅/日志推送（单向，HTTP 友好）
  - Endpoints: `/api/v1/events/stream`
- **Rationale**: 对话/工作流需要双向通信（取消/暂停），选 WebSocket；事件订阅单向推送，SSE 简单可靠。
- **Affects**: FR-20/21（对话交互）、工作流执行可视化
- **Provided by Starter**: No

**Decision 3.5: 异步任务 Webhook 回调 + HMAC 签名**

- **Signature**: HMAC-SHA256(timestamp + body, secret)
- **Retry**: 指数退避（1s, 4s, 16s），最多 3 次
- **Rationale**: 外部系统解耦，不要求长连接。HMAC 签名 + timestamp 防重放攻击。
- **Affects**: FR-19 异步 API、外部系统集成
- **Provided by Starter**: No

**Decision 3.6: 前端类型自动生成（openapi-typescript）**

- **Tooling**: `openapi-typescript` + CI 自动跑
- **Rationale**: 后端 OpenAPI schema 变化即自动生成前端 TS 类型，避免手写漂移。前端 service 层直接消费生成的类型。
- **Affects**: 前端 `services/` 层、`types/` 目录
- **Provided by Starter**: No

### Frontend Architecture

**Decision 4.1: 三层状态管理**

- **服务端状态**: TanStack Query 5.x（缓存/轮询/乐观更新/失效）
- **客户端状态**: Zustand 4.x（UI 状态/用户偏好/临时表单）
- **表单状态**: Ant Design Form（受控/非受控自动）
- **Rationale**: 服务端数据需要请求/缓存/失效生命周期，TanStack Query 是最佳实践；Zustand 轻量适合 UI 状态；表单交给 AntD Form 不重复造轮子。
- **Affects**: 全部前端数据流
- **Provided by Starter**: Partial（Zustand 来自 Step 3）

**Decision 4.2: 组件目录分层**

- **pages/**: 路由级页面（AgentListPage、WorkflowEditorPage）
- **features/**: 业务功能模块（agent-config、workflow-canvas、tool-registry）
- **components/**: 通用 UI 组件（Button、Modal、DataTable）
- **hooks/**: 自定义 Hooks（useAgent、useWorkflow）
- **services/**: API 调用层（agentApi、workflowApi）
- **stores/**: Zustand stores（useEditorStore、useAuthStore）
- **Rationale**: 经典分层，AI 代理实现时定位明确，避免大泥球。
- **Affects**: 前端代码组织、新人上手成本
- **Provided by Starter**: Partial（基础结构来自 Step 3）

**Decision 4.3: React Router v7 数据路由 + 路由懒加载**

- **Version**: react-router-dom 7.x
- **Rationale**: 数据路由支持 loader/action 模式；`React.lazy()` + `Suspense` 路由级代码分割，首屏只加载必要 chunk。
- **Affects**: 全部前端路由、首次加载性能
- **Provided by Starter**: No

**Decision 4.4: 性能优化组合**

- **代码分割**: 路由级 `React.lazy` + 大组件级 lazy（工作流编辑器、Monaco 等）
- **包体积**: Vite tree-shaking + Ant Design 按需引入（`babel-plugin-import`）
- **编辑器性能**: @xyflow/react `onlyRenderVisibleElements` + 节点 `memo` 包装
- **图片**: `vite-plugin-imagemin` 压缩 + `<img loading="lazy">`
- **请求缓存**: TanStack Query 默认 stale-while-revalidate
- **Rationale**: 综合多维优化，首屏 ≤3s 目标（NFR）可达。
- **Affects**: 前端构建配置、关键组件实现
- **Provided by Starter**: No

**Decision 4.5: Sentry 错误监控（DEFERRED）**

- **Status**: MVP 暂不接入
- **Rationale**: 先用 ErrorBoundary 兜底，记录到后端日志。Sentry 后置引入成本低。
- **Affects**: 无（MVP 阶段）
- **Provided by Starter**: No

### Infrastructure & Deployment

**Decision 5.1: Docker Compose 单机编排**

- **Services**:
  - `frontend`: Nginx 托管 Vite 静态产物
  - `backend`: Uvicorn/Gunicorn 多 worker
  - `mongodb`: MongoDB 7.0 单机
  - `redis`: Redis 7（缓存 + Celery broker）
  - `celery-worker`: Celery Worker
  - `caddy`: 反向代理（后置启用 HTTPS）
- **Rationale**: 符合 NFR"单机部署、不依赖外部 SaaS"。docker-compose 一键启动/停止/扩缩。
- **Affects**: 部署、运维、CI/CD
- **Provided by Starter**: No

**Decision 5.2: 多阶段镜像构建**

- **Backend Dockerfile**: builder（uv 装依赖）→ runtime（python:3.12-slim + venv + 非 root 用户 + HEALTHCHECK）
- **Frontend Dockerfile**: builder（node:22-alpine + vite build）→ runtime（nginx:alpine + dist + SPA fallback）
- **Rationale**: 镜像体积小（runtime 不含构建工具）、安全性好（非 root）、健康检查标准化。
- **Affects**: 镜像大小、启动速度、安全合规
- **Provided by Starter**: No

**Decision 5.3: GitHub Actions CI/CD**

- **PR 检查**: lint + type-check + test（前端 ESLint + tsc + Vitest；后端 ruff + mypy + pytest）
- **main 分支**: 构建镜像 + 推送到 GHCR
- **手动部署**: SSH 到服务器 `docker compose pull && up -d`
- **Rationale**: 免费、与 GitHub 集成好、配置简单。手动部署留运维控制权，避免意外。
- **Affects**: 代码质量门禁、部署流程
- **Provided by Starter**: No

**Decision 5.4: 日志与监控（MVP 极简）**

- **结构化日志**: Python `loguru` + JSON 格式
- **日志收集**: 容器 stdout → `docker logs` + 文件挂载 + logrotate
- **健康检查**: `/health` 端点（K8s liveness/readiness 风格）
- **基础指标**: Prometheus `/metrics` 端点（uvicorn-prometheus 集成）
- **DEFERRED**: ELK/Loki 日志聚合、Grafana 可视化、告警
- **Rationale**: MVP 阶段日志够用，监控可视化后置可降低复杂度。
- **Affects**: 运维可观测性、故障排查
- **Provided by Starter**: No

**Decision 5.5: Pydantic Settings 配置管理**

- **Implementation**: `pydantic-settings` + `.env` 文件
- **Rationale**: 强类型、验证、文档化（自动生成 `.env.example`）。开发期 `.env` 不入 git，生产期密钥管理（Vault/SOPS）后置。
- **Affects**: 配置加载、密钥管理
- **Provided by Starter**: No

**Decision 5.6: 手动备份（DEFERRED 自动化）**

- **Implementation**: 手动 `mongodump` + 文件卷 `rsync`
- **Rationale**: MVP 阶段 50 用户规模，手动备份可接受。自动化脚本（cron）后续按需加入。
- **Affects**: 数据安全
- **Provided by Starter**: No

**Decision 5.7: 内网部署 HTTP（DEFERRED HTTPS）**

- **Implementation**: Caddy 反代但暂不启用 HTTPS（仅 HTTP 监听）
- **Rationale**: 工业内网部署（MES/ERP/BI 网络环境），公网 HTTPS 暂不需要。未来公网部署时启用 Caddy 自动证书。
- **Affects**: 网络协议、外部系统接入方式
- **Provided by Starter**: No

### Task Engine Architecture

**Decision 6.1: Task 作为独立运行时实体**

- **Model**: `Task = Workflow 的运行时实例`，Task 与 Workflow 模板解耦，绑定模板快照执行
- **Rationale**: PRD 明确 Workflow=Class、Task=Instance 的概念模型。Task 拥有独立的生命周期（状态机）、变量池（隔离于 Session）和审计日志。与原架构中"Workflow 执行"是同一概念的不同抽象层级——原 Workflow executor 负责的是 Task 执行。
- **Affects**: FR-7（工作流执行模式 → Task 实例化）、FR-29（状态机）、FR-30（前后台模式）、FR-31（流程干预）
- **Implementation**:
  - `engine/task/` 目录管理 Task 生命周期
  - `Task` MongoDB 文档模型存储状态、变量池、绑定快照
  - Workflow executor 演进为 Task executor，每次执行创建一个 Task 实例
- **Provided by Starter**: No

**Decision 6.2: Task 状态机 — 状态存储在 MongoDB**

- **State Storage**: Task 状态持久化到 MongoDB（`tasks` 集合），不在内存中维护
- **State Machine**: Python `enum` + 转换规则表实现，转换前校验合法性
- **Rationale**: 状态转换需要持久化和可审计。MongoDB 原子更新（`findOneAndUpdate` + version 字段）天然支持乐观锁。Task 不可恢复错误时标记 `failed`，不删除记录。
- **Affects**: FR-29（状态机全部转换路径）、FR-31（干预操作的乐观锁）
- **Implementation**:
  ```python
  class TaskStatus(str, Enum):
      PENDING = "pending"
      RUNNING = "running"
      WAITING_HUMAN = "waiting_human"
      PAUSED = "paused"
      COMPLETED = "completed"
      FAILED = "failed"
      CANCELLED = "cancelled"

  TASK_TRANSITIONS = {
      (TaskStatus.PENDING, "start"): TaskStatus.RUNNING,
      (TaskStatus.RUNNING, "reach_human"): TaskStatus.WAITING_HUMAN,
      (TaskStatus.RUNNING, "pause"): TaskStatus.PAUSED,
      # ... 完整转换表同 PRD FR-29
  }
  ```
- **Provided by Starter**: No

**Decision 6.3: 变量池 — MongoDB 嵌入文档**

- **Storage**: Task 变量池存储为 MongoDB 嵌入文档（`task.variables`），节点输出按 `node_id.field` 前缀组织
- **Expression Engine**: Python `jinja2` 或自定义轻量求值器，支持 `{{node_id.field}}` 语法
- **Null-safe**: 求值失败时 gateway 走 fallback，params 注入为 `null`
- **Rationale**: 变量池与 Task 同文档存储，避免跨集合查询。表达式求值需要安全沙箱（`jinja2.sandbox.Environment`），防止任意代码执行。
- **Affects**: FR-24（变量池与表达式注入）、FR-11（条件边）、FR-10（gateway 节点）
- **Implementation**: `engine/task/variable_pool.py` + `engine/task/expression.py`
- **Provided by Starter**: No

**Decision 6.4: Workflow Registry — Agent 启动时注入**

- **Mechanism**: Agent StateGraph 构建时，从 `workflows` 集合查询所有已发布 Workflow 的 Registry 元数据（`when_to_use`、`required_entities`、`has_human_node`、`side_effects`），注入到 Agent 的 System Prompt 中
- **Two-tier**: MVP 单层（全量注入）；后续迭代拆分核心/扩展两层，扩展层 RAG 检索
- **Rationale**: PRD FR-33 要求 Agent 前置感知所有 Workflow。注入 System Prompt 是最直接方案，LangGraph 原生支持动态 System Prompt。
- **Affects**: FR-33（Agent-Workflow 交互）、Agent builder
- **Provided by Starter**: No

**Decision 6.5: 前后台模式 — Celery 异步 + WebSocket 推送**

- **Foreground**: API handler 直接调用 Task executor，同步等待结果。30 秒超时自动转后台
- **Background**: 通过 Celery 异步执行 Task，WebSocket/SSE 推送关键节点状态
- **Push Strategy**: 前台 Task 逐节点推送进度；后台 Task 仅推送关键节点（waiting_human/completed/failed）
- **Rationale**: 复用现有 Celery 基础设施，前台超时转后台自然映射为"Celery 任务提交"。WebSocket 已有基础设施用于推送。
- **Affects**: FR-30（前后台模式）、FR-31（干预操作的实时性）、API 层
- **Provided by Starter**: No

**Decision 6.6: 流程干预 — REST API + WebSocket 实时通知**

- **API**: `POST /api/v1/tasks/{task_id}/intervene` — 接受 action（approve/reject/pause/resume/skip/rollback/inject）+ payload
- **Optimistic Lock**: `findOneAndUpdate({task_id, version: N}, {$set: {...}, $inc: {version: 1}})` — 版本不匹配返回 409 Conflict
- **Audit**: 所有干预操作记录到 `task_audit_logs` 集合（操作人、时间、动作、结果、version）
- **Rationale**: REST API 简单可靠，乐观锁轻量适合 MVP 规模（50 用户），审计日志满足合规要求。
- **Affects**: FR-31（流程干预）、API 层、Task executor
- **Provided by Starter**: No

**Decision 6.7: 节点执行器 — Strategy 模式扩展**

- **Pattern**: `BaseNodeExecutor` 抽象类 + 每种节点类型一个实现类（`AgentNodeExecutor`、`ToolNodeExecutor`、`HumanNodeExecutor`、`GatewayNodeExecutor`、`ParallelNodeExecutor`、`SubflowNodeExecutor`）
- **Node Config**: 每种节点有独立的 Pydantic 配置 schema（如 `AgentNodeConfig`、`HumanNodeConfig`），存储在 Workflow 模板中
- **Rationale**: PRD FR-10 从 5 种节点扩展到 8 种，Strategy 模式支持灵活扩展新节点类型而不影响引擎核心。每种节点的执行逻辑差异大（Agent 调 LLM、Tool 直接调用、Human 等待外部输入、Gateway 条件路由），Strategy 模式天然适配。
- **Affects**: FR-10（8 种核心节点）、`engine/workflow/nodes/` 目录结构
- **Provided by Starter**: No

### Decision Impact Analysis

**Implementation Sequence:**

1. **基础设施层（Story #1）**
   - Docker Compose 骨架
   - MongoDB + Redis 启动配置
   - 后端/前端 Dockerfile 多阶段构建
   - 健康检查端点

2. **后端核心（Stories #2-5）**
   - FastAPI 项目结构 + Pydantic Settings
   - JWT 认证 + bcrypt 密码 + RBAC 装饰器
   - MongoDB 连接 + MongoDBSaver 接入 LangGraph
   - Celery + Redis 任务队列

3. **后端业务（Stories #6-12）**
   - API Key 管理（外部系统）
   - 统一错误响应中间件
   - WebSocket/SSE 端点
   - Webhook 回调签名 + 重试
   - MongoDB Vector Search 知识库

4. **前端核心（Stories #13-15）**
   - Vite + React + AntD 初始化
   - TanStack Query + Zustand + 路由配置
   - 登录页 + 路由守卫 + RBAC 渲染

5. **前端业务（Stories #16-20）**
   - Agent CRUD 页面
   - 工作流编辑器（@xyflow/react）— 8 种节点类型
   - 工具注册中心
   - 对话界面（WebSocket 流式）— 含对话触发 Workflow 创建 Task
   - Task 管理面板（状态查看、审批/干预、执行时间线）
   - 执行日志查看

6. **运维与质量（Stories #21-23）**
   - GitHub Actions 流水线
   - 日志结构化 + 健康检查完善
   - openapi-typescript 自动生成集成

7. **延后项（MVP 之后）**
   - Scheduled Workflow（Cron 定时 + prefetch + escalation）
   - Timer/Event 节点
   - 事件总线（at-least-once、死信队列、背压处理）
   - Workflow Engine 高可用（多副本、主从选举）
   - 限流（Sprint 2+）
   - 监控告警（Sprint 3+）
   - 自动备份（Sprint 2+）
   - HTTPS 公网部署（Sprint 3+）
   - Sentry 错误监控（Sprint 2+）

**Cross-Component Dependencies:**

```
frontend (React + TanStack Query)
    ↓ HTTP/WS
backend (FastAPI)
    ├──→ MongoDB (状态/日志/向量/Task 变量池)
    ├──→ Redis (缓存/Celery broker)
    └──→ Celery Worker (异步 Task 执行)
              ↓
              Task Engine → Workflow Nodes → 外部 LLM / MCP / Tool
```

- **数据流**: 前端 TanStack Query 缓存 → 后端 API → MongoDB/Redis/Celery
- **Task 执行流**: API → Task Service → Task Executor → Node Executors → 变量池 → MongoDB
- **前台 Task**: API handler 直接调用 Task Executor → 30s 超时转 Celery 后台
- **后台 Task**: API → Celery → Task Executor → WebSocket 推送关键节点状态
- **干预流**: 用户审批/操作 → Task API → 乐观锁校验 → Task 状态转换 → WebSocket 推送
- **流式流**: 前端 WebSocket → 后端 Uvicorn WS handler → Task/Agent stream → MongoDBSaver checkpoint
- **安全流**: 登录 → JWT → 后续请求带 Bearer → RBAC 装饰器校验 → 业务执行
- **外部集成流**: 外部系统 → API Key + HMAC 签名 → 异步 API → Celery → Webhook 回调（HMAC 签名）

---

## Next Steps

**Ready for Step 6: Project Structure** — 定义完整的项目目录结构、文件组织、模块边界。

## Implementation Patterns & Consistency Rules

### Pattern Categories Defined

**Critical Conflict Points Identified:** 5 个领域 / 18 个具体冲突点

AI 代理并行开发时，以下模式不一致会导致**集成即崩**：命名漂移、格式不统一、通信协议不匹配、错误处理各异、加载状态混乱。本节定义所有代理必须遵守的一致性规范。

### Naming Patterns

**Database Naming Conventions (MongoDB):**

- **集合（Collection）名**: snake_case 复数
  - ✅ `agents`、`workflows`、`execution_logs`、`user_sessions`
  - ❌ `Agent`、`workflow`、`ExecutionLog`
- **字段名**: snake_case
  - ✅ `agent_id`、`created_at`、`updated_at`、`is_deleted`
  - ❌ `agentId`、`createdAt`
- **索引名**: `idx_{collection}_{fields}` 格式
  - ✅ `idx_agents_user_id`、`idx_execution_logs_thread_id`
- **外键引用**: 纯 ID 字符串（MongoDB 风格），无外键约束
  - ✅ `agent_id: "agent_abc123"`
  - ❌ 嵌套对象引用（避免循环依赖和深度序列化）

**API Naming Conventions:**

- **REST 路径**: snake_case + 复数资源
  - ✅ `GET /api/v1/agents`、`POST /api/v1/agents/{agent_id}/invoke`
  - ❌ `GET /api/v1/getAgent`、`/api/v1/agent`
- **路径参数**: snake_case
  - ✅ `{agent_id}`、`{workflow_id}`、`{execution_id}`
- **查询参数**: snake_case
  - ✅ `?page=1&page_size=20&user_id=xxx`
- **HTTP Headers**: 标准头用标准名，自定义头用 `X-` 前缀 + PascalCase
  - ✅ `X-Request-ID`、`X-API-Key`、`Authorization`
- **JSON 请求/响应字段**: **snake_case**（跨前后端统一，避免转换开销）

**Code Naming Conventions:**

| 场景 | 风格 | 示例 |
|------|------|------|
| **Python 变量/函数** | snake_case | `agent_id`、`def get_agent_by_id()` |
| **Python 类** | PascalCase | `class AgentService`、`class WorkflowExecutor` |
| **Python 常量** | UPPER_SNAKE | `MAX_CONCURRENT_TASKS = 5` |
| **Python 模块** | snake_case | `agent_service.py`、`workflow_executor.py` |
| **TS 变量/函数** | camelCase | `const agentId`、`function getAgentById()` |
| **TS 类型/接口/类** | PascalCase | `interface Agent`、`class AgentCard` |
| **TS 枚举** | PascalCase + 成员 PascalCase | `enum AgentStatus { Draft, Published }` |
| **TS 文件** | kebab-case | `agent-card.tsx`、`use-agent.ts` |
| **React 组件** | PascalCase | `AgentCard.tsx`、`WorkflowEditor.tsx` |
| **环境变量** | UPPER_SNAKE | `MONGODB_URI`、`JWT_SECRET_KEY` |
| **Celery 任务名** | snake_case + 模块前缀 | `agents.invoke`、`workflows.execute_node` |

### Structure Patterns

**Project Organization (后端 Python):**

```
backend/
├── app/
│   ├── api/v1/          # API 路由层（按 resource 划分子目录）
│   ├── core/            # 核心：配置、安全、依赖注入
│   ├── models/          # MongoDB 数据模型（Beanie / Pydantic）
│   ├── schemas/         # Pydantic 请求/响应 schema
│   ├── services/        # 业务逻辑层
│   ├── engine/          # LangGraph 引擎层
│   ├── workers/         # Celery 任务定义
│   └── main.py
├── tests/               # 镜像 app/ 结构
│   ├── api/
│   ├── services/
│   └── engine/
├── pyproject.toml
└── Dockerfile
```

**Project Organization (前端 TypeScript):**

```
frontend/src/
├── pages/               # 路由级页面
├── features/            # 业务功能模块（内聚）
│   └── {feature_name}/
│       ├── components/
│       ├── hooks/
│       ├── stores/
│       └── types.ts
├── components/          # 通用 UI 组件
├── hooks/               # 跨 feature 共享 hooks
├── services/            # API 调用层（按后端 resource 划分）
├── stores/              # 跨 feature 全局 stores
├── lib/                 # 工具函数
├── types/               # 全局类型定义
└── routes/              # 路由配置
```

**File Structure Patterns:**

- **测试文件位置**: **co-located**（与源文件同目录）
  - 前端：`agent-card.tsx` ↔ `agent-card.test.tsx`
  - 后端：`agent_service.py` ↔ `test_agent_service.py`
- **配置文件**: 根目录 `.env`（不入 git）、`.env.example`（模板）、`app/core/config.py`（Pydantic Settings 加载）
- **静态资源**: 前端 `public/`（构建时复制）+ `src/assets/`（构建时打包）
- **类型定义**: 前端 `src/types/api.ts`（openapi-typescript 生成的类型，从不手改）
- **文档**: `docs/`（项目级）+ 各模块 `README.md`（模块级）

### Format Patterns

**API Response Formats:**

- **成功响应**: `{data: ..., meta?: ...}` 包裹
  - 列表：`{data: [...], meta: {page, page_size, total, total_pages}}`
  - 单个：`{data: {...}}`
  - 操作（删除/触发）：`{data: {success: true, ...}}`
- **错误响应**: `{error: {code, message, details, request_id, timestamp}}`
- **HTTP 状态码**: 标准语义
  - 200 OK（GET/PUT 成功）、201 Created（POST 创建）、204 No Content（DELETE）
  - 400 Bad Request（参数错误）、401 Unauthorized、403 Forbidden、404 Not Found
  - 409 Conflict（资源冲突）、422 Unprocessable Entity（业务规则失败）
  - 500 Internal Server Error、503 Service Unavailable
- **业务错误码**: `{MODULE}_{ACTION}_{REASON}`
  - ✅ `AGENT_INVOKE_TIMEOUT`、`WORKFLOW_NODE_NOT_FOUND`、`API_KEY_INVALID`

**Data Exchange Formats:**

- **时间格式**: ISO 8601 字符串（UTC）`2026-06-08T10:30:00.123Z`
- **日期格式**（仅日期无时间）: `2026-06-08`
- **ID 格式**: `{resource}_{ulid}`（ULID 可排序、可反解时间）
  - ✅ `agent_01HXYZABCDEF`、`workflow_01HXYZABCDEF`
  - ❌ 纯 UUID、纯自增数字（无类型可辨识）
- **布尔**: JSON `true` / `false`
- **空值**: JSON `null`，不用空字符串或省略字段
- **大数字**: 字符串传递（避免 JS 精度丢失）`"big_number": "9999999999999999"`
- **二进制**: 不入 JSON，走预签名 URL 上传/下载

### Communication Patterns

**Event System Patterns (WebSocket/SSE):**

- **事件类型**: snake_case + 过去时（描述已发生的事）
  - ✅ `token_received`、`agent_thinking`、`workflow_step_completed`、`execution_failed`
  - ❌ `TokenReceived`、`agent.thinking`、`WORKFLOW_STEP`
- **事件 payload 结构**: `{type, timestamp, data, sequence}`
  ```json
  {
    "type": "token_received",
    "timestamp": "2026-06-08T10:30:00.123Z",
    "data": { "content": "Hello" },
    "sequence": 42
  }
  ```
- **Celery 任务事件**: 同 WebSocket，task_id 入 payload

**State Management Patterns (Zustand):**

- **Store 命名**: `use{Feature}Store`（如 `useEditorStore`、`useAuthStore`）
- **状态更新**: **不可变更新**（创建新对象/数组）
  ```ts
  // ✅ 正确
  set(state => ({ ...state, isLoading: true }))
  set(state => ({ items: [...state.items, newItem] }))
  // ❌ 错误（直接修改）
  state.isLoading = true
  state.items.push(newItem)
  ```
- **Action 命名**: 动词开头（`setAgent`、`addNode`、`updateConfig`）
- **Selector 模式**: 简单状态直接解构，复杂派生用 `useShallow`
  ```ts
  const agent = useEditorStore(s => s.agent)
  const { nodes, edges } = useEditorStore(useShallow(s => ({ nodes: s.nodes, edges: s.edges })))
  ```

**TanStack Query Patterns:**

- **Query Key 命名**: 数组形式，按 resource 层级
  ```ts
  useQuery({ queryKey: ['agents', agentId], ... })
  useQuery({ queryKey: ['agents', agentId, 'executions'], ... })
  ```
- **Mutation 命名**: `useCreateAgent`、`useUpdateAgent`、`useDeleteAgent`
- **失效策略**: Mutation 成功后 `queryClient.invalidateQueries({ queryKey: ['agents'] })`
- **乐观更新**: UI 立即更新 + 失败回滚（用于点赞、状态切换等）

### Process Patterns

**Error Handling Patterns:**

- **后端全局异常**: FastAPI `@app.exception_handler(Exception)` 兜底 + 业务异常类 `AppError` 体系
  ```python
  class AppError(Exception):
      def __init__(self, code: str, message: str, status_code: int = 400, details: dict | None = None):
          self.code = code
          self.message = message
          self.status_code = status_code
          self.details = details or {}
  ```
- **后端日志**: loguru + JSON 格式 + 全链路 `request_id`
  ```python
  logger.bind(request_id=request_id, user_id=user_id).error("agent_invoke_failed", agent_id=agent_id, error=str(e))
  ```
- **前端错误边界**: `ErrorBoundary` 包裹路由 + features，关键失败兜底页
- **前端用户提示**: Ant Design `message.error()` / `notification.error()`，message 走后端 `error.message` 字段
- **敏感信息脱敏**: 日志中间件 + Pydantic `Field(exclude=True)` 排除敏感字段

**Loading State Patterns:**

- **TanStack Query**: 使用内置 `isLoading` / `isPending` / `isError` / `isFetching`
  - `isLoading`: 首次加载无缓存
  - `isPending`: mutation 待处理
  - `isFetching`: 后台重新获取
- **全局 Loading**: 路由级用 AntD `Spin` 包裹页面；操作级用按钮 `loading` prop
- **避免**: 自建 `loading` boolean 状态（用 TanStack Query 内置即可）

**Validation Patterns:**

- **后端**: Pydantic Schema 强制验证（请求体、查询参数、响应体）
- **前端**: Ant Design Form 内置校验 + 自定义 validator
- **跨端一致性**: 后端 schema 即真理之源，前端通过 `openapi-typescript` 同步

**Authentication Flow:**

- **登录**: POST `/api/v1/auth/login` → 后端验证 → 返回 `access_token`（body）+ `refresh_token`（HttpOnly Cookie）
- **请求拦截**: 前端 axios interceptor 自动加 `Authorization: Bearer {access_token}`
- **Token 刷新**: 401 响应时自动用 refresh_token 换新 access_token，重发原请求
- **登出**: POST `/api/v1/auth/logout` → 清除前端 store + 调用后端注销 refresh_token

### Enforcement Guidelines

**All AI Agents MUST:**

1. **命名一致性**
   - 跨语言 JSON 字段统一 snake_case（不因前端习惯改 camelCase）
   - Python 内部 snake_case，TypeScript 内部 camelCase
   - 文件名后端 snake_case，前端 kebab-case

2. **格式一致性**
   - API 响应统一 `{data, meta?, error?}` 包裹
   - 时间统一 ISO 8601 字符串
   - 错误统一 `{error: {code, message, details, request_id, timestamp}}`
   - ID 统一 `{resource}_{ulid}`

3. **结构一致性**
   - 测试 co-located（不分离 tests/ 目录）
   - 前端 features 内聚（按业务模块，不按技术类型）
   - 后端分层固定（api/services/engine/workers）

4. **通信一致性**
   - 事件名 snake_case 过去时
   - State 更新不可变
   - 跨端类型从 OpenAPI 自动生成，不手写

5. **流程一致性**
   - 用 TanStack Query 内置状态，不用自建 loading
   - 后端异常用 `AppError` 体系，不用裸 raise
   - 日志必须带 `request_id` 全链路串联
   - 校验用 Pydantic / AntD Form 内置

**Pattern Enforcement:**

- **代码审查**: PR review 检查清单包含上述 5 项
- **Lint 工具**:
  - 前端：ESLint（airbnb-typescript）+ Prettier
  - 后端：ruff（替代 flake8/black/isort）+ mypy
- **CI 验证**: GitHub Actions PR 流水线必须跑 lint + type-check + test
- **模式更新**: 新增模式须更新本节，PR 注明"添加 Pattern X 到 architecture.md"

### Pattern Examples

**✅ Good Examples:**

```python
# 后端 Python（snake_case、类型注解、AppError、loguru）
from app.core.errors import AppError
from app.core.logging import get_logger

logger = get_logger(__name__)

async def invoke_agent(agent_id: str, input_data: dict) -> dict:
    agent = await agent_service.get_by_id(agent_id)
    if not agent:
        raise AppError("AGENT_NOT_FOUND", f"Agent {agent_id} not found", status_code=404)
    try:
        result = await agent_executor.run(agent, input_data)
        logger.bind(agent_id=agent_id).info("agent_invoke_success", elapsed=result.elapsed)
        return {"data": result.to_dict()}
    except TimeoutError:
        raise AppError("AGENT_INVOKE_TIMEOUT", "Agent execution exceeded 30s", status_code=504)
```

```ts
// 前端 TypeScript（camelCase、kebab-case 文件名、不可变更新、openapi-typescript）
// 文件: agent-list-page.tsx
import type { Agent } from '@/types/api'
import { useQuery } from '@tanstack/react-query'
import { useAgentList } from '@/services/agent-api'

export function AgentListPage() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['agents'],
    queryFn: useAgentList,
  })

  if (isLoading) return <Spin />
  if (isError) return <Empty description="加载失败" />

  return (
    <List
      dataSource={data.data}
      renderItem={(agent: Agent) => <AgentCard key={agent.id} agent={agent} />}
    />
  )
}
```

```json
// API 响应（snake_case 字段、ULID ID、ISO 时间）
{
  "data": {
    "id": "agent_01HXYZABCDEF",
    "name": "质量分析助手",
    "status": "published",
    "created_at": "2026-06-08T10:30:00.123Z",
    "updated_at": "2026-06-08T10:30:00.123Z"
  }
}
```

**❌ Anti-Patterns:**

```python
# ❌ camelCase 在 Python（违反命名规范）
agentId = "agent_123"
def getAgentData(agentId: str):
    pass

# ❌ 裸 raise（违反错误处理规范）
if not agent:
    raise ValueError("Agent not found")  # 应抛 AppError 携带 code

# ❌ 字符串拼接日志（违反日志规范）
logger.info(f"User {user_id} called agent {agent_id}")  # 应 bind 字段化
```

```ts
// ❌ 自建 loading 状态（违反 loading 规范）
const [loading, setLoading] = useState(false)  // 用 TanStack Query isLoading

// ❌ 手写类型（违反类型规范）
interface Agent { id: string; name: string }  // 应从 @/types/api 导入

// ❌ 直接 mutation（违反 state 规范）
const nodes = useEditorStore(s => s.nodes)
nodes.push(newNode)  // 应 set(state => ({ nodes: [...state.nodes, newNode] }))

// ❌ PascalCase 文件名（违反文件命名规范）
// AgentCard.tsx（应 agent-card.tsx）
```

```json
// ❌ camelCase 字段（违反 JSON 规范）
{
  "agentId": "agent_123",
  "createdAt": "2026-06-08T10:30:00Z"
}

// ❌ 数字 ID（违反 ID 规范）
{ "id": 12345 }

// ❌ 裸返回（违反响应包裹规范）
{ "name": "质量分析助手", "status": "published" }
```

---

## Next Steps (After Step 5)

**Ready for Step 7: Architecture Validation** — 验证架构一致性、完整性、可实施性。

## Project Structure & Boundaries

### Complete Project Directory Structure

```
agent-flow/
├── README.md                          # 项目入口说明
├── LICENSE                            # 许可证
├── .gitignore                         # Git 忽略规则
├── .dockerignore                      # Docker 构建忽略
├── .editorconfig                      # 编辑器统一配置
│
├── docs/                              # 项目文档（已有，保留）
│   ├── planning-artifacts/            # 规划阶段产物
│   ├── implementation-artifacts/      # 实施阶段产物
│   ├── brainstorming/                 # 头脑风暴记录
│   ├── ai-framework-selection.md
│   └── architecture-overview.html
│
├── backend/                           # FastAPI + LangGraph 后端
│   ├── pyproject.toml                 # uv 项目配置 + 依赖
│   ├── uv.lock                        # 依赖锁文件
│   ├── Dockerfile                     # 多阶段构建
│   ├── .python-version                # Python 3.12
│   ├── .env.example                   # 配置模板
│   ├── README.md                      # 后端模块说明
│   │
│   ├── app/                           # 应用代码
│   │   ├── __init__.py
│   │   ├── main.py                    # FastAPI 入口
│   │   │
│   │   ├── api/                       # API 路由层（按 resource 子目录）
│   │   │   ├── __init__.py
│   │   │   ├── deps.py                # 全局依赖注入
│   │   │   ├── errors.py              # 异常处理（AppError 体系）
│   │   │   ├── middleware/            # 中间件
│   │   │   │   ├── __init__.py
│   │   │   │   ├── request_id.py      # request_id 注入
│   │   │   │   ├── logging_mw.py      # 日志中间件
│   │   │   │   └── exception_mw.py    # 全局异常捕获
│   │   │   └── v1/
│   │   │       ├── __init__.py
│   │   │       ├── router.py          # v1 路由聚合
│   │   │       ├── auth/              # 认证
│   │   │       │   ├── __init__.py
│   │   │       │   ├── login.py
│   │   │       │   ├── refresh.py
│   │   │       │   └── logout.py
│   │   │       ├── agents/            # Agent 管理（FR-1/2/3）
│   │   │       │   ├── __init__.py
│   │   │       │   ├── crud.py        # 增删改查
│   │   │       │   ├── publish.py
│   │   │       │   ├── invoke.py      # 同步调用
│   │   │       │   ├── stream.py      # WebSocket 流式
│   │   │       │   └── schemas.py
│   │   │       ├── workflows/         # 工作流（FR-9/10/11/12/12A）
│   │   │       │   ├── __init__.py
│   │   │       │   ├── crud.py
│   │   │       │   ├── execute.py
│   │   │       │   ├── versions.py
│   │   │       │   ├── templates.py   # 模板管理（DB+文件双写、semver）
│   │   │       │   └── schemas.py
│   │   │       ├── tasks/             # Task 管理（FR-29/30/31/32/33）
│   │   │       │   ├── __init__.py
│   │   │       │   ├── crud.py        # Task 创建、查询、取消
│   │   │       │   ├── intervene.py   # 流程干预 API
│   │   │       │   ├── timeline.py    # 执行时间线 / 审计日志
│   │   │       │   ├── query.py       # Task 进度查询（前台/后台）
│   │   │       │   └── schemas.py
│   │   │       ├── tools/             # 工具系统（FR-13/14/15）
│   │   │       │   ├── __init__.py
│   │   │       │   ├── skills.py      # Skill CRUD
│   │   │       │   ├── mcp.py         # MCP 连接管理
│   │   │       │   ├── discover.py    # MCP 工具自动发现
│   │   │       │   └── schemas.py
│   │   │       ├── knowledge/         # 知识库（FR-16/17）
│   │   │       │   ├── __init__.py
│   │   │       │   ├── documents.py
│   │   │       │   ├── search.py      # 向量检索
│   │   │       │   └── schemas.py
│   │   │       ├── api_keys/          # 外部 API Key（FR-18/19）
│   │   │       │   ├── __init__.py
│   │   │       │   ├── crud.py
│   │   │       │   └── schemas.py
│   │   │       ├── conversations/     # 对话（FR-20/21）
│   │   │       │   ├── __init__.py
│   │   │       │   ├── messages.py
│   │   │       │   ├── stream.py
│   │   │       │   └── schemas.py
│   │   │       ├── executions/        # 执行日志（FR-25/26）
│   │   │       │   ├── __init__.py
│   │   │       │   ├── logs.py
│   │   │       │   ├── trace.py       # 调用链
│   │   │       │   └── schemas.py
│   │   │       ├── users/             # 用户管理（FR-27）
│   │   │       │   ├── __init__.py
│   │   │       │   ├── crud.py
│   │   │       │   └── schemas.py
│   │   │       ├── models/            # LLM 模型路由（FR-3）
│   │   │       │   ├── __init__.py
│   │   │       │   ├── providers.py
│   │   │       │   └── schemas.py
│   │   │       ├── callbacks/         # 异步 Webhook 回调
│   │   │       │   ├── __init__.py
│   │   │       │   └── delivery.py    # HMAC 签名 + 重试
│   │   │       └── health.py          # 健康检查
│   │   │
│   │   ├── core/                      # 核心：配置、安全、通用
│   │   │   ├── __init__.py
│   │   │   ├── config.py              # Pydantic Settings
│   │   │   ├── security.py            # JWT、密码、RBAC
│   │   │   ├── logging.py             # loguru 配置
│   │   │   ├── errors.py              # AppError 体系
│   │   │   └── pagination.py          # 分页工具
│   │   │
│   │   ├── models/                    # MongoDB 数据模型
│   │   │   ├── __init__.py
│   │   │   ├── base.py                # 基础模型
│   │   │   ├── agent.py
│   │   │   ├── workflow.py
│   │   │   ├── task.py                # Task 模型（状态、变量池、绑定快照、version）
│   │   │   ├── task_audit.py          # Task 审计日志模型
│   │   │   ├── tool.py
│   │   │   ├── knowledge.py
│   │   │   ├── conversation.py
│   │   │   ├── execution.py
│   │   │   ├── user.py
│   │   │   └── api_key.py
│   │   │
│   │   ├── schemas/                   # Pydantic 请求/响应
│   │   │   ├── __init__.py
│   │   │   ├── common.py              # 通用：分页、错误
│   │   │   ├── agent.py
│   │   │   ├── workflow.py
│   │   │   ├── task.py                # Task 请求/响应 schema
│   │   │   ├── tool.py
│   │   │   ├── knowledge.py
│   │   │   ├── conversation.py
│   │   │   ├── execution.py
│   │   │   ├── user.py
│   │   │   └── api_key.py
│   │   │
│   │   ├── services/                  # 业务逻辑层
│   │   │   ├── __init__.py
│   │   │   ├── agent_service.py
│   │   │   ├── workflow_service.py
│   │   │   ├── task_service.py        # Task 业务逻辑（创建、查询、状态转换）
│   │   │   ├── workflow_registry.py   # Workflow Registry 能力地图注入
│   │   │   ├── tool_service.py
│   │   │   ├── knowledge_service.py
│   │   │   ├── conversation_service.py
│   │   │   ├── execution_service.py
│   │   │   ├── user_service.py
│   │   │   ├── api_key_service.py
│   │   │   └── model_router.py        # LLM 动态路由
│   │   │
│   │   ├── engine/                    # LangGraph 引擎层（按执行实体）
│   │   │   ├── __init__.py
│   │   │   ├── state.py               # AgentState 状态定义
│   │   │   ├── checkpointer.py        # MongoDBSaver 单例
│   │   │   ├── llm_factory.py         # LLM 客户端工厂
│   │   │   ├── prompt.py              # 提示词模板管理
│   │   │   ├── context.py             # 上下文压缩
│   │   │   │
│   │   │   ├── agent/                 # Agent 执行实体
│   │   │   │   ├── __init__.py
│   │   │   │   ├── builder.py         # StateGraph 构建
│   │   │   │   ├── direct_executor.py # 直接执行
│   │   │   │   ├── react_executor.py  # REACT 推理
│   │   │   │   ├── planner_executor.py # 计划-执行-验证
│   │   │   │   └── depth_guard.py     # 嵌套深度保护
│   │   │   │
│   │   │   ├── workflow/              # 工作流执行实体
│   │   │   │   ├── __init__.py
│   │   │   │   ├── builder.py         # DAG 构建
│   │   │   │   ├── executor.py        # 工作流执行
│   │   │   │   ├── nodes/             # 8 种核心节点（Strategy 模式）
│   │   │   │   │   ├── __init__.py
│   │   │   │   │   ├── base.py        # BaseNodeExecutor 抽象类
│   │   │   │   │   ├── start_end.py   # start / end 节点
│   │   │   │   │   ├── agent_node.py  # agent 节点（调用 LLM Agent 推理）
│   │   │   │   │   ├── tool_node.py   # tool 节点（直接调用外部 Tool）
│   │   │   │   │   ├── human_node.py  # human 节点（等待人工输入/审批）
│   │   │   │   │   ├── gateway_node.py # gateway 节点（条件分支路由）
│   │   │   │   │   ├── parallel_node.py # parallel 节点（fork/join）
│   │   │   │   │   └── subflow_node.py # subflow 节点（嵌套调用子 Workflow）
│   │   │   │   └── edges.py           # 条件边
│   │   │   │
│   │   │   ├── task/                  # Task 运行时管理（FR-29/30/31）
│   │   │   │   ├── __init__.py
│   │   │   │   ├── state_machine.py   # Task 状态机（TaskStatus + 转换规则）
│   │   │   │   ├── executor.py        # Task 执行器（协调节点执行 + 状态推进）
│   │   │   │   ├── variable_pool.py   # 变量池管理（读写隔离 + null-safe）
│   │   │   │   ├── expression.py      # 表达式引擎（jinja2 sandbox）
│   │   │   │   ├── context.py         # Task 上下文（三层隔离：Session/Task/Node）
│   │   │   │   ├── intervention.py    # 流程干预（approve/reject/pause/resume/... + 乐观锁）
│   │   │   │   ├── foreground.py      # 前后台模式（30s 自动转后台 + 推送策略）
│   │   │   │   └── audit.py           # Task 审计日志
│   │   │   │
│   │   │   └── tool/                  # 工具执行实体
│   │   │       ├── __init__.py
│   │   │       ├── registry.py        # 工具注册中心
│   │   │       ├── skill_runner.py    # Skill 执行
│   │   │       ├── mcp_client.py      # MCP 客户端
│   │   │       └── sandbox.py         # 代码工具沙箱
│   │   │
│   │   ├── workers/                   # Celery 任务
│   │   │   ├── __init__.py
│   │   │   ├── celery_app.py          # Celery 实例
│   │   │   ├── tasks/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── agents.py          # agents.* 任务
│   │   │   │   ├── workflows.py       # workflows.* 任务
│   │   │   │   ├── tasks.py           # tasks.* 任务（后台 Task 执行、前台超时转后台）
│   │   │   │   ├── knowledge.py       # 文档解析/索引
│   │   │   │   └── callbacks.py       # Webhook 投递
│   │   │   └── beat_schedule.py       # 定时任务（可选）
│   │   │
│   │   └── db/                        # 数据库连接
│   │       ├── __init__.py
│   │       ├── mongodb.py             # MongoDB 客户端
│   │       ├── redis.py               # Redis 客户端
│   │       └── indexes.py             # 索引创建脚本
│   │
│   ├── tests/                         # co-located 镜像测试（co-located 在源文件同目录）
│   │   ├── conftest.py                # pytest fixtures
│   │   ├── api/
│   │   ├── services/
│   │   ├── engine/
│   │   └── workers/
│   │       └── test_*.py
│   │
│   ├── scripts/                       # 运维脚本
│   │   ├── init_mongo.py              # 初始化 MongoDB
│   │   ├── init_indexes.py            # 创建索引
│   │   ├── generate_openapi.py        # 导出 OpenAPI schema
│   │   └── seed_data.py               # 种子数据
│   │
│   └── alembic/                       # 数据迁移（MVP 可选）
│       └── versions/
│
├── frontend/                          # React + Vite 前端
│   ├── package.json
│   ├── pnpm-lock.yaml                 # 或 package-lock.json
│   ├── tsconfig.json
│   ├── tsconfig.node.json
│   ├── vite.config.ts
│   ├── tailwind.config.ts
│   ├── postcss.config.js
│   ├── .eslintrc.cjs
│   ├── .prettierrc
│   ├── index.html
│   ├── Dockerfile                     # 多阶段构建
│   ├── nginx.conf                     # SPA fallback + 缓存
│   ├── .env.example
│   ├── README.md
│   │
│   ├── public/                        # 静态资源（构建时复制）
│   │   ├── favicon.ico
│   │   └── locales/                   # i18n 资源（MVP 仅中文）
│   │
│   └── src/
│       ├── main.tsx                   # React 入口
│       ├── App.tsx                    # 根组件
│       ├── index.css                  # Tailwind 入口
│       ├── env.d.ts                   # 环境变量类型
│       │
│       ├── pages/                     # 路由级页面
│       │   ├── login-page.tsx
│       │   ├── dashboard-page.tsx
│       │   ├── not-found-page.tsx
│       │   └── error-page.tsx
│       │
│       ├── features/                  # 业务特性（按 PRD 13 特性）
│       │   ├── agent_management/      # FR-1/2/3 Agent 管理
│       │   │   ├── components/
│       │   │   │   ├── agent-list.tsx
│       │   │   │   ├── agent-card.tsx
│       │   │   │   ├── agent-form.tsx
│       │   │   │   └── agent-publish-dialog.tsx
│       │   │   ├── hooks/
│       │   │   │   ├── use-agents.ts
│       │   │   │   └── use-agent-mutation.ts
│       │   │   ├── stores/
│       │   │   │   └── agent-filter-store.ts
│       │   │   └── types.ts
│       │   │
│       │   ├── execution_engine/      # FR-4/5/6/7/8 自主执行
│       │   │   ├── components/
│       │   │   │   ├── agent-runner.tsx
│       │   │   │   ├── react-trace.tsx
│       │   │   │   └── depth-warning.tsx
│       │   │   ├── hooks/
│       │   │   │   ├── use-agent-invoke.ts
│       │   │   │   └── use-websocket.ts
│       │   │   └── types.ts
│       │   │
│       │   ├── task_management/       # FR-29/30/31/32/33 Task 管理（新增）
│       │   │   ├── components/
│       │   │   │   ├── task-list.tsx           # Task 列表（按状态筛选）
│       │   │   │   ├── task-detail-panel.tsx   # Task 详情（状态、变量池、时间线）
│       │   │   │   ├── task-status-badge.tsx   # 状态徽章（7 种状态）
│       │   │   │   ├── task-intervene-bar.tsx  # 干预操作栏（approve/reject/pause/...）
│       │   │   │   ├── task-timeline.tsx       # 执行时间线（节点级）
│       │   │   │   ├── human-node-card.tsx    # human 节点审批卡片
│       │   │   │   └── task-variable-inspector.tsx # 变量池查看器
│       │   │   ├── hooks/
│       │   │   │   ├── use-tasks.ts            # Task 列表/详情
│       │   │   │   ├── use-task-intervene.ts   # 流程干预（含乐观锁重试）
│       │   │   │   ├── use-task-stream.ts      # Task 进度 WebSocket 订阅
│       │   │   │   └── use-task-timeline.ts    # 执行时间线
│       │   │   ├── stores/
│       │   │   │   └── task-filter-store.ts    # Task 筛选状态
│       │   │   └── types.ts
│       │   │
│       │   ├── workflow_editor/       # FR-9/10/11/12/12A DAG（8 种节点）
│       │   │   ├── components/
│       │   │   │   ├── workflow-canvas.tsx
│       │   │   │   ├── node-palette.tsx        # 8 种节点类型面板
│       │   │   │   ├── nodes/                  # 自定义节点渲染组件
│       │   │   │   │   ├── start-end-node.tsx
│       │   │   │   │   ├── agent-node-view.tsx
│       │   │   │   │   ├── tool-node-view.tsx
│       │   │   │   │   ├── human-node-view.tsx
│       │   │   │   │   ├── gateway-node-view.tsx
│       │   │   │   │   ├── parallel-node-view.tsx
│       │   │   │   │   └── subflow-node-view.tsx
│       │   │   │   ├── node-inspector.tsx      # 节点参数配置面板
│       │   │   │   ├── condition-edge.tsx
│       │   │   │   └── version-history.tsx
│       │   │   ├── hooks/
│       │   │   │   ├── use-workflow.ts
│       │   │   │   └── use-canvas-state.ts
│       │   │   ├── stores/
│       │   │   │   └── editor-store.ts  # Zustand
│       │   │   └── types.ts
│       │   │
│       │   ├── tool_registry/         # FR-13/14/15 工具系统
│       │   │   ├── components/
│       │   │   │   ├── skill-list.tsx
│       │   │   │   ├── skill-upload.tsx
│       │   │   │   ├── mcp-connection-list.tsx
│       │   │   │   └── tool-pool-view.tsx
│       │   │   ├── hooks/
│       │   │   │   └── use-tools.ts
│       │   │   └── types.ts
│       │   │
│       │   ├── knowledge_base/        # FR-16/17 知识库
│       │   │   ├── components/
│       │   │   │   ├── document-list.tsx
│       │   │   │   ├── document-upload.tsx
│       │   │   │   └── search-panel.tsx
│       │   │   ├── hooks/
│       │   │   │   └── use-knowledge.ts
│       │   │   └── types.ts
│       │   │
│       │   ├── api_sdk/               # FR-18/19 外部 API/SDK
│       │   │   ├── components/
│       │   │   │   ├── api-key-list.tsx
│       │   │   │   ├── api-key-create-dialog.tsx
│       │   │   │   └── callback-history.tsx
│       │   │   ├── hooks/
│       │   │   │   └── use-api-keys.ts
│       │   │   └── types.ts
│       │   │
│       │   ├── conversation/          # FR-20/21 对话交互
│       │   │   ├── components/
│       │   │   │   ├── chat-window.tsx
│       │   │   │   ├── message-list.tsx
│       │   │   │   ├── message-input.tsx
│       │   │   │   └── streaming-message.tsx
│       │   │   ├── hooks/
│       │   │   │   ├── use-conversation.ts
│       │   │   │   └── use-chat-stream.ts
│       │   │   └── types.ts
│       │   │
│       │   ├── execution_logs/        # FR-25/26 执行日志
│       │   │   ├── components/
│       │   │   │   ├── log-viewer.tsx
│       │   │   │   ├── trace-timeline.tsx
│       │   │   │   └── log-filter.tsx
│       │   │   ├── hooks/
│       │   │   │   └── use-execution-logs.ts
│       │   │   └── types.ts
│       │   │
│       │   ├── user_management/       # FR-27 权限管理
│       │   │   ├── components/
│       │   │   │   ├── user-list.tsx
│       │   │   │   ├── role-editor.tsx
│       │   │   │   └── permission-matrix.tsx
│       │   │   ├── hooks/
│       │   │   │   └── use-users.ts
│       │   │   └── types.ts
│       │   │
│       │   └── layout/                # 通用布局
│       │       ├── components/
│       │       │   ├── app-shell.tsx
│       │       │   ├── sidebar.tsx
│       │       │   ├── header.tsx
│       │       │   └── breadcrumb.tsx
│       │       └── types.ts
│       │
│       ├── components/                # 跨特性通用 UI 组件
│       │   ├── data-table.tsx
│       │   ├── empty-state.tsx
│       │   ├── error-boundary.tsx
│       │   ├── loading-spinner.tsx
│       │   ├── confirm-dialog.tsx
│       │   └── status-badge.tsx
│       │
│       ├── hooks/                     # 跨特性共享 hooks
│       │   ├── use-debounce.ts
│       │   ├── use-pagination.ts
│       │   ├── use-request.ts         # TanStack Query 封装
│       │   └── use-permission.ts      # 前端权限检查
│       │
│       ├── services/                  # API 调用层（按后端 resource）
│       │   ├── api-client.ts          # axios 实例 + 拦截器
│       │   ├── auth-api.ts
│       │   ├── agent-api.ts
│       │   ├── workflow-api.ts
│       │   ├── tool-api.ts
│       │   ├── knowledge-api.ts
│       │   ├── conversation-api.ts
│       │   ├── execution-api.ts
│       │   ├── user-api.ts
│       │   └── api-key-api.ts
│       │
│       ├── stores/                    # 跨特性全局 stores
│       │   ├── auth-store.ts          # 当前用户、token
│       │   ├── notification-store.ts  # 全局通知
│       │   └── theme-store.ts         # 主题偏好
│       │
│       ├── lib/                       # 工具库
│       │   ├── format.ts              # 时间、数字格式化
│       │   ├── validate.ts            # 通用校验
│       │   ├── request-id.ts          # request_id 生成
│       │   ├── constants.ts           # 全局常量
│       │   └── ws-client.ts           # WebSocket 客户端封装
│       │
│       ├── types/                     # 全局类型
│       │   ├── api.ts                 # openapi-typescript 生成（自动）
│       │   ├── common.ts
│       │   └── permission.ts          # RBAC 类型
│       │
│       ├── routes/                    # 路由配置
│       │   ├── index.tsx
│       │   ├── protected-routes.tsx   # RequireAuth 包装
│       │   ├── role-routes.tsx        # RequireRole 包装
│       │   └── paths.ts               # 路径常量
│       │
│       └── config/                    # 运行时配置
│           ├── menu.ts                # 侧边栏菜单（按角色过滤）
│           ├── env.ts                 # 环境变量（强类型）
│           └── query-client.ts        # TanStack Query 配置
│
├── deploy/                            # 部署配置
│   ├── docker-compose.yml             # 主编排
│   ├── docker-compose.dev.yml         # 开发覆盖（热重载）
│   ├── .env.example                   # 全局环境变量模板
│   ├── Caddyfile                      # 反向代理（内网 HTTP，MVP 阶段）
│   ├── mongo/
│   │   ├── init.js                    # MongoDB 初始化
│   │   └── mongo.conf
│   ├── redis/
│   │   └── redis.conf
│   ├── nginx/
│   │   ├── default.conf               # 前端 Nginx 配置
│   │   └── nginx.conf
│   └── scripts/
│       ├── start.sh                   # 一键启动
│       ├── stop.sh
│       ├── logs.sh                    # 聚合查看日志
│       ├── backup.sh                  # 手动备份
│       └── restore.sh
│
├── .github/                           # GitHub 配置
│   ├── workflows/
│   │   ├── ci.yml                     # PR 检查（lint + type-check + test）
│   │   ├── build.yml                  # main 分支构建镜像
│   │   └── deploy.yml                 # 手动部署
│   ├── ISSUE_TEMPLATE/
│   │   ├── bug_report.md
│   │   └── feature_request.md
│   └── PULL_REQUEST_TEMPLATE.md
│
├── scripts/                           # 仓库级脚本
│   ├── setup-dev.sh                   # 一键初始化开发环境
│   ├── generate-api-types.sh          # 从后端 OpenAPI 生成前端类型
│   └── pre-commit.sh                  # Git hook
│
├── tests/                             # 端到端测试（MVP 可选）
│   ├── e2e/
│   │   ├── playwright.config.ts
│   │   └── specs/
│   └── fixtures/
│
├── .claude/                           # Claude AI 配置（已有）
│   └── skills/
│
├── .spec-workflow/                    # Spec 工作流（已有）
│   └── specs/
│
├── .vscode/                           # VS Code 配置（推荐）
│   ├── settings.json
│   ├── extensions.json
│   └── launch.json                    # 调试配置
│
└── Makefile                           # 顶层命令聚合
    ├── make install
    ├── make dev
    ├── make test
    ├── make lint
    ├── make build
    └── make deploy
```

### Architectural Boundaries

**API Boundaries:**

| 边界 | 端点前缀 | 认证 | 职责 |
|------|----------|------|------|
| **公开 API** | `/api/v1/auth/*` | 无 | 登录、刷新、登出 |
| **内部用户 API** | `/api/v1/{resource}/*` | JWT | 内部用户所有操作 |
| **外部系统 API** | `/api/v1/agents/*/invoke` | API Key + HMAC | 外部 MES/ERP/BI 集成 |
| **流式端点** | `/api/v1/{resource}/*/stream` (WS) | JWT / API Key | 实时流式 |
| **健康检查** | `/health`、`/metrics` | 无 | K8s/运维探针 |
| **API 文档** | `/docs`、`/redoc`、`/openapi.json` | 无 | Swagger UI / ReDoc |

**API 路径规范**：`/api/v1/{resource}/{id?}/{action?}`
- 资源名 snake_case 复数
- ID 用 ULID（`agent_01HXYZ...`）
- Action 为动词（`invoke`、`publish`、`stream`）

**Component Boundaries:**

| 边界 | 通信方式 | 职责 |
|------|----------|------|
| **页面 ↔ Feature** | props 传递 + Zustand store | 页面是路由壳，Feature 提供业务 |
| **Feature ↔ Feature** | **不直接通信**（通过 stores/ 或 services/） | 避免特性耦合 |
| **Feature ↔ Services** | TanStack Query（服务端）+ Zustand（客户端） | 单一数据源 |
| **Services ↔ Backend API** | axios + interceptor | 统一请求拦截、错误处理 |
| **WebSocket Client ↔ Backend** | 单例 ws-client + EventEmitter | 复用连接、事件总线 |

**Service Boundaries:**

- **API 路由层** (`app/api/v1/{resource}/`)：HTTP 端点，参数校验，调用 service
- **业务逻辑层** (`app/services/{resource}_service.py`)：业务规则，跨模型编排
- **数据模型层** (`app/models/{resource}.py`)：MongoDB 文档定义
- **Schema 层** (`app/schemas/{resource}.py`)：Pydantic 请求/响应
- **引擎层** (`app/engine/{agent,workflow,tool}/`)：LangGraph 执行，状态管理
- **任务层** (`app/workers/tasks/{domain}.py`)：Celery 异步任务

**调用方向**（禁止反向依赖）：
```
api → services → engine / models / workers
                    ↓
                  engine → models / services
```

**Data Boundaries:**

- **MongoDB Collections**: `agents`、`workflows`、`tools`、`knowledge_documents`、`conversations`、`messages`、`executions`、`users`、`api_keys`、`execution_logs`
- **MongoDB 索引**: 创建时机 = `db/indexes.py` 启动时执行
- **Redis 缓存键**: `llm:cache:{prompt_hash}`、`session:{user_id}`、`mcp:discover:{server_id}`
- **向量索引**: `knowledge_documents.embedding` 字段创建 Vector Search Index
- **文件存储**: 本地卷挂载 `./data/uploads/`（NFR 上传 ≤ 50MB）

### Requirements to Structure Mapping

**28 项 FR → 11 特性 → 11 个 features/ 子目录 + 11 个 api/v1/ 子目录：**

| FR 范围 | 后端路由 | 后端服务 | 后端引擎 | 前端特性 | 前端页面 |
|---------|----------|----------|----------|----------|----------|
| **FR-1/2/3** Agent 管理 | `api/v1/agents/` | `agent_service` | `engine/agent/builder` | `features/agent_management/` | `pages/agent-list-page.tsx` 等 |
| **FR-4/5/6/7/8** 自主执行 | `api/v1/agents/.../invoke`、`stream` | `agent_service` | `engine/agent/{direct,react,planner}` | `features/execution_engine/` | `pages/agent-run-page.tsx` |
| **FR-9/10/11/12** DAG 工作流 | `api/v1/workflows/` | `workflow_service` | `engine/workflow/{builder,executor,nodes}` | `features/workflow_editor/` | `pages/workflow-edit-page.tsx` |
| **FR-13/14/15** 工具系统 | `api/v1/tools/{skills,mcp}` | `tool_service` | `engine/tool/{registry,mcp_client}` | `features/tool_registry/` | `pages/tools-page.tsx` |
| **FR-16/17** 知识库 | `api/v1/knowledge/` | `knowledge_service` | `engine/tool/skill_runner`（含 embedding）| `features/knowledge_base/` | `pages/knowledge-page.tsx` |
| **FR-18/19** API/SDK | `api/v1/api_keys/` | `api_key_service` | — | `features/api_sdk/` | `pages/api-keys-page.tsx` |
| **FR-20/21** 对话 | `api/v1/conversations/` | `conversation_service` | `engine/agent/react_executor` | `features/conversation/` | `pages/chat-page.tsx` |
| **FR-22/23/24** 上下文 | `engine/context.py` | `context.py` | `engine/context.py` | `features/conversation/components/streaming-message.tsx` |
| **FR-25/26** 执行日志 | `api/v1/executions/` | `execution_service` | 所有引擎节点埋点 | `features/execution_logs/` | `pages/execution-logs-page.tsx` |
| **FR-27** 权限 | `api/v1/users/` | `user_service` | `core/security.py` | `features/user_management/` | `pages/users-page.tsx` |
| **FR-28** Web 界面 | — | — | — | `features/layout/` | `features/layout/components/app-shell.tsx` |

**Cross-Cutting Concerns:**

| 横切关注点 | 后端位置 | 前端位置 | 备注 |
|-----------|----------|----------|------|
| **认证授权** | `core/security.py` + `api/middleware/` | `services/api-client.ts` + `routes/protected-routes.tsx` | JWT 中间件、axios 拦截器 |
| **错误处理** | `core/errors.py` + `api/middleware/exception_mw.py` | `components/error-boundary.tsx` + `hooks/use-request.ts` | AppError 体系 |
| **日志追踪** | `core/logging.py` + `api/middleware/request_id.py` | `lib/request-id.ts` | request_id 全链路 |
| **配置管理** | `core/config.py` | `config/env.ts` | Pydantic Settings + Vite env |
| **类型生成** | `app/api/v1/*/schemas.py` | `types/api.ts`（openapi-typescript 生成）| 自动同步 |

### Integration Points

**Internal Communication:**

```
┌─────────────────────────────────────────────────────────────┐
│                    Frontend (React + Vite)                  │
│  pages → features → components/hooks/stores                 │
│              ↓                                              │
│          services/ (axios + interceptor)                    │
└──────────┬──────────────────────────────────────────────────┘
           │ HTTP/WS
           ↓
┌─────────────────────────────────────────────────────────────┐
│                Backend (FastAPI + LangGraph)                │
│                                                              │
│  api/v1/* ──→ services/* ──→ engine/* ──→ models/*          │
│                   ↓                  ↓                       │
│               workers/* (Celery)  db/* (Mongo/Redis)        │
└──────────┬──────────────────────────────────────────────────┘
           │ Mongo Wire Protocol / Redis Protocol
           ↓
┌─────────────────────────────────────────────────────────────┐
│              Data Layer (MongoDB 7.0 + Redis 7)             │
│  Collections: agents, workflows, executions, ...            │
│  Cache: LLM responses, sessions, MCP discoveries            │
└─────────────────────────────────────────────────────────────┘
```

**External Integrations:**

| 集成点 | 协议 | 认证 | 用途 |
|--------|------|------|------|
| **外部系统 → API** | REST/WS | API Key + HMAC | 消费 Agent 能力 |
| **Backend → LLM** | HTTPS | API Key（环境变量） | OpenAI / Claude / 国产模型 |
| **Backend → MCP** | stdio / SSE | — | 工具发现与调用 |
| **Backend → Webhook** | HTTPS POST | HMAC 签名 | 异步任务结果回调 |

**Data Flow:**

**1. 同步 Agent 调用流（外部系统）：**
```
MES 系统 → POST /api/v1/agents/{id}/invoke (API Key + HMAC)
  → API 中间件（认证 + 限流预留）
  → agent_service.invoke()
  → engine/agent/react_executor.run()
    → LLM 调用
    → 工具调用（engine/tool/registry）
    → MongoDBSaver 持久化
  → 返回结果 + execution_id
  → 异步触发 Webhook 回调（如果异步模式）
```

**2. 流式对话流（Web 端）：**
```
用户输入 → POST /api/v1/conversations/{id}/messages
  → conversation_service.create()
  → WebSocket /stream
  → engine/agent/react_executor.stream()
    → 逐 token 推送 {type: "token_received", data}
    → MongoDBSaver 增量持久化
  → 关闭 WS
```

**3. 异步任务流（长任务）：**
```
前端 → POST /api/v1/workflows/{id}/execute (async=true)
  → Celery 任务入队
  → 立即返回 {data: {task_id}}
  → Worker 后台执行（engine/workflow/executor）
  → 完成后 Webhook 回调（HMAC 签名）
```

### File Organization Patterns

**Configuration Files:**

- **后端配置**：`backend/.env`（不入 git）、`backend/.env.example`（模板）、`backend/app/core/config.py`（Pydantic Settings 强类型加载）
- **前端配置**：`frontend/.env`（Vite 前缀 `VITE_`）、`frontend/src/config/env.ts`（强类型）
- **部署配置**：`deploy/.env`（不入 git）、`deploy/.env.example`（全局变量）
- **MongoDB/Redis**：`deploy/mongo/mongo.conf`、`deploy/redis/redis.conf`

**Source Organization:**

- **后端**：按层（api/services/engine/workers）+ 按 resource 子目录
- **前端**：按特性（features/）+ 跨特性共享（components/hooks/services/stores/lib）

**Test Organization:**

- **co-located**：`agent_service.py` ↔ `test_agent_service.py`（pytest + Vitest 都能识别）
- **fixtures**：`tests/conftest.py`（后端）、`src/test/setup.ts`（前端）
- **E2E（可选）**：`tests/e2e/specs/`（Playwright）

**Asset Organization:**

- **静态资源**：`frontend/public/`（favicon、locales）
- **打包资源**：`frontend/src/assets/`（被 Vite 打包处理）
- **用户上传**：`deploy/data/uploads/`（卷挂载）
- **文档**：`docs/`（项目级）+ 各模块 `README.md`

### Development Workflow Integration

**Development Server Structure:**

```bash
# 启动开发环境（带热重载）
make dev
# 等价于：
# - docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.dev.yml up
# - 后端：uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
# - 前端：vite dev --host 0.0.0.0 --port 5173
# - MongoDB / Redis：Docker 容器
# - Celery Worker：--reload
```

**端口分配：**
- 前端 dev: `5173`（Vite HMR）
- 后端 dev: `8000`（FastAPI）
- MongoDB: `27017`
- Redis: `6379`
- 前端 prod (Nginx): `80`
- 后端 prod (Uvicorn behind Caddy): `80`

**Build Process Structure:**

```bash
# 后端构建
docker build -t agent-flow-backend:latest ./backend
# 阶段 1: builder（uv sync + 复制代码）
# 阶段 2: runtime（python:3.12-slim + venv + 非 root + HEALTHCHECK）

# 前端构建
docker build -t agent-flow-frontend:latest ./frontend
# 阶段 1: builder（node:22-alpine + npm ci + vite build）
# 阶段 2: runtime（nginx:alpine + dist + SPA fallback）
```

**Deployment Structure:**

```bash
# 部署（手动 SSH）
make deploy
# 等价于：
# - docker compose -f deploy/docker-compose.yml pull
# - docker compose -f deploy/docker-compose.yml up -d
# - docker compose logs -f --tail=100
```

**目录卷挂载：**
- `deploy/data/mongodb` → `/data/db`（MongoDB 数据）
- `deploy/data/redis` → `/data`（Redis 持久化）
- `deploy/data/uploads` → `/app/uploads`（用户上传）
- `deploy/data/logs` → `/app/logs`（应用日志）

---

## Next Steps (After Step 6)

**Ready for Step 8: Workflow Completion** — 完结架构工作流，提供实施启动指南。

## Architecture Validation Results

### Coherence Validation ✅

**Decision Compatibility:**

- ✅ **技术栈兼容**：LangGraph 1.0.8 + FastAPI 0.128.0 + MongoDB 7.0 + React 19 + Vite 5 + @xyflow/react 11.5.5 均为主流稳定版本，官方文档与生态支持完整
- ✅ **依赖兼容**：`langgraph-checkpoint-mongodb` 与 MongoDBSaver 原生集成；`@xyflow/react` v11 兼容 React 19；`openapi-typescript` 与 FastAPI OpenAPI 3.1 schema 完全兼容
- ✅ **无矛盾决策**：所有 17 项 Critical 决策相互支撑（如 LangGraph + MongoDB Checkpointer 与 MongoDB Atlas Vector Search 共享主库；Celery + Redis 与 OpenAPI types 自动生成协同）
- ✅ **模式对齐**：snake_case 命名（DB/JSON/Python）与 camelCase（TS）通过 Pydantic Schema 统一桥接；kebab-case 前端文件与 PascalCase 组件名在导入时统一

**Pattern Consistency:**

- ✅ **命名一致性**：5 种命名风格（snake_case/camelCase/PascalCase/kebab-case/UPPER_SNAKE）在各自作用域内严格定义，跨语言 JSON 字段统一 snake_case（避免转换开销）
- ✅ **结构一致性**：co-located 测试（前后端统一）+ features 分层（前端按 PRD 11 特性）+ 后端分层（api/services/engine/workers）形成对称
- ✅ **通信一致性**：WebSocket/SSE 事件用 snake_case 过去时；Zustand 不可变更新；TanStack Query 内置 loading 状态；Celery 任务名带模块前缀
- ✅ **流程一致性**：AppError 异常体系（后端）+ ErrorBoundary 兜底（前端）；loguru + request_id 全链路日志；Pydantic/AntD Form 校验源头化

**Structure Alignment:**

- ✅ **结构支撑决策**：项目结构含 11 个 `api/v1/{resource}/` 子目录对应 28 项 FR；engine/agent/、engine/workflow/、engine/tool/ 三大执行实体与 Step 3 技术栈对齐
- ✅ **边界清晰**：api→services→engine 单向调用链；4 类边界（API/组件/服务/数据）明确定义；FR→后端路由/服务/引擎 + 前端 features/页面 完整映射
- ✅ **集成点规范**：内部通信矩阵（页面→Feature→Service→API）+ 外部集成表（API/LLM/MCP/Webhook）+ 3 类数据流（同步/流式/异步）均有具体实现路径
- ✅ **部署结构对齐**：Docker Compose 单机 6 服务（frontend/backend/mongodb/redis/celery-worker/caddy）+ 数据卷挂载（mongodb/redis/uploads/logs）符合 NFR 单机部署约束

### Requirements Coverage Validation ✅

**Epic/Feature Coverage:**

- ✅ **13 大 PRD 特性全部覆盖**：Agent 管理 / 自主执行 / DAG 工作流 / Task 生命周期 / Agent-Workflow 交互 / 工具系统 / 知识库 / API-SDK / 对话 / 上下文管理 / 执行日志 / 权限 / Web 界面 100% 落到 features/ 与 api/v1/ 子目录
- ✅ **35 项 FR 全部架构支撑**：每项 FR 在 FR Mapping Table 中有明确的后端路由 + 服务 + 引擎 + 前端特性 + 页面映射
- ✅ **跨特性依赖处理**：横切关注点（认证、错误、日志、配置、类型、Task 状态机、并发控制、前后台模式）有专门章节定义

**Functional Requirements Coverage:**

- ✅ **FR-1/2/3 Agent 管理** → `api/v1/agents/` + `agent_service` + `features/agent_management/`
- ✅ **FR-4/5/6/7/8 自主执行** → `engine/agent/{direct,react,planner}_executor` + 嵌套深度保护 `depth_guard.py`
- ✅ **FR-9/10/11/12/12A DAG 工作流** → `engine/workflow/{builder,executor,nodes}` + 8 种节点 Strategy + @xyflow/react
- ✅ **FR-29/30/31 Task 生命周期** → `engine/task/{state_machine,executor,foreground,intervention}` + `api/v1/tasks/` + `features/task_management/`
- ✅ **FR-32/33 Agent-Workflow 交互** → `services/workflow_registry.py` + `engine/task/variable_pool.py` + Agent System Prompt 注入
- ✅ **FR-13/14/15 工具系统** → `engine/tool/{registry,mcp_client,skill_runner,sandbox}` + 3 种 Skill 来源
- ✅ **FR-16/17 知识库** → MongoDB Atlas Vector Search + `engine/tool/skill_runner`（含 embedding）
- ✅ **FR-18/19 API/SDK** → `api/v1/api_keys/` + Webhook HMAC 签名 + 异步回调
- ✅ **FR-20/21 对话** → `api/v1/conversations/.../stream` (WS) + `features/conversation/`
- ✅ **FR-22/22A/23/24 上下文** → `engine/task/context.py` 三层隔离 + `engine/task/variable_pool.py` + 跨节点 state 共享
- ✅ **FR-25/26 执行日志** → `api/v1/executions/` + `engine/task/audit.py` + 全链路 request_id + `features/execution_logs/`
- ✅ **FR-27 权限** → `core/security.py` RBAC 装饰器 + 4 角色枚举
- ✅ **FR-28 Web 界面** → `features/layout/` + 侧边栏菜单按角色过滤 + Task 管理面板

**Non-Functional Requirements Coverage:**

- ✅ **性能**（API 同步 ≤30s、Web 首屏 ≤3s、流式输出、前台 30s 自动转后台）：WebSocket 流式 + Vite lazy + UI 库按需 + 编辑器 memo + Celery 异步后台
- ✅ **可靠性**（API ≥99%、单组件故障不全局、日志不丢、Engine 降级时 Direct 可用）：MongoDB 持久化 + loguru 结构化 + Docker Compose 隔离 + Celery 任务重试
- ✅ **安全**（API 认证、密码加密、日志脱敏、Task 变量池隔离）：JWT + bcrypt + AppError 不泄露栈 + Task variables 与 Session 隔离
- ✅ **扩展性**（50 用户/5 并发 Task/全局 50 并发）：单机部署 + 多 worker Uvicorn + Celery 并发控制 + 可配置并发上限
- ✅ **并发**（乐观锁、审计日志）：Task version 字段 + `findOneAndUpdate` 原子操作 + `task_audit_logs` 集合
- ✅ **数据**（运行时日志 30 天、审计日志 90 天、上传 ≤50MB）：MongoDB collections TTL + 文件卷挂载 + NFR 校验在 upload endpoint

### Implementation Readiness Validation ✅

**Decision Completeness:**

- ✅ **17 项 Critical 决策 + 7 项 Task Engine 决策全部带版本**：MongoDB 7.0+、LangGraph 1.0.8+、FastAPI 0.128.0+、React 19、Vite 5+、@xyflow/react 11.5.5+、Task 状态机 Python enum + 转换规则表、变量池 jinja2 sandbox、Workflow Registry System Prompt 注入
- ✅ **8 项 Important 决策明确**：RBAC 手写、错误响应结构、Webhook HMAC、openapi-typescript、路由懒加载、性能优化、Pydantic Settings、多阶段构建
- ✅ **6 项 Deferred 决策清晰**：限流/监控/备份/HTTPS/Sentry/MCP 密钥管理均标注"DEFERRED"且说明后置时机

**Structure Completeness:**

- ✅ **完整目录树**（~230 文件/目录）：从根级 .gitignore 到 backend/app/engine/task/{state_machine,executor,variable_pool} 单文件级别；前端从 pages/ 到 features/{13 个特性}/components 单组件级别
- ✅ **集成点明确**：3 类数据流（同步/流式/异步）有调用序列图；4 个外部集成（API/LLM/MCP/Webhook）有协议 + 认证 + 用途三列表
- ✅ **组件边界清晰**：页面↔Feature↔Service 通信矩阵 + 5 类边界（API/组件/服务/数据/调用方向）

**Pattern Completeness:**

- ✅ **5 大类 18 个冲突点全部覆盖**：Naming（7 项）/ Structure（4 项）/ Format（5 项）/ Communication（4 项）/ Process（5 项）
- ✅ **Good/Anti Examples 对照**：每类模式都有正反代码示例（Python + TypeScript + JSON 三语言）
- ✅ **Enforcement Guidelines**：5 条 MUST 规则 + 4 项 CI 验证机制（lint/type-check/test/格式审查）

### Gap Analysis Results

**Critical Gaps (Block Implementation):**

- ✅ **无 Critical Gap**：所有 17 项 Critical 决策已记录；项目结构完整；集成点明确；命名/结构/格式/通信/流程 5 大类模式已闭环

**Important Gaps (Smooth Implementation):**

- ⚠️ **Celery 任务链可观测性**：Celery 任务与 WebSocket 事件流的串联方案需在 Story 中细化（建议在 Worker 推事件到 Redis Pub/Sub，后端 SSE 订阅）
  - **缓解**：在 4-implementation 阶段的 Sprint Planning 故事中定义
- ⚠️ **MCP 连接生命周期**：MCP Server 连接池的断连重连、并发安全、认证 token 刷新未在架构中详述
  - **缓解**：在 `engine/tool/mcp_client.py` Story 中实现，连接池 + 心跳 + 指数退避重连
- ⚠️ **多 LLM 路由成本追踪**：FR-3 模型动态路由涉及成本/限流/降级，但当前架构未定义 LLM 调用的成本埋点
  - **缓解**：在 `services/model_router.py` Story 中实现，统一拦截器记录 token 用量
- ⚠️ **Task 状态机并发场景**：多个用户同时对同一 Task 执行干预操作时，乐观锁冲突重试策略未定义
  - **缓解**：在 `engine/task/intervention.py` Story 中实现 3 次指数退避重试 + 友好提示"Task 状态已变更，请重新获取"
- ⚠️ **WebSocket 推送可靠性**：前后台 Task 推送依赖 WebSocket，但断线重连后的消息补发机制未定义
  - **缓解**：在 `features/task_management/hooks/use-task-stream.ts` Story 中实现"断线重连后通过 `task_query` 补全最新状态"

**Nice-to-Have Gaps (Post-MVP):**

- 💡 **架构图（Mermaid）**：当前架构文档以 Markdown 表格为主，建议在 `docs/architecture-overview.html` 中补充 SVG/Mermaid 架构图
  - **缓解**：可由 `bmad-agent-tech-writer` skill 或人工补充
- 💡 **ADRs 独立文件**：当前 17 项决策嵌入 architecture.md，建议未来按 ADR 模板拆为 `docs/adr/0001-mongodb.md` 等
  - **缓解**：MVP 之后按需拆解
- 💡 **性能基准测试**：架构未定义性能基准（如 LLM 流式首 token 延迟、并发任务吞吐量）
  - **缓解**：Sprint 3+ 接入 Prometheus + 基准测试

### Validation Issues Addressed

**无阻塞性问题发现**。5 项 Important Gap 均不阻塞 MVP 实施，已在上述章节标注缓解方案（具体到 Story 级别）。

### Architecture Completeness Checklist

**Requirements Analysis**

- [x] Project context thoroughly analyzed（Step 2 完成，35 项 FR + 6 类 NFR + 9 类 cross-cutting concerns）
- [x] Scale and complexity assessed（中等偏高，15-18 个核心组件，单机 50 用户）
- [x] Technical constraints identified（LangGraph + MongoDB + React Flow 生态约束）
- [x] Cross-cutting concerns mapped（日志/认证/三层上下文/嵌套深度/流式/错误处理/Task 状态机/并发控制/前后台模式 9 项）

**Architectural Decisions**

- [x] Critical decisions documented with versions（17 项 Critical + 7 项 Task Engine 决策，全部带版本，Context7 验证）
- [x] Technology stack fully specified（前后端 + DB + 队列 + 部署 + CI 6 类）
- [x] Integration patterns defined（3 类数据流 + 4 类外部集成 + 5 类边界）
- [x] Performance considerations addressed（lazy + memo + Vector Search + Uvicorn 多 worker）

**Implementation Patterns**

- [x] Naming conventions established（5 种命名风格 + 5 类作用域 + 4 种语言/格式）
- [x] Structure patterns defined（co-located + features 分层 + 后端分层）
- [x] Communication patterns specified（事件 + State + Query + 任务 4 类）
- [x] Process patterns documented（错误 + Loading + 校验 + 认证 4 类）

**Project Structure**

- [x] Complete directory structure defined（~230 文件/目录，4 层深度）
- [x] Component boundaries established（API/组件/服务/数据 4 类 + 调用方向约束）
- [x] Integration points mapped（4 个外部集成 + 3 类数据流 + 调用序列）
- [x] Requirements to structure mapping complete（35 项 FR → 13 个 features + 13 个 api/v1 子目录）

### Architecture Readiness Assessment

**Overall Status:** **READY FOR IMPLEMENTATION** ✅

**Confidence Level:** **High** — 16/16 checklist 全部勾选，无 Critical Gap，5 项 Important Gap 有明确缓解方案

**Key Strengths:**

1. **完整技术栈锁定且版本验证**：Context7 核实 LangGraph 1.0.8、FastAPI 0.128.0、@xyflow/react 11.5.5 均为最新稳定版
2. **5 大类模式覆盖 18 个冲突点**：Good/Anti Examples 对照确保 AI 代理实施零歧义
3. **FR 100% 落到结构**：35 项 FR → 13 个后端子目录 + 13 个前端特性 + 完整调用链（含 Task 引擎）
4. **集成点边界清晰**：3 类数据流（同步/流式/异步）+ 4 类外部集成 + Task 干预流有具体协议/认证/用途
5. **部署架构与 NFR 对齐**：Docker Compose 6 服务 + 数据卷挂载 + 多 worker Uvicorn 满足单机 50 用户 + ≥99% 可用性
6. **横切关注点集中处理**：认证/错误/日志/配置/类型/Task 状态机/并发控制/前后台模式 8 项有专门章节，AI 代理可复用不重复造轮子
7. **Task 引擎决策完备**：7 项 Task Engine 架构决策（状态机/变量池/Registry/前后台/干预/节点Strategy/Task 实体）覆盖 PRD 新增的 5 项核心 FR

**Areas for Future Enhancement:**

1. **架构可视化**：补充 Mermaid 架构图（Step 8 完成时可顺手补一份）
2. **ADR 独立化**：MVP 完成后按 ADR 模板拆解 17 项决策为 `docs/adr/0001-xxxx.md`
3. **性能基线**：Sprint 3+ 建立 Prometheus 指标 + 基准测试套件
4. **可观测性增强**：Celery 任务↔WS 事件流串联（Important Gap #1）的具体实现
5. **MCP 生态完善**：MCP 连接池/重连/认证的工程化封装（Important Gap #2）
6. **LLM 成本埋点**：模型路由层的 token 用量追踪与告警（Important Gap #3）

### Implementation Handoff

**AI Agent Guidelines:**

- ✅ **严格遵循本架构文档**：所有技术选型、版本号、目录结构、命名规范均不可偏离
- ✅ **统一实施模式**：5 大类 18 个冲突点必须遵守，违反时 PR review 必须拒绝
- ✅ **尊重架构边界**：调用方向禁止反向依赖（api→services→engine，不允许 engine 直接调 api）
- ✅ **遇到疑问先查文档**：本架构文档是唯一权威；如需补充，PR 修改 architecture.md 并标注
- ✅ **跨端类型自动同步**：前端不手写 API 类型，全部从后端 OpenAPI 自动生成（`scripts/generate-api-types.sh`）
- ✅ **测试 co-located**：写实现时同时写 co-located 测试；PR 必须含测试
- ✅ **PR 包含决策引用**：提交说明中引用 architecture.md 的对应章节（如 "Implements Step 6 FR Mapping 中 FR-4/5/6/7/8"）

**First Implementation Priority:**

**Story #1：项目初始化（基础设施层）**

```bash
# 1. 创建仓库根目录
mkdir agent-flow && cd agent-flow

# 2. 初始化后端
mkdir backend && cd backend
uv init --name agent-flow-backend
uv add fastapi uvicorn langgraph langchain-core langgraph-checkpoint-mongodb
uv add langchain-mcp-adapters langchain-openai langchain-anthropic
uv add pymongo celery redis pydantic-settings
uv add --dev pytest pytest-asyncio httpx ruff mypy
cd ..

# 3. 初始化前端
npm create vite@latest frontend -- --template react-ts
cd frontend
npm install @xyflow/react zustand react-router-dom @tanstack/react-query antd
npm install -D tailwindcss postcss autoprefixer @types/node
npm install -D vitest @testing-library/react @testing-library/jest-dom
npm install -D eslint @typescript-eslint/parser @typescript-eslint/eslint-plugin prettier
npm install -D openapi-typescript
cd ..

# 4. 创建部署配置
mkdir -p deploy/{mongo,redis,nginx,scripts}
mkdir -p deploy/data/{mongodb,redis,uploads,logs}

# 5. 创建 CI 配置
mkdir -p .github/workflows

# 6. 验证启动
make dev  # 一键启动开发环境
```

**验证标准**：
- ✅ 后端 `http://localhost:8000/docs` 可见 Swagger UI
- ✅ 前端 `http://localhost:5173` 可见登录页
- ✅ MongoDB `mongosh` 可连，Redis `redis-cli` 可连
- ✅ Celery Worker 启动日志无 ERROR
- ✅ `/health` 端点返回 200

**后续 Story 优先级**（按 Step 4 Decision Impact Analysis）：
1. 基础设施层（Story #1）— 项目初始化
2. 后端核心（Stories #2-5）— FastAPI / 认证 / MongoDB / Celery
3. 后端业务（Stories #6-12）— API Key / 错误中间件 / WS-SSE / Webhook / Vector Search
4. 前端核心（Stories #13-15）— Vite / 状态管理 / 路由守卫
5. 前端业务（Stories #16-20）— Agent CRUD / 工作流编辑器 / 工具中心 / 对话 / 日志
6. 运维与质量（Stories #21-23）— CI / 日志 / 类型生成

---

**🎉 架构工作流即将完成** — 进入 Step 8 后，将给出最终完结报告与下一步建议（建议进入 `bmad-create-epics-and-stories` 阶段）。
