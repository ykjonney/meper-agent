---
baseline_commit: NO_VCS
---

# Story 1.1: 项目脚手架与基础设施

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

**As a** 全栈工程师，
**I want** 初始化 Vite + React 19 前端、FastAPI + LangGraph 后端（使用 uv 管理依赖）、Docker Compose 单机部署、CI/CD 流水线，以及 5 大代码模式基线（命名/分层/错误/日志/ID），
**So that** 所有后续 Epic 都有统一的工程基线和可运行的部署环境，避免后续重构。

## Acceptance Criteria (BDD)

### AC1: Docker Compose 全栈启动

**Given** 项目仓库已克隆且 Docker Desktop 已启动
**When** 在仓库根目录执行 `make dev`（或 `docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.dev.yml up -d`）
**Then** 6 个服务全部进入 healthy 状态：
  - `frontend`（Vite dev server，端口 5173）— HMR 正常工作
  - `backend`（Uvicorn，端口 8000）— `/api/v1/health` 返回 `{"status": "ok"}`
  - `mongodb`（端口 27017）— 可用 `mongosh` 连接
  - `redis`（端口 6379）— 可用 `redis-cli ping` 返回 PONG
  - `celery-worker`— 启动日志无 ERROR
  - `caddy`（反向代理，端口 80）— `http://localhost` 转发前端

**And** 前端 `http://localhost:5173` 可见空白但可编译的 React 应用
**And** OpenAPI 文档 `http://localhost:8000/docs`（Swagger UI）和 `http://localhost:8000/redoc`（ReDoc）均可访问

### AC2: 后端 API 路由规范

**Given** 后端代码库已初始化（`uv sync` 已运行，依赖已锁）
**When** 开发者创建新的 API endpoint
**Then** 路由路径遵循 `/api/v1/{resource}/{id?}/{action?}` 格式（资源名复数 snake_case）
**And** 错误响应统一为 `{"error": {"code", "message", "details", "request_id", "timestamp"}}` 结构
**And** 所有日志携带 `request_id`（通过 loguru 结构化输出到 stdout 和文件）
**And** 健康检查端点 `/api/v1/health` 不需要认证、返回 200

### AC3: 数据库 ID 与字段规范

**Given** 数据库集合新增需求
**When** 创建 MongoDB collection 或 Pydantic model
**Then** ID 字段使用 ULID 格式 `{resource}_{ulid}`（如 `user_01HXYZ...`、`agent_01HXYZ...`）
**And** 字段命名 snake_case（DB / JSON / Python 一致）
**And** 所有实体包含 `created_at`、`updated_at` 时间戳字段（UTC ISO 格式）

### AC4: 前端组件结构规范

**Given** 前端新增组件
**When** 创建 React 组件
**Then** 业务组件位于 `frontend/src/features/{feature}/components/{Component}.tsx`（特性内分层）
**And** 跨特性通用组件位于 `frontend/src/components/`
**And** 文件名 kebab-case（`agent-card.tsx`），TypeScript 标识符 camelCase/PascalCase
**And** `main.tsx` 启动后能正确渲染根组件 `App.tsx`

### AC5: CI/CD 流水线

**Given** 代码提交到 PR 或 main 分支
**When** GitHub Actions CI 触发（`.github/workflows/ci.yml`）
**Then** 依次执行：
  - 后端：`ruff check` + `mypy` + `pytest`
  - 前端：`eslint` + `tsc --noEmit` + `vitest run`
**And** main 分支额外触发镜像构建并推送到 GHCR（`.github/workflows/build.yml`）
**And** 部署步骤（`.github/workflows/deploy.yml`）需要手动 dispatch，不自动部署

### AC6: 配置管理（Pydantic Settings）

**Given** 配置文件已准备（`.env` 由开发者从 `.env.example` 复制，`.env` 不入 git）
**When** 应用启动
**Then** 后端通过 `pydantic-settings` 从 `.env` 读取配置（`backend/app/core/config.py`）
**And** 缺失关键配置（如 `MONGODB_URI`、`JWT_SECRET_KEY`）时启动失败并打印明确错误（带字段名）
**And** 前端通过 `VITE_` 前缀环境变量配置（`frontend/src/config/env.ts` 强类型）

### AC7: 锁文件与依赖管理

**Given** 项目依赖已声明
**When** 执行 `uv sync`（后端）和 `npm install`（前端）
**Then** 后端 `uv.lock` 与前端 `package-lock.json`（或 `pnpm-lock.yaml`）生成并提交到 git
**And** 后端 Python 版本固定为 3.12（`backend/.python-version`）
**And** `pyproject.toml` 和 `package.json` 完整声明生产与开发依赖

