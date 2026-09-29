# Agent Flow

AI Agent 编排与自动化平台。Agent 管理（版本化+快照回滚）、可视化工作流编排（DAG + Human 审核）、**计划模式**（先规划后人审再执行）、**Agent 自繁殖**（agent 创建 agent）、工具输出回溯（压缩可逆）、执行过程账（request 级事件流）、LLM 稳定错误码 + SDK 级重试、IM 渠道接入（钉钉/飞书，熔断分级）、MCP/Skill 工具集成、RBAC 权限控制、Docker 沙盒隔离执行。

## 核心特性

### Agent 执行引擎（harness）

| 特性 | 说明 |
|------|------|
| **REACT 循环** | LangGraph StateGraph：compress → llm → ToolNode 回环，流式 SSE |
| **三种执行上下文** | `chat`（全量工具）/ `workflow`（无人值守，剥离 HITL）/ `plan`（调研设计优先，剥离变更工具） |
| **上下文工程** | 两级工具输出压缩 + LLM 语义摘要 + 图片降级占位 + 中断标注 + 未消费保护 |
| **工具输出回溯** | 压缩发生时自动归档原文到 `tool_output_archives`（TTL 30 天），agent 可用 `recall_tool_result` 取回——压缩可逆 |
| **LLM 重试 + 错误码** | SDK 级瞬态重试（`Agent.max_retry`）+ 8 类稳定错误码（`LLM_TIMEOUT/AUTH/QUOTA/…`），渠道按码分级熔断 |
| **Docker 沙盒** | 只读 rootfs + no-new-privileges + 断网 + fail-closed（不可用则拒绝执行） |
| **HITL** | `ask_clarification`（澄清问答/向导表单）、`request_app_authorization`（MCP 凭证授权）、`propose_plan`（计划审批）——全部基于 `interrupt()` + checkpointer |

### 计划模式（Plan Mode）

```
开关开启 → 调研（沙盒探索合法，变更工具禁） → propose_plan 提交计划书
  → 审批卡（文档样式：目标/背景约束/步骤☐/验收标准/交付物）
  → [同意执行] → PLAN.md 落盘 + 合成 tool_result（零 LLM 成本） → 自动 kickoff
  → 执行：读 PLAN.md、逐步勾选、验收对照
  → [反馈] → 修订循环（探针读 checkpoint 强制 plan 上下文，不信客户端）
  → [拒绝] → dismiss 终止
```

- 计划书支持**编辑后批准**（编辑稿直接落盘 PLAN.md，零 LLM）
- **双重确认抑制**：计划中点名的工作流自动免 confirm_workflow 卡
- **工具清单警示**：卡片高亮"本计划将使用 X/Y"（变更类 ⚠）
- 判据：**不确定性而非步骤数**——路径明确、每步可逆的批量任务直接执行不造计划

### Agent 自繁殖（Spawn）

```
can_spawn_agents 手动开启（编辑器开关）
  → list_capabilities（盘点：内置/自定义/MCP 连接+工具/技能/模型/参考 agent）
  → create_agent（draft 态 + 不放大权限 + 审计标记）
  → test_agent（独立干净会话试跑验收）
  → 人审发布
```

治理三原则：draft 闸门（人审发布）、权限不放大（创建物恒无 can_spawn）、审计可溯（父 agent id + 会话 id 落档）。

### Agent 版本化 + 快照回滚

```
每次 update_agent → 自动快照当前状态 + version +1（永不复用）
回滚 = 快照当前（防后悔）→ 以目标版本恢复 → version = max + 1
```

API：`GET /agents/{id}/snapshots`、`GET /agents/{id}/snapshots/{ver}`、`POST /agents/{id}/snapshots/{ver}/restore`

自优化循环（"严格提升才保留"）的硬前置。

### 执行过程账（Execution Events）

每次 agent 调用自动记录 9 种事件（≤16KB，超限丢中段保首尾）：

| 事件 | 记录内容 |
|------|---------|
| `tools_resolved` | 工具装配结果 + 加载失败 |
| `request_begin/end` | LLM 请求边界 + 逐请求 token |
| `tool_call/result` | 工具调用元数据（参数预览/耗时/字符数/成功与否） |
| `compaction` | 上下文压缩发生与效果 |
| `interrupt` | 人机协同中断（澄清/授权/取消） |
| `error` | 失败 + 稳定错误码 |

