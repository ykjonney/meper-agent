# Agent Flow

AI Agent 编排与自动化平台。支持 Agent 管理、可视化工作流编排、MCP/Skill 工具集成、RBAC 权限控制、任务调度与执行。

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端框架 | FastAPI + Uvicorn |
| Agent 引擎 | LangGraph 1.x + LangChain |
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
│   │   ├── api/v1/       # REST API 路由
│   │   ├── core/         # 配置、安全、日志
│   │   ├── engine/       # Agent 引擎（LangGraph 构建、工具执行）
│   │   ├── models/       # MongoDB 数据模型
│   │   ├── schemas/      # Pydantic 请求/响应模型
│   │   ├── services/     # 业务逻辑层
│   │   ├── cli/          # CLI 命令（create-admin 等）
│   │   └── main.py       # FastAPI 应用入口
│   ├── tests/            # 测试套件
│   ├── pyproject.toml    # Python 项目配置（uv）
│   └── .env.example      # 环境变量模板
├── frontend/             # 前端应用
│   ├── src/
│   │   ├── components/   # 通用组件
│   │   ├── features/     # 功能模块（工作流编辑器等）
│   │   ├── pages/        # 页面
│   │   ├── services/     # API 调用层
│   │   ├── stores/       # Zustand 状态
│   │   └── types/        # TypeScript 类型
│   ├── package.json
│   └── .env.example      # 环境变量模板
├── deploy/               # Docker 部署配置
│   ├── docker-compose.yml
│   └── docker-compose.dev.yml
└── docs/                 # 项目文档
```

## 前置依赖

| 依赖 | 版本要求 |
|------|---------|
| Python | >= 3.12 |
| Node.js | >= 18（推荐 20+） |
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

### 4. 启动前端

```bash
cd frontend

# 复制环境变量模板
cp .env.example .env

# 安装依赖
npm install

# 启动开发服务器
npm run dev
```

### 5. 访问应用

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
| `MODEL_ENCRYPTION_KEY` | API Key 加密密钥 | — |

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

# 创建数据目录
mkdir -p data/mongodb data/redis

# 启动所有服务
docker compose up -d

# 创建管理员账户（首次部署需要）
docker compose run --rm --profile init create-admin
```

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
# 以下两项本地开发必须留空（路径转换仅在 backend 容器化时需要）
SANDBOX_HOST_WORKSPACES_DIR=
SANDBOX_HOST_SKILLS_DIR=
```

### 3. 验证生效

启动 backend 后，Agent 调用 bash 工具时日志应显示：
```
sandbox_docker_executed exit_code=0 duration="0.5s"
```

若看到 `sandbox_subprocess_executed` 则说明未成功启用沙盒，仍在使用降级的 subprocess 执行。

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
cd frontend

# 运行测试
npm run test

# 监听模式
npm run test:watch

# 代码检查
npm run lint

# 自动修复
npm run lint:fix

# 类型检查
npm run type-check

# 代码格式化
npm run format

# 生产构建
npm run build
```

## API 文档

启动后端后，访问以下地址查看交互式 API 文档：

- **Swagger UI**：http://localhost:8000/docs
- **ReDoc**：http://localhost:8000/redoc