### AC8: 后端分层骨架

**Given** 后端代码库
**When** 开发者查看 `backend/app/` 结构
**Then** 存在清晰的 4 层结构：
  - `api/`：路由层（按 resource 子目录，含 `middleware/`、`v1/`、`deps.py`、`errors.py`）
  - `services/`：业务逻辑层（占位文件即可）
  - `engine/`：LangGraph 引擎层（占位 `state.py`、`checkpointer.py`）
  - `workers/`：Celery 任务层（占位 `celery_app.py`）
**And** 依赖方向严格遵循 `api → services → engine/models/workers`，禁止反向依赖

### AC9: 前端分层骨架

**Given** 前端代码库
**When** 开发者查看 `frontend/src/` 结构
**Then** 存在分层结构：
  - `features/{feature}/`：业务特性（11 个，与 PRD 11 FR 对应，目录可空但需存在）
  - `components/`：跨特性通用组件（占位 6 个）
  - `hooks/`、`services/`、`stores/`、`lib/`、`types/`、`routes/`、`config/`
**And** `routes/` 已配置 React Router v7 基础骨架（含 `protected-routes.tsx` 占位）

### AC10: 5 大模式基线（AppError、日志、ID）

**Given** 后端代码库已初始化
**When** 开发者查看 `backend/app/core/`
**Then** 存在以下文件且可导入：
  - `errors.py`：`AppError` 异常基类，含 `code`、`message`、`status_code`、`details` 字段
  - `logging.py`：loguru 配置（JSON 格式 + 文件轮转）
  - `config.py`：Pydantic Settings 基类
  - `security.py`：占位文件（后续 Story 1.3 填充 JWT）
**And** `api/middleware/request_id.py`：每个请求注入 `request_id`（UUID4 短格式）
**And** `api/middleware/logging_mw.py`：日志中间件（记录请求方法、路径、状态码、耗时）
**And** `api/middleware/exception_mw.py`：全局异常捕获，统一转 `AppError` 响应格式
**And** `api/errors.py`：FastAPI exception_handler 注册

### AC11: 前端主题基线

**Given** 前端代码库已初始化
**When** 开发者查看主题配置
**Then** `frontend/tailwind.config.ts` 集成品牌色 token（primary `#1E5EFF`、accent `#00D4FF`、中性色、语义色）
**And** `frontend/src/App.tsx` 包裹 AntD `ConfigProvider` + 主题 token（圆角克制 2-4px）
**And** `frontend/src/index.css` 引入 Tailwind 基础样式

### AC12: Makefile 一键命令

**Given** 仓库根目录
**When** 开发者查看 `Makefile`
**Then** 提供以下命令：
  - `make install`：安装前后端依赖（`cd backend && uv sync` + `cd frontend && npm install`）
  - `make dev`：启动开发环境（docker compose + 热重载）
  - `make test`：运行前后端测试
  - `make lint`：运行前后端 lint
  - `make build`：构建生产镜像
  - `make deploy`：手动部署提示
  - `make generate-api`：从后端 OpenAPI 生成前端类型

---

## Tasks / Subtasks

### 阶段 1：仓库根级脚手架

- [x] **T1** 创建仓库根级文件（AC: #12）
  - [x] T1.1 创建 `README.md`（项目说明、快速启动指引）
  - [x] T1.2 创建 `.gitignore`（Python、Node、IDE、`.env`、`data/`）
  - [x] T1.3 创建 `.dockerignore`
  - [x] T1.4 创建 `.editorconfig`
  - [x] T1.5 创建 `Makefile`（install/dev/test/lint/build/deploy/generate-api 目标）
  - [x] T1.6 创建 `LICENSE`（按项目要求，可暂用占位）

### 阶段 2：后端 uv 项目初始化

- [x] **T2** 后端 uv 项目初始化（AC: #2, #6, #7, #8）
  - [x] T2.1 `cd backend && uv init --name agent-flow-backend`（生成 `pyproject.toml`、`.python-version`）
  - [x] T2.2 锁定 Python 版本为 3.12（`.python-version` 内容为 `3.12`）
  - [x] T2.3 添加运行依赖：`uv add fastapi uvicorn[standard] langgraph langchain-core langgraph-checkpoint-mongodb langchain-mcp-adapters langchain-openai langchain-anthropic pymongo celery redis pydantic-settings loguru python-ulid pyjwt passlib[bcrypt]`
  - [x] T2.4 添加开发依赖：`uv add --dev pytest pytest-asyncio httpx ruff mypy`
  - [x] T2.5 创建 `backend/.env.example`（含所有必需环境变量模板）
  - [x] T2.6 创建 `backend/.env`（本地默认值，不入 git，仅本地）
  - [x] T2.7 创建 `backend/README.md`（后端模块说明）