仪表盘可视化：执行记录 tab（筛选/分页/详情弹窗过程时间线）、Agent 调用趋势图、渠道分布、指标卡。

### IM 渠道接入

- 钉钉 Stream 模式、飞书事件订阅
- 会话延续（channel 域内复用 session，空闲/活满/预算耗尽三边界轮换）
- **分级熔断**：`LLM_AUTH`/`LLM_QUOTA` 确定性失败 → 立即 DEGRADED；可重试类照旧计数到阈值
- 消息幂等去重（msgId 级别）

## 架构总览

```
┌─────────────────────────────────────────────────────────────┐
│  frontend-studio（管理端）   frontend-client（终端用户）      │
│  • 会话/Agent/工作流/任务/仪表盘   • 对话/文件/技能反馈        │
├─────────────────────────────────────────────────────────────┤
│  FastAPI（API 层）                                           │
│  • agents / workflows / tasks / channels / admin / ext     │
├─────────────────────────────────────────────────────────────┤
│  Services（业务层）                                          │
│  • AgentExecutionService（chat invoke/stream/resume）       │
│  • AgentSnapshotService（版本化+回滚）                       │
│  • ExecutionLogService（过程账+聚合）                        │
│  • ChannelService（IM 渠道+分级熔断）                        │
│  • ToolOutputArchiveService（压缩归档）                      │
├─────────────────────────────────────────────────────────────┤
│  harness_integration（适配层）                                │
│  • context.py（装配：LLM/工具/formatter/中间件/ContextVar）    │
│  • execution.py（stream/invoke/resume 入口 + 探针推断）        │
│  • adapters/（AppEvent 翻译 + SSE）                          │
│  • recorder_middleware.py（过程事件采集）                     │
├─────────────────────────────────────────────────────────────┤
│  agent-flow-harness（可独立发布的引擎库）                      │
│  • graph/（StateGraph REACT 循环 + 压缩节点）                 │
│  • sandbox/（Docker fail-closed 沙盒）                       │
│  • mcp/（per-user 凭证透传 + fail-closed 守卫）               │
│  • interaction/（clarification / app_auth / plan）           │
│  • subagents/ / skills/ / context_engineering/              │
├─────────────────────────────────────────────────────────────┤
│  Celery Worker（异步任务）                                    │
│  • workflow_execution / channel_inbound / beat 定时清理      │
├─────────────────────────────────────────────────────────────┤
│  MongoDB（agents/sessions/messages/tasks/execution_logs/    │
│           tool_output_archives/agent_snapshots/…）           │
│  Redis（运行取消标志/Celery Broker）                          │
└─────────────────────────────────────────────────────────────┘
```

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端框架 | FastAPI + Uvicorn |
| Agent 引擎 | LangGraph 1.x + LangChain(核心逻辑抽取为独立库 `agent-flow-harness`,见 `backend/packages/harness`) |
| 数据库 | MongoDB 7.0（Motor 异步驱动） |
| 缓存 / 消息队列 | Redis 7+ |
| 任务队列 | Celery |
| 前端框架 | React 19 + TypeScript + Vite |
| UI 组件 | Ant Design 6 + Tailwind CSS |
| 工作流画布 | @xyflow/react |
| 状态管理 | Zustand + TanStack React Query |
| 部署 | Docker Compose + Caddy |

## 项目结构

```
agent-flow/
├── backend/              # 后端服务
│   ├── app/
│   │   ├── api/v1/       # REST API 路由（ext/ 子目录为外部终端用户 API）
│   │   ├── core/         # 配置、安全、日志
│   │   ├── db/           # MongoDB / Redis 连接与索引
│   │   ├── engine/       # Agent 引擎
│   │   │   ├── agent/    #   内置工具（recall/plan/spawn/chart/…）
│   │   │   ├── workflow/ #   自研 DAG 引擎 + 节点执行器
│   │   │   └── harness_integration/  # app ↔ harness 适配层
│   │   ├── models/       # MongoDB 数据模型
│   │   ├── schemas/      # Pydantic 请求/响应模型
│   │   ├── services/     # 业务逻辑层（api 层不直接操作 db）
│   │   ├── utils/        # 工具函数（LLM 错误码/输入清洗/模板渲染）
│   │   ├── workers/      # Celery 任务（工作流/渠道/定时清理）
│   │   └── main.py       # FastAPI 应用入口
│   ├── packages/
│   │   └── harness/      # agent-flow-harness —— 可独立发布的引擎库
│   │       │             #  （LangGraph 编排、沙盒、guards、中间件、压缩），
│   │       │             #  editable 安装，backend 改它即时生效
│   ├── tests/            # 测试套件
│   └── .env.example
├── frontend-studio/      # Studio 管理端——当前活跃开发
│   ├── src/
│   │   ├── components/   # 页面组件（会话/Agent/工作流/任务/仪表盘/渠道/…）
│   │   ├── features/     # 工作流编辑器（React Flow 画布）
│   │   ├── services/     # API 调用层（agent-api/workflow-api/…）
│   │   ├── stores/       # Zustand 状态
│   │   └── hooks/        # usePermission / useTaskRealtime / …
├── frontend/             # 管理端前端（原始，部分功能已迁移至 studio）
├── frontend-client/      # 终端用户对话客户端（React + Ant Design）
├── deploy/               # Docker Compose + Caddy + sandbox 镜像
├── docs/                 # 项目文档
└── README.md
```

