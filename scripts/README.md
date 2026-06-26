# Agent Flow 部署脚本

不使用Docker的本地部署脚本，用于启动和停止Agent Flow的所有服务。

## 脚本说明

### `start.sh` - 启动所有服务

```bash
./scripts/start.sh
```

启动顺序：
1. 检查依赖服务（MongoDB、Redis）
2. 启动后端（FastAPI + Uvicorn，端口8000）
3. 启动Celery Worker（异步任务处理）
4. 启动前端（Vite dev server，端口3000）

### `stop.sh` - 停止所有服务

```bash
./scripts/stop.sh
```

停止顺序：
1. 停止后端服务
2. 停止Celery Worker
3. 停止前端服务
4. 清理所有子进程

### `status.sh` - 查看服务状态

```bash
./scripts/status.sh
```

显示：
- 依赖服务状态（MongoDB、Redis）
- 应用服务状态（后端、Celery、前端）
- 日志文件信息

## 访问地址

启动后，可以通过以下地址访问：

- **前端界面**: http://localhost:3000
- **后端API**: http://localhost:8000
- **API文档**: http://localhost:8000/docs

## 日志文件

所有日志都保存在 `logs/` 目录：

- `backend.log` - 后端服务日志
- `celery.log` - Celery Worker日志
- `frontend.log` - 前端服务日志

实时查看日志：

```bash
# 查看后端日志
tail -f logs/backend.log

# 查看Celery日志
tail -f logs/celery.log

# 查看前端日志
tail -f logs/frontend.log
```

## 依赖要求

### 系统依赖

- **Python 3.12+** - 后端运行环境
- **Node.js 18+** - 前端运行环境
- **MongoDB 7.0+** - 数据库
- **Redis** - 缓存和消息队列

### macOS 安装依赖

```bash
# 使用Homebrew安装
brew install mongodb-community redis node

# 启动MongoDB和Redis
brew services start mongodb-community
brew services start redis
```

### 首次使用

```bash
# 1. 安装后端依赖
cd backend
uv sync

# 2. 安装前端依赖
cd frontend-studio
npm install

# 3. 配置环境变量
cd backend
cp .env.example .env
# 编辑 .env 配置必要的环境变量

# 4. 启动服务
./scripts/start.sh
```

## 故障排查

### 端口被占用

如果端口8000或3000被占用：

```bash
# 查看占用端口的进程
lsof -i :8000
lsof -i :3000

# 终止占用进程
kill -9 <PID>
```

### 服务启动失败

1. 检查日志文件：`logs/*.log`
2. 确认依赖服务已启动：`./scripts/status.sh`
3. 手动启动服务查看错误信息

### 清理残留进程

如果停止脚本无法完全清理进程：

```bash
# 清理Python进程
pkill -f "uvicorn app.main:app"
pkill -f "celery -A app.celery_app"

# 清理Node进程
pkill -f "vite --port=3000"
```

## 注意事项

1. **PID文件**: 脚本使用 `.pids/` 目录存储进程ID，不要手动删除
2. **日志轮转**: 脚本不会自动轮转日志，需要手动清理或配置logrotate
3. **生产环境**: 这些脚本适用于开发环境，生产环境建议使用systemd或supervisor
4. **热重载**: 后端和前端都启用了热重载，修改代码会自动重启