### 阶段 3：后端分层骨架与 5 大模式基线

- [x] **T3** 创建 `backend/app/` 4 层目录结构（AC: #8）
  - [x] T3.1 创建 `app/__init__.py`、`app/main.py`（FastAPI 入口）
  - [x] T3.2 创建 `app/api/`（`__init__.py`、`deps.py`、`errors.py`、`middleware/__init__.py`、`v1/__init__.py`、`v1/router.py`、`v1/health.py`）
  - [x] T3.3 创建 `app/api/middleware/request_id.py`（每请求注入 UUID 短格式）
  - [x] T3.4 创建 `app/api/middleware/logging_mw.py`（记录方法/路径/状态码/耗时到 loguru）
  - [x] T3.5 创建 `app/api/middleware/exception_mw.py`（全局兜底异常捕获）
  - [x] T3.6 创建 `app/core/`（`__init__.py`、`config.py`、`logging.py`、`errors.py`、`security.py` 占位、`pagination.py` 占位）
  - [x] T3.7 实现 `core/errors.py`：`AppError(Exception)` 基类 + `ERROR_CODES` 常量
  - [x] T3.8 实现 `core/config.py`：`Settings(BaseSettings)`，含 `mongodb_uri`、`redis_url`、`jwt_secret_key`、`jwt_access_expire_minutes=15`、`jwt_refresh_expire_days=7` 等字段；缺失关键字段时 Pydantic 自动报错
  - [x] T3.9 实现 `core/logging.py`：loguru 配置（JSON 序列化 + stdout + 文件轮转 + 按级别过滤）
  - [x] T3.10 创建 `app/models/`（`__init__.py`、`base.py` 含 ULID 基类 + `created_at`/`updated_at` 时间戳）
  - [x] T3.11 创建 `app/schemas/`（`__init__.py`、`common.py` 含分页与统一错误响应模型）
  - [x] T3.12 创建 `app/services/`（`__init__.py`，业务层占位）
  - [x] T3.13 创建 `app/engine/`（`__init__.py`、`state.py`、`checkpointer.py`、`llm_factory.py`、`prompt.py`、`context.py` 占位）
  - [x] T3.14 创建 `app/workers/`（`__init__.py`、`celery_app.py`、`tasks/__init__.py`）
  - [x] T3.15 创建 `app/db/`（`__init__.py`、`mongodb.py`、`redis.py`、`indexes.py`）
  - [x] T3.16 实现 `api/v1/health.py`：返回 `{"status": "ok"}`，无需认证
  - [x] T3.17 实现 `api/v1/router.py`：聚合 v1 子路由（health 优先）
  - [x] T3.18 实现 `api/errors.py`：注册 `AppError` 异常 handler，输出统一响应结构
  - [x] T3.19 在 `main.py` 中：注册中间件、挂载 v1 router、启动日志初始化、加载 Settings
  - [x] T3.20 创建 `backend/Dockerfile`（多阶段：builder 用 uv sync → runtime 用 python:3.12-slim + 非 root 用户 + HEALTHCHECK）
  - [x] T3.21 创建 `backend/scripts/init_mongo.py`、`generate_openapi.py`（导出 OpenAPI JSON）

### 阶段 4：后端测试基线

- [x] **T4** 创建测试基础设施（AC: #2）
  - [x] T4.1 创建 `backend/tests/conftest.py`（pytest fixtures：TestClient、mock MongoDB、mock Redis）
  - [x] T4.2 创建 `tests/api/test_health.py`：验证 `/api/v1/health` 返回 200
  - [x] T4.3 创建 `tests/core/test_errors.py`：验证 AppError 抛出与序列化
  - [x] T4.4 创建 `tests/api/test_request_id.py`：验证响应头含 `X-Request-ID`
  - [x] T4.5 配置 `pyproject.toml` 的 `[tool.pytest]`、`[tool.ruff]`、`[tool.mypy]` 段

### 阶段 5：前端 Vite 项目初始化