## 前置依赖

| 依赖 | 版本要求 |
|------|---------|
| Python | >= 3.12 |
| Node.js | >= 20（推荐 22+,与 CI 一致） |
| MongoDB | >= 7.0 |
| Redis | >= 7.0 |
| uv（Python 包管理器） | 最新稳定版（见下方安装说明） |

### 安装 uv

本项目推荐使用 [uv](https://docs.astral.sh/uv/) 管理 Python 依赖。安装方式：

**macOS / Linux：**

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Windows：**

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

**通过 pip 安装：**

```bash
pip install uv
```

安装完成后验证：

```bash
uv --version
```

## 快速开始（本地开发）

### 1. 克隆仓库

```bash
git clone <repo-url>
cd agent-flow
```

### 2. 启动基础设施（MongoDB + Redis）

**方式 A：使用 Docker Compose 仅启动基础设施**

```bash
docker compose -f deploy/docker-compose.yml up -d mongodb redis
```

**方式 B：本地安装**

确保 MongoDB 和 Redis 已在本地运行，默认端口分别为 `27017` 和 `6379`。

### 3. 启动后端

```bash
cd backend

# 复制环境变量模板并编辑
cp .env.example .env
# 按需修改 .env 中的配置（MongoDB 地址、Redis 地址、JWT 密钥等）

# 安装依赖（uv 自动创建虚拟环境）
uv sync

# 创建初始管理员账户
uv run python -m app.cli create-admin \
  --username admin \
  --password your-password \
  --email admin@example.com

# 启动开发服务器
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

**备选方案：不使用 uv（pip + venv）**

如果你不想安装 uv，可以使用 Python 自带的 venv 和 pip：

```bash
cd backend

# 创建虚拟环境
python -m venv .venv

# 激活虚拟环境
source .venv/bin/activate  # Linux/macOS
# .venv\Scripts\activate   # Windows

# 安装依赖
pip install -e .

# 创建初始管理员账户
python -m app.cli create-admin \
  --username admin \
  --password your-password \
  --email admin@example.com

# 启动开发服务器
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 4. 启动 Celery Worker

工作流执行、Webhook 投递、定时任务等异步任务由 Celery worker 处理，需单独启动（新开一个终端）：

```bash
cd backend
source .venv/bin/activate  # 或 uv run 前缀

celery -A app.workers.celery_app worker --loglevel=info --concurrency=2
```

> **不启动 Worker 的影响**：创建工作流任务后会一直停留在 `pending` 状态，Agent 不会执行；Webhook 投递不会触发。Agent 会话聊天（直接调用 LLM）不受影响，因为它走的是 FastAPI 同步流式接口，不经过 Celery。

> **定时触发器**（cron/once）由 `TriggerSchedulerService` 在 FastAPI 进程内轮询，不依赖 Celery Beat。Beat 仅用于 `cleanup_expired_workspaces` 定时清理，本地开发可不启动。

### 5. 启动前端

```bash
# Studio 管理端（当前活跃开发——工作流编辑器、仪表盘、渠道管理、计划模式等）
cd frontend-studio
npm install
npm run dev

# 或原始管理端（部分功能已迁移至 studio）
cd frontend
npm install
npm run dev
```

### 6. 访问应用

| 地址 | 说明 |
|------|------|
| http://localhost:5173 | 前端界面 |
| http://localhost:8000/docs | Swagger API 文档 |
| http://localhost:8000/redoc | ReDoc API 文档 |
| http://localhost:8000/health | 健康检查 |

## 环境变量说明

### 后端（`backend/.env`）

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `APP_NAME` | 应用名称 | `Agent Flow` |
| `APP_ENV` | 运行环境 | `development` |
| `DEBUG` | 调试模式 | `true` |
| `MONGODB_URI` | MongoDB 连接地址 | `mongodb://localhost:27017` |
| `MONGODB_DB_NAME` | 数据库名称 | `agent_flow` |
| `REDIS_URL` | Redis 连接地址 | `redis://localhost:6379/0` |
| `JWT_SECRET_KEY` | JWT 签名密钥（**生产环境务必修改**） | — |
| `JWT_ALGORITHM` | JWT 算法 | `HS256` |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | 访问令牌过期时间（分钟） | `15` |
| `JWT_REFRESH_TOKEN_EXPIRE_DAYS` | 刷新令牌过期时间（天） | `7` |
| `CELERY_BROKER_URL` | Celery Broker 地址 | `redis://localhost:6379/1` |
| `CELERY_RESULT_BACKEND` | Celery 结果后端地址 | `redis://localhost:6379/2` |
| `CORS_ORIGINS` | 允许的跨域来源（逗号分隔） | `http://localhost:5173,http://localhost:3000` |
| `LOG_LEVEL` | 日志级别 | `INFO` |
| `LOG_JSON_FORMAT` | 日志是否输出 JSON 格式 | `false` |
| `MODEL_ENCRYPTION_KEY` | API Key 加密密钥 | — |
| **可观测性** | | |
| `LANGSMITH_API_KEY` | LangSmith API Key（留空则不启用链路追踪，[免费 Developer 计划](https://www.langchain.com/pricing)含 5000 traces/月） | — |
| `LANGSMITH_PROJECT` | LangSmith 项目名称 | `agent-flow` |
| **Token 限额** | | |
| `DEFAULT_SESSION_MAX_TOKENS` | 单个会话累计 Token 上限（超出后 Agent 自动停止），Agent 可通过 `max_tokens` 字段单独覆盖 | `200000` |
| **执行过程账** | | |
| `CHANNEL_PERSIST_MESSAGES` | IM 渠道会话是否落 messages 明细（默认关——审计由 execution_log events 承担） | `false` |
| **上下文压缩** | | |
| `COMPRESSION_PROTECTED_TURNS` | 压缩时保护的最近对话轮数 | `5` |
| `COMPRESSION_THRESHOLD` | 触发压缩的上下文占比（0.0~1.0） | `0.7` |
| `COMPRESSION_HARD_LIMIT_RATIO` | 紧急丢弃最早消息的硬上限占比 | `0.9` |
| `IMAGE_KEEP_RECENT_N` | 图片降级时保留最近 N 张真图（0=全部降级） | `3` |
| **工作空间路径** | | |
| `WORKSPACES_HOST_DIR` | 宿主机工作空间根目录，按 `{user_id}/{session_id}/` 分子目录 | `~/.agent-flow/workspaces` |
| `WORKSPACES_CONTAINER_DIR` | 容器内工作空间路径。**本地开发无需设置**，自动推导为 `WORKSPACES_HOST_DIR`；Docker 部署时由 `docker-compose.yml` 注入 | 自动推导 |
| `SKILLS_HOST_DIR` | 宿主机 Skill 文件存储目录 | `~/.agent-flow/skills` |
| `SKILLS_CONTAINER_DIR` | 容器内 Skill 路径。规则同 `WORKSPACES_CONTAINER_DIR` | 自动推导 |
| `WORKSPACE_MAX_BYTES` | 单个工作空间最大字节数（0 = 不限） | `524288000`（500 MB） |
| **沙盒执行（Sandbox）** | | |
| `SANDBOX_ENABLED` | 是否使用 Docker 容器隔离执行 bash 命令。`false` 时降级为宿主机 subprocess | `false` |
| `SANDBOX_IMAGE` | 沙盒 Docker 镜像名称 | `agent-sandbox:latest` |
| `SANDBOX_MEM_LIMIT` | 沙盒容器内存上限 | `512m` |
| `SANDBOX_CPU_QUOTA` | CPU 配额（微秒/秒，100000 = 1 核） | `100000` |
| `SANDBOX_TIMEOUT` | 单条命令超时秒数 | `120` |
| `SANDBOX_MAX_OUTPUT_BYTES` | 命令输出最大字节数 | `51200`（50 KB） |
| `SANDBOX_NETWORK_MODE` | 网络模式：`none`（无网络，最安全）/ `bridge`（可访问外网）/ `host`（共享宿主机网络，隔离最弱） | `none` |
| `SANDBOX_CONTAINER_WORKSPACE_DIR` | 沙盒容器内工作区挂载点（一般无需修改） | `/workspace` |
| `SANDBOX_CONTAINER_SKILLS_DIR` | 沙盒容器内 Skill 目录挂载点（一般无需修改） | `/data/skills` |

### 前端（`frontend/.env`）

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `VITE_API_BASE_URL` | 后端 API 地址 | `http://localhost:8000` |
| `VITE_WS_BASE_URL` | 后端 WebSocket 地址 | `ws://localhost:8000` |

## Docker 部署

### 生产部署

```bash
cd deploy

# 复制并编辑环境变量
cp .env.example .env
# 按需修改 .env 中的配置（特别是 JWT_SECRET_KEY、MONGO_ROOT_PASSWORD、ADMIN_PASSWORD 等）
# 数据目录默认使用 ~/.agent-flow/...（与项目代码分离），无需额外配置

# 创建数据目录（默认路径 ~/.agent-flow/）
mkdir -p ~/.agent-flow/{mongodb,redis,workspaces,skills}

# 构建 sandbox 镜像（重要，见下方说明）
make build-sandbox

# 启动所有服务
docker compose up -d

# 创建管理员账户（首次部署需要）
docker compose run --rm --profile init create-admin
```

`deploy/.env` 中的关键数据目录变量（均使用 `${HOME}` 自动解析为绝对路径，数据与项目代码分离）：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `WORKSPACES_HOST_DIR` | `${HOME}/.agent-flow/workspaces` | 宿主机工作空间目录 |
| `SKILLS_HOST_DIR` | `${HOME}/.agent-flow/skills` | 宿主机 Skill 目录 |
| `MONGODB_DATA_DIR` | `${HOME}/.agent-flow/mongodb` | MongoDB 数据持久化目录 |
| `REDIS_DATA_DIR` | `${HOME}/.agent-flow/redis` | Redis 数据持久化目录 |
| `WORKSPACES_CONTAINER_DIR` | `/data/workspaces` | 容器内工作空间挂载点（一般无需修改） |
| `SKILLS_CONTAINER_DIR` | `/data/skills` | 容器内 Skill 挂载点（一般无需修改） |

此命令将启动：
- **Caddy**（端口 80/443）— 统一入口，构建并服务前端静态文件 + 反向代理 API（`deploy/Dockerfile.caddy`）
- **Backend**（端口 8000）— FastAPI 服务
- **Celery Worker** — 异步任务处理
- **MongoDB**（端口 27017）— 数据库
- **Redis**（端口 6379）— 缓存和消息队列

访问地址：
- 前端界面：http://localhost
- API 文档：http://localhost/api/v1/docs

### 更新代码

代码更新后，重新构建并重启服务：

```bash
cd deploy

# 重新构建所有镜像并重启
docker compose up -d --build

# 或只重建特定服务
docker compose up -d --build backend
docker compose up -d --build caddy
```

### 开发模式

```bash
cd deploy
cp .env.example .env  # 首次需要
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
```

启动的服务：
- **Frontend**（端口 5173）— Vite 开发服务器
- **Backend**（端口 8000）— FastAPI
- **Celery Worker** — 异步任务处理
- **MongoDB**（端口 27017）
- **Redis**（端口 6379）

访问地址：
- 前端界面：http://localhost:5173
- API 文档：http://localhost:8000/docs

### ⚠️ 关于 Sandbox 镜像（重要）

项目使用沙盒容器来安全隔离执行 Agent 生成的 shell 命令。**默认的 `docker compose up` 不会自动构建 sandbox 镜像**，因为它使用了 `profiles: [tools]` 进行配置隔离。

**如果未构建 sandbox 镜像：**
- 所有 Agent 的 bash 命令会**静默降级**为宿主机 subprocess 执行
- 程序不会报错，但会**完全失去安全隔离**
- 日志中会出现警告：`sandbox_docker_unavailable, falling back to subprocess`

**构建 sandbox 镜像（推荐在部署前执行）：**

```bash
# 方式一：使用 Makefile
make build-sandbox

# 方式二：使用 docker compose
docker compose -f deploy/docker-compose.yml build sandbox
```

**验证镜像是否已构建：**

```bash
make deploy-check
# 输出 "✅ agent-sandbox:latest image found" 表示已就绪
```

**镜像包含的工具：**

| 类别 | 内容 |
|------|------|
| 系统命令 | curl, git, jq, wget, unzip, tree |
| 编译环境 | gcc, libxml2-dev, libxslt1-dev |
| 图像处理 | libjpeg-dev, zlib1g-dev, Pillow |
| Node.js | 22.x（含 npm） |
| Python 数据科学栈 | pandas, numpy, scipy, matplotlib, openpyxl |

## 终端用户客户端（frontend-client）

面向终端用户的独立对话客户端（`frontend-client/`），基于 React + Ant Design，通过 JWT 登录使用。生产环境由 Caddy 托管在 `/client/` 路径，开发环境端口 3001。

```bash
cd frontend-client
npm install
npm run dev    # 启动开发服务器 http://localhost:3001
npm run build  # 生产构建
```

## Studio 管理端（frontend-studio）

当前活跃开发的管理端前端（`frontend-studio/`），基于 React 19 + Tailwind CSS + TanStack Query + Zustand。

```bash
cd frontend-studio
npm install
npm run dev    # 启动开发服务器（默认 Vite 端口）
npm run lint   # = tsc --noEmit（类型检查）
npm run build  # 生产构建
```

主要功能页面：

| 页面 | 功能 |
|------|------|
| 会话记录 | ChatHomepage（含计划模式开关/计划书审批卡/工具卡片） |
| 仪表盘 | 任务运行历史 tab + Agent 执行记录 tab（筛选/分页/详情弹窗过程时间线）+ 调用趋势图 + 渠道分布 |
| 智能体 | Agent 空间 + 编辑器（含"允许创建 Agent"开关、版本号） |
| AI 工作路线 | WorkflowSpace + React Flow 画布编辑器 |
| 工具库 | 内置工具 + 组织自定义工具统一目录 |
| 消息渠道 | 钉钉/飞书渠道配置（长连接/密钥/状态） |
| 外部授权 | MCP 应用授权管理 |

## 路径变量说明（HOST_DIR vs CONTAINER_DIR）

系统涉及两类路径变量，理解其区别对正确配置至关重要：

| 变量后缀 | 含义 | 使用场景 |
|----------|------|---------|
| `*_HOST_DIR` | **宿主机**（或 Docker 宿主机）上的绝对路径 | Docker 挂载、沙盒容器 bind mount 的源路径 |
| `*_CONTAINER_DIR` | **容器内部**的路径（backend 或 sandbox 容器内） | backend 代码读写文件时使用的路径 |

**本地开发：** 只需设置 `*_HOST_DIR`（如 `WORKSPACES_HOST_DIR=~/.agent-flow/workspaces`）。`*_CONTAINER_DIR` 在 `backend/.env` 中留空即可，启动时会自动推导为对应的 `*_HOST_DIR`。

**Docker 部署：** `docker-compose.yml` 通过环境变量同时注入两者：`*_HOST_DIR` 用于 bind mount 源路径，`*_CONTAINER_DIR`（如 `/data/workspaces`）用于容器内挂载目标路径。backend 代码始终通过 `*_CONTAINER_DIR` 访问文件，在生成沙盒容器时再转换为宿主机路径用于 bind mount。

```
宿主机                              backend 容器                     sandbox 容器
~/.agent-flow/workspaces ─compose mount─▶ /data/workspaces            /workspace
  (WORKSPACES_HOST_DIR)              (WORKSPACES_CONTAINER_DIR)    (SANDBOX_CONTAINER_WORKSPACE_DIR)
        │                                  │ backend 代码读写此路径
        │                                  │
        └─── sandbox.py _host_path() 将容器路径翻译为 HOST_DIR ─docker API mount─▶
```

> **注意**：sandbox 的 bind mount 源路径始终是 **HOST_DIR**（宿主机视角），因为 Docker daemon 运行在宿主机上，无法识别容器内路径。`sandbox.py` 中的 `_host_path()` 负责做这个翻译。

## 本地开发启用 Sandbox

默认本地开发 `SANDBOX_ENABLED=false`（bash 命令直接通过 subprocess 执行，方便调试）。如需在本地测试沙盒隔离执行：

### 1. 构建 sandbox 镜像

```bash
make build-sandbox
```

### 2. 在 `backend/.env` 中启用沙盒

```bash
# 在 backend/.env 末尾追加
SANDBOX_ENABLED=true
SANDBOX_IMAGE=agent-sandbox:latest
# HOST_DIR 已在 .env 中配置，CONTAINER_DIR 留空会自动推导，无需额外配置
```

### 3. 验证生效

启动 backend 后，Agent 调用 bash 工具时日志应显示：
```
sandbox_docker_executed exit_code=0 duration="0.5s"
```

若看到 `sandbox_subprocess_executed` 则说明未成功启用沙盒，仍在使用降级的 subprocess 执行。

## 可观测性

### Token 消耗可视化

每条 AI 回复下方会显示本轮 Token 用量（如 `· 1,234 tokens · 3 轮`），数据持久化到 Message 和 Session 文档中，刷新页面不丢失。

### 会话级 Token 限额

通过 `DEFAULT_SESSION_MAX_TOKENS`（默认 20 万）配置全局会话 Token 上限。每个 Agent 可在配置页单独设置 `max_tokens` 字段覆盖全局默认值。超出限额时 Agent 自动停止，防止恶意消耗 LLM API 配额。

### 执行过程账（Execution Events）

每次 agent 调用（invoke/stream/resume，跨 internal/api_key/im 三渠道）自动记录过程事件到 `execution_logs` 集合——request 边界、逐请求 token、工具调用元数据、压缩/中断/错误，capped ≤16KB（超限丢中段保首尾+自声明）。

仪表盘可视化：执行记录 tab（来源/状态/Agent/会话筛选、分页、详情弹窗含过程事件时间线）、Agent 调用趋势图（按日聚合）、渠道分布、指标卡（调用总数/成功率/Token 消耗）。

### LLM 稳定错误码

8 类机器码贯穿 SSE / execution_log / 渠道熔断：`LLM_TIMEOUT / LLM_NETWORK / LLM_RATE_LIMIT / LLM_QUOTA / LLM_AUTH / LLM_UNSUPPORTED / LLM_INVALID_INPUT / LLM_UNKNOWN`。渠道按码分级：AUTH/QUOTA 确定性失败 → 立即 DEGRADED；可重试类照旧计数到阈值。

### 结构化日志

后端使用 loguru 统一日志管道（stdout 人类可读 + 文件 JSON 序列化）。harness 引擎的 structlog 日志自动桥接到 loguru，确保所有日志格式统一、共享同一文件 sink。uvicorn access log 已关闭以避免重复。

### LangSmith 链路追踪（可选）

在 `.env` 中设置 `LANGSMITH_API_KEY` 即可启用 LangSmith 链路追踪。启用后，每次 Agent 执行的 LLM 调用、工具调用、REACT 循环都会以 trace 树的形式上报到 `smith.langchain.com`，可在 Web UI 中查看完整的执行链路、Token 用量和延迟分析。

```bash
# .env 中添加
LANGSMITH_API_KEY=lsv2_xxx
LANGSMITH_PROJECT=agent-flow
```

## 默认角色与权限

系统内置 4 个角色：

| 角色 | 说明 |
|------|------|
| `admin` | 系统管理员，拥有所有权限 |
| `developer` | 开发者，可创建和管理 Agent、工作流、工具 |
| `operator` | 运维人员，可执行和管理任务 |
| `viewer` | 只读用户，仅可查看 |

## 开发指南

### 后端

> 以下命令假设已激活虚拟环境（`source .venv/bin/activate`）。如果使用 uv，将 `pytest` 等替换为 `uv run pytest` 即可。

```bash
cd backend

# 运行测试
pytest

# 运行测试并生成覆盖率报告
pytest --cov=app --cov-report=term-missing

# 代码检查
ruff check .

# 代码格式化
ruff format .

# 类型检查
pyright
```

### 前端

```bash
# frontend-studio（当前活跃开发）
cd frontend-studio
npm run lint       # = tsc --noEmit（类型检查）
npm run build      # 生产构建

# frontend（原始管理端）
cd frontend
npm run test       # 运行测试
npm run lint       # 代码检查
npm run build      # 生产构建
```

## API 文档

启动后端后，访问以下地址查看交互式 API 文档：

- **Swagger UI**：http://localhost:8000/docs
- **ReDoc**：http://localhost:8000/redoc
