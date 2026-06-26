# 阿里云 Docker 部署配置指南

本文档介绍如何配置 GitHub Actions 自动部署到阿里云 ECS 服务器。

## 📋 前置条件

- 阿里云 ECS 服务器（已安装 Docker 和 Docker Compose）
- 阿里云容器镜像服务（ACR）
- GitHub 仓库

## 1️⃣ 配置阿里云容器镜像服务（ACR）

### 1.1 创建命名空间

1. 登录 [阿里云容器镜像服务控制台](https://cr.console.aliyun.com/)
2. 选择地域（如：华东1-杭州）
3. 点击「命名空间」→「创建命名空间」
4. 输入命名空间名称：`agent-flow`

### 1.2 创建镜像仓库

为每个服务创建镜像仓库：

**后端镜像：**
- 仓库名称：`agent-flow-backend`
- 类型：私有
- 地域：与命名空间相同

**Caddy镜像（包含前端）：**
- 仓库名称：`agent-flow-caddy`

**Sandbox镜像：**
- 仓库名称：`agent-flow-sandbox`

### 1.3 获取 ACR 凭证

1. 在 ACR 控制台，点击右上角「访问凭证」
2. 创建固定密码（用于 Docker 登录）
3. 记下：
   - **Registry URL**: `crpi-keb4al1ccypg3agi.cn-hangzhou.personal.cr.aliyuncs.com`（个人版实例）
   - **用户名**: 阿里云账号（如：`15656207716`）
   - **密码**: 刚才设置的固定密码

登录命令示例：
```bash
docker login --username=15656207716 crpi-keb4al1ccypg3agi.cn-hangzhou.personal.cr.aliyuncs.com
```

## 2️⃣ 配置阿里云 ECS 服务器

### 2.1 安装 Docker 和 Docker Compose

SSH 登录到 ECS 服务器：

```bash
# 安装 Docker
curl -fsSL https://get.docker.com | sh

# 启动 Docker
sudo systemctl start docker
sudo systemctl enable docker

# 将当前用户添加到 docker 组
sudo usermod -aG docker $USER

# 验证 Docker Compose（Docker 安装包已内置）
docker compose version
```

### 2.2 配置服务器目录

```bash
# 创建项目目录
sudo mkdir -p /opt/agent-flow
sudo chown $USER:$USER /opt/agent-flow

# 克隆项目（首次）
cd /opt/agent-flow
git clone https://github.com/YOUR_USERNAME/agent-flow.git .

# 复制环境变量文件
cp deploy/.env.example deploy/.env
# 编辑 .env 文件，配置实际的环境变量
vim deploy/.env
```

### 2.3 配置 SSH 密钥登录

在本地生成 SSH 密钥（如果没有）：

```bash
ssh-keygen -t ed25519 -C "github-actions"
```

将公钥添加到 ECS 服务器的 `~/.ssh/authorized_keys`：

```bash
# 在本地执行
cat ~/.ssh/id_ed25519.pub | ssh root@YOUR_ECS_IP "mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys"
```

测试 SSH 登录：

```bash
ssh -i ~/.ssh/id_ed25519 root@YOUR_ECS_IP
```

## 3️⃣ 配置 GitHub Secrets

在 GitHub 仓库中配置以下 Secrets：

### 3.1 进入设置页面

1. 打开 GitHub 仓库
2. 点击「Settings」→「Secrets and variables」→「Actions」
3. 点击「New repository secret」

### 3.2 添加 Secrets

**阿里云 ACR 配置：**

| Secret 名称 | 值 | 说明 |
|------------|---|------|
| `ALIYUN_REGISTRY` | `crpi-keb4al1ccypg3agi.cn-hangzhou.personal.cr.aliyuncs.com` | ACR Registry URL（个人版实例） |
| `ALIYUN_NAMESPACE` | `agent-flow` | ACR 命名空间 |
| `ALIYUN_ACR_USERNAME` | 你的阿里云账号 | ACR 用户名 |
| `ALIYUN_ACR_PASSWORD` | 你的ACR固定密码 | ACR 密码 |

**阿里云 ECS 配置：**

| Secret 名称 | 值 | 说明 |
|------------|---|------|
| `ALIYUN_ECS_HOST` | `47.xxx.xxx.xxx` | ECS 公网 IP |
| `ALIYUN_ECS_USERNAME` | `root` | SSH 用户名 |
| `ALIYUN_ECS_SSH_KEY` | SSH 私钥内容 | 完整的私钥文件内容 |
| `ALIYUN_ECS_PORT` | `22` | SSH 端口（默认22） |
| `DEPLOY_PATH` | `/opt/agent-flow` | 项目部署路径 |

### 3.3 添加 SSH 私钥

获取私钥内容：

```bash
cat ~/.ssh/id_ed25519
```

复制完整内容（包括 `-----BEGIN OPENSSH PRIVATE KEY-----` 和 `-----END OPENSSH PRIVATE KEY-----`），粘贴到 GitHub Secret `ALIYUN_ECS_SSH_KEY`。

## 4️⃣ 配置环境变量

在 ECS 服务器上编辑 `/opt/agent-flow/deploy/.env` 文件：

```bash
# 数据库配置
MONGO_ROOT_USER=agentflow
MONGO_ROOT_PASSWORD=your_strong_password_here
MONGODB_DATA_DIR=/opt/agent-flow/data/mongodb

# Redis配置
REDIS_DATA_DIR=/opt/agent-flow/data/redis

# 工作空间配置
WORKSPACES_HOST_DIR=/opt/agent-flow/data/workspaces
WORKSPACES_CONTAINER_DIR=/data/workspaces

# Skills配置
SKILLS_HOST_DIR=/opt/agent-flow/data/skills
SKILLS_CONTAINER_DIR=/data/skills

# Sandbox配置
SANDBOX_ENABLED=true

# 后端配置
JWT_SECRET_KEY=your_jwt_secret_key_here
MODEL_ENCRYPTION_KEY=your_encryption_key_here

# 管理员账号（首次部署时使用）
ADMIN_USERNAME=admin
ADMIN_PASSWORD=your_admin_password
ADMIN_EMAIL=admin@example.com

# ── Docker 镜像配置（ACR）──────────────────────────────────────────
# 生产环境：指向阿里云 ACR 镜像仓库
BACKEND_IMAGE=crpi-keb4al1ccypg3agi.cn-hangzhou.personal.cr.aliyuncs.com/meper-agent-flow/agent-flow-backend:latest
CADDY_IMAGE=crpi-keb4al1ccypg3agi.cn-hangzhou.personal.cr.aliyuncs.com/meper-agent-flow/agent-flow-caddy:latest
SANDBOX_IMAGE=crpi-keb4al1ccypg3agi.cn-hangzhou.personal.cr.aliyuncs.com/meper-agent-flow/agent-flow-sandbox:latest

# 本地开发：使用默认值（从 Dockerfile 构建）
# BACKEND_IMAGE=deploy-backend
# CADDY_IMAGE=deploy-caddy
# SANDBOX_IMAGE=agent-sandbox:latest
```

## 5️⃣ 首次部署

在 ECS 服务器上执行首次部署：

```bash
cd /opt/agent-flow

# 登录 ACR
docker login --username=15656207716 crpi-keb4al1ccypg3agi.cn-hangzhou.personal.cr.aliyuncs.com

# 拉取镜像
docker compose -f deploy/docker-compose.yml pull

# 启动服务
docker compose -f deploy/docker-compose.yml up -d

# 创建管理员用户
docker compose -f deploy/docker-compose.yml run --rm create-admin

# 查看服务状态
docker compose -f deploy/docker-compose.yml ps
```

## 6️⃣ 自动部署流程

配置完成后，自动部署流程如下：

```
1. 开发者推送代码到 main 分支
   ↓
2. GitHub Actions 触发 CI workflow
   ↓
3. 运行 lint、type check、test
   ↓
4. 构建 Docker 镜像并推送到 ACR
   ↓
5. 触发 Deploy workflow
   ↓
6. SSH 登录 ECS 服务器
   ↓
7. 拉取最新镜像
   ↓
8. 重启服务
   ↓
9. 执行健康检查
   ↓
10. 部署完成 ✅
```

## 7️⃣ 手动部署

如果需要手动部署：

### 方式1：GitHub Actions 手动触发

1. 打开 GitHub 仓库
2. 点击「Actions」→「Deploy to Aliyun」
3. 点击「Run workflow」
4. 选择分支和环境
5. 点击「Run workflow」

### 方式2：SSH 到服务器手动部署

```bash
# SSH 登录服务器
ssh root@YOUR_ECS_IP

# 进入项目目录
cd /opt/agent-flow

# 拉取最新代码
git pull origin main

# 登录 ACR
docker login --username=15656207716 crpi-keb4al1ccypg3agi.cn-hangzhou.personal.cr.aliyuncs.com

# 拉取最新镜像
docker compose -f deploy/docker-compose.yml pull

# 重启服务
docker compose -f deploy/docker-compose.yml down
docker compose -f deploy/docker-compose.yml up -d

# 查看日志
docker compose -f deploy/docker-compose.yml logs -f
```

## 8️⃣ 常见问题

### Q1: SSH 连接失败

检查：
- SSH 私钥是否正确（包括完整的 BEGIN 和 END 行）
- ECS 安全组是否开放了 SSH 端口（22）
- SSH 用户名是否正确（通常是 `root`）

### Q2: Docker 镜像拉取失败

检查：
- ACR 用户名和密码是否正确
- 镜像仓库是否为私有（需要登录）
- 网络是否畅通

### Q3: 服务启动失败

检查：
- `.env` 文件配置是否正确
- 端口是否被占用（80、443、8000）
- 查看日志：`docker compose -f deploy/docker-compose.yml logs backend`

### Q4: 数据库连接失败

检查：
- MongoDB 和 Redis 服务是否正常运行
- 环境变量中的数据库配置是否正确
- 数据目录权限是否正确

## 9️⃣ 监控和日志

### 查看服务状态

```bash
docker compose -f deploy/docker-compose.yml ps
```

### 查看实时日志

```bash
# 查看所有服务日志
docker compose -f deploy/docker-compose.yml logs -f

# 查看特定服务日志
docker compose -f deploy/docker-compose.yml logs -f backend
```

### 备份数据

```bash
# 备份 MongoDB 数据
docker exec deploy-mongodb-1 mongodump --out /data/backup

# 备份到本地
docker cp deploy-mongodb-1:/data/backup ./backup
```

## 🔟 安全建议

1. **定期更新密码**：ACR 密码、数据库密码、JWT Secret
2. **限制访问**：配置 ECS 安全组，只允许必要的端口
3. **启用 HTTPS**：配置 Caddy 自动 HTTPS
4. **定期备份**：备份 MongoDB 数据和配置文件
5. **监控告警**：配置阿里云监控，设置告警规则

## 📞 技术支持

如有问题，请查看：
- GitHub Actions 日志
- ECS 服务器日志
- Docker 容器日志

---

**配置完成后，推送到 main 分支即可自动部署！** 🚀