- [x] **T5** 前端 Vite 项目初始化（AC: #4, #7, #11）
  - [x] T5.1 `npm create vite@latest frontend -- --template react-ts`
  - [x] T5.2 安装运行依赖：`npm install @xyflow/react@^11.5.5 zustand react-router-dom @tanstack/react-query antd @ant-design/icons axios dayjs`
  - [x] T5.3 安装 Tailwind：`npm install -D tailwindcss@^3 postcss autoprefixer`（注意：v4 不稳定，使用 v3 稳定版）
  - [x] T5.4 安装测试依赖：`npm install -D vitest @testing-library/react @testing-library/jest-dom @testing-library/user-event jsdom`
  - [x] T5.5 安装 lint 依赖：`npm install -D eslint @typescript-eslint/parser @typescript-eslint/eslint-plugin prettier eslint-config-prettier eslint-plugin-react eslint-plugin-react-hooks`
  - [x] T5.6 安装类型生成：`npm install -D openapi-typescript @types/node`
  - [x] T5.7 配置 `tailwind.config.ts`（集成品牌色 token：primary `#1E5EFF`、accent `#00D4FF`、中性色、语义色、圆角 2/4px、阴影层级）
  - [x] T5.8 配置 `postcss.config.js`
  - [x] T5.9 配置 `vite.config.ts`（alias `@` → `src/`，server proxy `/api` → `localhost:8000`）
  - [x] T5.10 配置 `tsconfig.json`（strict mode、`paths` alias）
  - [x] T5.11 配置 `.eslintrc.cjs`（airbnb-typescript 基础上精简，禁用与 AntD 冲突规则）
  - [x] T5.12 配置 `.prettierrc`
  - [x] T5.13 创建 `.env.example`（`VITE_API_BASE_URL=http://localhost:8000` 等）
  - [x] T5.14 创建 `frontend/src/index.css`（Tailwind directives）
  - [x] T5.15 创建 `frontend/src/env.d.ts`（Vite env 类型）
  - [x] T5.16 创建 `frontend/src/main.tsx`（React 入口 + ConfigProvider 包裹）
  - [x] T5.17 创建 `frontend/src/App.tsx`（含 AntD ConfigProvider + 主题 token）

### 阶段 6：前端分层骨架

- [x] **T6** 创建 `frontend/src/` 分层目录（AC: #9）
  - [x] T6.1 创建 `pages/`（`login-page.tsx`、`dashboard-page.tsx`、`not-found-page.tsx`、`error-page.tsx` 占位）
  - [x] T6.2 创建 `features/` 11 个特性目录（`agent_management/`、`execution_engine/`、`workflow_editor/`、`tool_registry/`、`knowledge_base/`、`api_sdk/`、`conversation/`、`execution_logs/`、`user_management/`、`layout/` 各一个 `.gitkeep`）
  - [x] T6.3 创建 `components/` 占位（`data-table.tsx`、`empty-state.tsx`、`error-boundary.tsx`、`loading-spinner.tsx`、`confirm-dialog.tsx`、`status-badge.tsx` 各占位）
  - [x] T6.4 创建 `hooks/`（`use-debounce.ts`、`use-pagination.ts`、`use-request.ts`、`use-permission.ts` 占位）
  - [x] T6.5 创建 `services/`（`api-client.ts` axios 实例 + 拦截器骨架，其他 api 文件占位）
  - [x] T6.6 创建 `stores/`（`auth-store.ts`、`notification-store.ts`、`theme-store.ts` 占位）
  - [x] T6.7 创建 `lib/`（`format.ts`、`validate.ts`、`request-id.ts`、`constants.ts`、`ws-client.ts` 占位）
  - [x] T6.8 创建 `types/`（`api.ts` 占位、`common.ts`、`permission.ts`）
  - [x] T6.9 创建 `routes/`（`index.tsx`、`protected-routes.tsx` 占位、`role-routes.tsx` 占位、`paths.ts`）
  - [x] T6.10 创建 `config/`（`menu.ts`、`env.ts`、`query-client.ts`）

### 阶段 7：前端 Dockerfile 与 Nginx

- [x] **T7** 前端容器化（AC: #1）
  - [x] T7.1 创建 `frontend/Dockerfile`（多阶段：node:22-alpine + vite build → nginx:alpine + dist）
  - [x] T7.2 创建 `frontend/nginx.conf`（SPA fallback：`try_files $uri $uri/ /index.html`）

### 阶段 8：Docker Compose 编排

- [x] **T8** 创建 `deploy/` 配置（AC: #1）
  - [x] T8.1 创建 `deploy/docker-compose.yml`（6 服务：frontend / backend / mongodb / redis / celery-worker / caddy）
  - [x] T8.2 创建 `deploy/docker-compose.dev.yml`（开发覆盖：热重载 + 挂载源码卷）
  - [x] T8.3 创建 `deploy/.env.example`（全局变量：MONGODB_URI、REDIS_URL、JWT_SECRET_KEY 等）
  - [x] T8.4 创建 `deploy/Caddyfile`（反向代理：`localhost` → frontend:80，`localhost/api` → backend:8000）
  - [x] T8.5 创建 `deploy/mongo/init.js`（初始化 MongoDB 用户与库，可选）
  - [x] T8.6 创建 `deploy/mongo/mongo.conf`
  - [x] T8.7 创建 `deploy/redis/redis.conf`（持久化 AOF + 最大内存策略）
  - [x] T8.8 创建 `deploy/data/.gitkeep`（占位数据卷目录：mongodb / redis / uploads / logs）
  - [x] T8.9 创建 `deploy/scripts/start.sh`、`stop.sh`、`logs.sh`、`backup.sh`、`restore.sh`（可执行）

### 阶段 9：CI/CD

- [x] **T9** 创建 GitHub Actions 工作流（AC: #5）
  - [x] T9.1 创建 `.github/workflows/ci.yml`（PR 检查：lint + type-check + test，前后端矩阵）
  - [x] T9.2 创建 `.github/workflows/build.yml`（main 分支构建并推送镜像到 GHCR）
  - [x] T9.3 创建 `.github/workflows/deploy.yml`（手动 dispatch，SSH 部署提示）
  - [x] T9.4 创建 `.github/PULL_REQUEST_TEMPLATE.md`

### 阶段 10：辅助脚本与文档

- [x] **T10** 仓库级脚本与配置（AC: #12）
  - [x] T10.1 创建 `scripts/setup-dev.sh`（一键初始化开发环境）
  - [x] T10.2 创建 `scripts/generate-api-types.sh`（从后端 OpenAPI 生成前端类型）
  - [x] T10.3 创建 `scripts/pre-commit.sh`（本地 lint 提示）
  - [x] T10.4 创建 `.vscode/settings.json`（推荐配置 + Python 解释器指向 uv venv）
  - [x] T10.5 创建 `.vscode/extensions.json`（推荐扩展：Python、ESLint、Prettier、Tailwind）
  - [x] T10.6 创建 `.vscode/launch.json`（FastAPI / Vite 调试配置）

### 阶段 11：验证

- [x] **T11** 端到端验证（AC: #1-#12 全部）
  - [x] T11.1 本地运行 `make install` 验证依赖安装
  - [x] T11.2 本地运行 `make dev` 验证 docker compose 启动 6 服务
  - [x] T11.3 验证 `curl http://localhost:8000/api/v1/health` 返回 `{"status": "ok"}`
  - [x] T11.4 验证 `http://localhost:8000/docs` 显示 Swagger UI
  - [x] T11.5 验证 `http://localhost:5173` 可见 React 应用
  - [x] T11.6 运行 `make test` 验证测试通过
  - [x] T11.7 运行 `make lint` 验证 lint 通过

---

## Dev Notes

### 关键工程约束（必读）

#### 1. 后端 Python 包管理：**必须使用 uv**

> **CRITICAL**: 后端所有 Python 依赖管理、虚拟环境、锁文件、命令执行**只能使用 `uv`**，禁止使用 pip / poetry / pipenv / virtualenv / venv。

- 项目初始化：`uv init --name agent-flow-backend`
- 添加运行依赖：`uv add <pkg>`
- 添加开发依赖：`uv add --dev <pkg>`
- 同步依赖：`uv sync`（自动创建并管理 `.venv`）
- 运行命令：`uv run <cmd>`（如 `uv run uvicorn app.main:app`、`uv run pytest`、`uv run ruff check`）
- 锁文件：`uv.lock`（必须提交到 git）
- 项目配置：`backend/pyproject.toml`
- Python 版本文件：`backend/.python-version`（内容：`3.12`）
- Dockerfile builder 阶段：`uv sync --frozen --no-dev` 安装生产依赖到 `.venv`，runtime 阶段复制 `.venv`

#### 2. 技术栈版本基线

| 技术 | 版本 | 备注 |
|------|------|------|
| Python | 3.12+ | `.python-version` 锁定 |
| FastAPI | 0.128.0+ | async-first |
| Uvicorn | latest stable | 安装 `[standard]` 包含 uvloop |
| LangGraph | 1.0.8+ | StateGraph + MongoDB Checkpointer |
| Pydantic | 2.x（FastAPI 内置） | v2 语法 |
| pydantic-settings | latest | BaseSettings 配置管理 |
| MongoDB | 7.0+ | 单机部署，无副本集 |
| Redis | 7+ | 缓存 + Celery broker |
| Celery | 5.4+ | 异步任务队列 |
| React | 19 | 前端框架 |
| Vite | 5+ | 构建工具 |
| @xyflow/react | 11.5.5+ | 工作流编辑器（React Flow v11 新包名） |
| TypeScript | 5.x | strict mode |
| Tailwind CSS | **3.x** | **不要用 v4（不稳定）** |
| Ant Design | 5.x | UI 组件库 |
| TanStack Query | 5.x | 数据获取 |
| Zustand | 5.x | 状态管理 |
| React Router | 7.x | data routes |

#### 3. 命名规范（AR-18）

**后端（Python）**：
- 变量/函数：snake_case（`agent_id`、`get_agent_by_id`）
- 类：PascalCase（`AgentService`）
- 常量：UPPER_SNAKE（`MAX_CONCURRENT_TASKS`）
- 模块文件：snake_case（`agent_service.py`）
- MongoDB 集合：snake_case 复数（`agents`、`execution_logs`）
- MongoDB 字段：snake_case（`agent_id`、`created_at`）
- 索引：`idx_{collection}_{fields}`（`idx_agents_user_id`）
- API 路径：`/api/v1/{resource}/{id?}/{action?}`（资源复数 snake_case）
- HTTP Headers 自定义：`X-` 前缀 PascalCase（`X-Request-ID`、`X-API-Key`）
- JSON 字段：snake_case（前后端统一，**不**做 camelCase 转换）
- Celery 任务名：snake_case + 模块前缀（`agents.invoke`）

**前端（TypeScript）**：
- 变量/函数：camelCase（`agentId`、`getAgentById`）
- 类型/接口/类：PascalCase（`Agent`、`AgentCard`）
- 枚举：PascalCase + 成员 PascalCase（`enum AgentStatus { Draft, Published }`）
- 文件：kebab-case（`agent-card.tsx`、`use-agent.ts`）
- React 组件：PascalCase（`AgentCard.tsx`）
- 环境变量：UPPER_SNAKE + `VITE_` 前缀（`VITE_API_BASE_URL`）

**ID 格式（AR-22）**：`{resource}_{ulid}` — `agent_01HXYZABCDEF`、`user_01HXYZ...`、`workflow_01HXYZ...`

#### 4. 后端分层架构（AR-20）

```
backend/app/
├── api/                # 路由层（按 resource 子目录）
│   ├── deps.py         # 全局依赖注入
│   ├── errors.py       # 异常 handler 注册
│   ├── middleware/     # 中间件（request_id / logging / exception）
│   └── v1/             # v1 路由聚合
│       ├── router.py
│       ├── health.py
│       └── {resource}/ # 按 PRD 11 特性分目录
├── core/               # 核心：配置、安全、日志、错误、分页
├── models/             # MongoDB 数据模型（Pydantic）
├── schemas/            # 请求/响应 schema
├── services/           # 业务逻辑层
├── engine/             # LangGraph 引擎层（按执行实体）
│   ├── agent/
│   ├── workflow/
│   └── tool/
├── workers/            # Celery 任务
└── db/                 # MongoDB / Redis 连接
```

**依赖方向（禁止反向）**：`api → services → engine / models / workers`

#### 5. AppError 异常体系（AR-21）

```python
# backend/app/core/errors.py
class AppError(Exception):
    """业务异常基类。所有业务错误必须继承此类，禁止裸 raise Exception。"""
    def __init__(
        self,
        code: str,                # 业务错误码，如 "AGENT_NOT_FOUND"
        message: str,             # 用户可见消息
        status_code: int = 400,
        details: dict | None = None,
    ):
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        super().__init__(message)
```

**统一错误响应结构**（AR-23）：
```json
{
  "error": {
    "code": "AGENT_NOT_FOUND",
    "message": "...",
    "details": {},
    "request_id": "abc123",
    "timestamp": "2026-06-08T10:30:00.123Z"
  }
}
```

**业务错误码规范**：`{MODULE}_{ACTION}_{REASON}` — 如 `AGENT_INVOKE_TIMEOUT`、`WORKFLOW_NODE_NOT_FOUND`、`API_KEY_INVALID`

#### 6. 日志与 request_id（AR-5）

- 使用 `loguru`，JSON 格式输出到 stdout + 文件轮转（按天 + 100MB）
- 每个请求通过中间件注入 `request_id`（UUID4 短格式，如 `a1b2c3d4`），写入响应头 `X-Request-ID`
- 日志调用示例：
  ```python
  logger.bind(request_id=request_id, user_id=user_id).info(
      "agent_invoke_started", agent_id=agent_id
  )
  ```
- 敏感字段通过 Pydantic `Field(exclude=True)` 排除（后续 Story 实现，本 Story 仅建骨架）

#### 7. 前端主题（UX-DR2-DR8）

- 品牌色：`color.primary = #1E5EFF`、`color.accent = #00D4FF`（AI 标识）
- 圆角克制：`radius.sm = 2px`、`radius.md = 4px`、节点/Tag 零圆角
- 阴影 1 层为主：`shadow.sm = 0 1px 2px 0 rgba(0,0,0,0.03)`
- 字体：sans（PingFang SC + Microsoft YaHei）+ mono（SF Mono / Menlo）
- 主题 MVP 仅亮色，token 化预留暗色（CSS variables）
- Tailwind config 集成 AntD 主题 token（`tailwind.config.ts`）
- App.tsx 包裹 AntD `ConfigProvider` + 主题 token

完整 token 表见 `docs/planning-artifacts/ux-designs/ux-agent-flow-2026-06-08/DESIGN.md`。

#### 8. Docker Compose 服务定义

```yaml
# deploy/docker-compose.yml 关键结构
services:
  frontend:    # nginx:alpine, 端口 80:80, depends_on backend
  backend:     # 自构建, 端口 8000:8000, depends_on mongodb, redis
  mongodb:     # mongo:7.0, 端口 27017, volume data/mongodb
  redis:       # redis:7-alpine, 端口 6379, volume data/redis
  celery-worker: # 自构建 backend 镜像, command celery -A app.workers worker
  caddy:       # caddy:2-alpine, 端口 80:80, depends_on frontend, backend
```

开发覆盖（`docker-compose.dev.yml`）：
- backend 挂载 `./backend:/app` + `uv run uvicorn --reload`
- frontend 不进容器（用本地 `vite dev`，端口 5173，proxy `/api` → backend）
- mongodb / redis 仍用容器

#### 9. CI 验证规则（AR-3）

PR 必须通过：
- 后端：`uv run ruff check` + `uv run mypy app` + `uv run pytest`
- 前端：`npm run lint` + `npm run type-check` + `npm run test`

main 分支额外触发镜像构建并推送 GHCR。

### Project Structure Notes

- **Monorepo 简单方案**：前后端异语言（Python + TS），不适合 Turborepo/Nx，采用目录分离 + docker-compose 统一编排
- **目录冲突**：`docs/` 已存在（含 planning-artifacts），保留
- **数据卷**：`deploy/data/{mongodb,redis,uploads,logs}` 需在 `.gitignore` 排除，仅保留 `.gitkeep`
- **后端测试目录**：使用 `backend/tests/` co-located 镜像结构，但顶层 `tests/` 仅放 E2E（本 Story 不创建）
- **前端 features 目录**：11 个特性目录与 PRD 11 FR 对应，本 Story 仅创建空目录（`.gitkeep`），具体内容由后续 Story 填充
- **Epic 6（知识库）延后**：`features/knowledge_base/` 目录仍创建（占位），但 Story 不实现

### References

- [Source: docs/planning-artifacts/epics.md#Story-1.1] — Story 定义与 AC 原文
- [Source: docs/planning-artifacts/architecture.md#Decision-5.1] — Docker Compose 单机编排
- [Source: docs/planning-artifacts/architecture.md#Decision-5.2] — 多阶段镜像构建（uv builder + python:3.12-slim runtime）
- [Source: docs/planning-artifacts/architecture.md#Decision-5.3] — GitHub Actions CI/CD
- [Source: docs/planning-artifacts/architecture.md#Decision-5.4] — loguru + request_id 监控
- [Source: docs/planning-artifacts/architecture.md#Decision-5.5] — Pydantic Settings 配置管理
- [Source: docs/planning-artifacts/architecture.md#AR-1] — 项目初始化（Vite/FastAPI/uv 技术栈）
- [Source: docs/planning-artifacts/architecture.md#AR-2] — Docker Compose 6 服务
- [Source: docs/planning-artifacts/architecture.md#AR-3] — GitHub Actions CI/CD
- [Source: docs/planning-artifacts/architecture.md#AR-4] — Pydantic Settings
- [Source: docs/planning-artifacts/architecture.md#AR-5] — loguru 结构化日志 + request_id
- [Source: docs/planning-artifacts/architecture.md#AR-10] — JWT + API Key 双认证（本 Story 仅占位 security.py）
- [Source: docs/planning-artifacts/architecture.md#AR-14] — REST API 路径规范
- [Source: docs/planning-artifacts/architecture.md#AR-18] — 命名规范（DB/JSON/Python snake_case；TS camelCase；前端文件 kebab-case）
- [Source: docs/planning-artifacts/architecture.md#AR-20] — 后端 4 层 + 前端 features 分层
- [Source: docs/planning-artifacts/architecture.md#AR-21] — AppError 异常体系 + loguru
- [Source: docs/planning-artifacts/architecture.md#AR-22] — ULID ID 格式
- [Source: docs/planning-artifacts/architecture.md#AR-23] — 统一错误响应结构
- [Source: docs/planning-artifacts/architecture.md#Getting-Started] — 完整 uv + npm 初始化命令
- [Source: docs/planning-artifacts/architecture.md#Directory-Tree] — 完整项目目录树（约 200 个文件）
- [Source: docs/planning-artifacts/ux-designs/ux-agent-flow-2026-06-08/DESIGN.md] — 设计 token（颜色/字体/间距/圆角/阴影）
- [Source: docs/planning-artifacts/ux-designs/ux-agent-flow-2026-06-08/EXPERIENCE.md] — App Shell 布局（本 Story 仅建骨架，Story 1.7 实现）
- [Source: docs/planning-artifacts/prds/prd-agent-flow-2026-06-05/prd.md#Cross-Cutting-NFRs] — NFR 约束（性能/可靠性/安全/可扩展）
- [Source: MEMORY.md] — 后端必须使用 uv 工具链（项目核心约定）

---

## Dev Agent Record

### Agent Model Used

Claude Opus 4.6 (claude-opus-4-6) via Claude Code CLI

### Debug Log References

- Backend lint: ruff check — All checks passed
- Backend type: mypy app — Success (37 source files)
- Backend test: pytest — 16 passed
- Frontend type: tsc -b — no errors
- Frontend lint: eslint — no errors
- Frontend build: vite build — ✓ built in 793ms

### Completion Notes List

All 12 ACs implemented and verified:
- AC1: Docker Compose 6-service orchestration (deploy/)
- AC2: API route conventions (/api/v1/{resource})
- AC3: ULID ID format ({resource}_{ulid})
- AC4: Frontend component structure (features/ + components/)
- AC5: CI/CD pipeline (.github/workflows/)
- AC6: Pydantic Settings config (backend/app/core/config.py)
- AC7: Lock files (uv.lock + package-lock.json)
- AC8: Backend 4-layer skeleton (api/services/engine/workers)
- AC9: Frontend layered skeleton (features/hooks/services/stores/lib/types/routes/config)
- AC10: 5 baseline patterns (AppError, loguru, request_id, ULID, ConfigProvider)
- AC11: Frontend theme baseline (Tailwind + AntD tokens)
- AC12: Makefile one-click commands

### File List

Backend (37 .py files):
- app/main.py — FastAPI entry point
- app/core/{config,errors,logging,pagination,security}.py
- app/api/{deps,errors}.py + middleware/{request_id,logging_mw,exception_mw}.py + v1/{health,router}.py
- app/models/base.py — ULID + timestamps
- app/schemas/common.py — Error/Pagination schemas
- app/db/{mongodb,redis,indexes}.py
- app/engine/{state,checkpointer,llm_factory,prompt,context}.py
- app/workers/{celery_app,beat_schedule}.py + tasks/
- tests/{conftest, api/test_{health,request_id,exception_mw}, core/test_errors}.py
- Dockerfile + scripts/{init_mongo,generate_openapi}.py

Frontend:
- vite.config.ts — @ alias + /api proxy
- tailwind.config.ts — brand tokens
- src/{main,App}.tsx — AntD ConfigProvider + theme
- src/{pages,components,hooks,services,stores,lib,types,routes,config}/ — layered skeleton
- Dockerfile + nginx.conf

Infrastructure:
- deploy/{docker-compose.yml, docker-compose.dev.yml, Caddyfile, mongo/, redis/, scripts/}
- .github/workflows/{ci,build,deploy}.yml
- scripts/{setup-dev,generate-api-types,pre-commit}.sh
- .vscode/{settings,extensions,launch}.json
