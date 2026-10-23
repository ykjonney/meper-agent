# Agent Flow 部署指南

## 三种部署方式

| 模式 | 何时选 | DB 怎么跑 | 数据位置 |
|---|---|---|---|
| **A. 纯手动** | 服务器不想装 Docker | 自己装 MongoDB/Redis/Qdrant（apt/brew/Docker run 都行） | 你定 |
| **B. 混合** | app 走系统服务，DB 走容器 | `infra/docker-compose.yml` 起 Mongo/Redis/Qdrant 容器 | `$AF_DATA_DIR` |
| **C. 全 Docker** | 想完全容器化 | compose 内含 | `$AF_DATA_DIR` |

> **B ↔ C 切换零迁移**：`$AF_DATA_DIR` 是 B/C 共用的数据根目录（默认 `./data`），B 写进 `data/{mongodb,redis,qdrant}` 与 C 完全相同。
> **A → B/C**：需 `mongodump` / `mongorestore` + Qdrant snapshot 导入（不在本指南范围）。

## 前提条件

| 项 | 要求 | 模式 |
|---|---|---|
| 操作系统 | Linux x86_64（包文件名标明平台，请对应） | A/B/C |
| Python | **3.12**（应用为 cp3.12 二进制，其他版本无法加载） | A/B |
| Docker | （B 起 DB 容器 / C 起全部容器） | B/C |
| MongoDB 7.0+ / Redis 7+ / Qdrant 1.10+ | A 自备；B/C 在 compose 内 | A |

> 不想安装 Python 3.12？向供应商索取「整合版」安装包（已内置运行环境，解压即用）。
> Qdrant 没有原生包：模式 A 可装官方二进制 tarball，或 `docker run qdrant/qdrant` 单起（不算"装 Docker"）。

---

## A. 纯手动

### 1. 解压
```bash
unzip agent-flow-<版本>-linux-x86_64.zip && cd agent-flow
```

### 2. 初始化环境
**通常跳过此步**——`./agent-flow start` 会自动检测并初始化环境（首次几分钟）。

仅内网离线服务器需要手动初始化：向供应商索取离线依赖包，解压后执行 `./agent-flow setup --offline <依赖包目录>`。

### 3. 配置数据库
打开 `etc/agent-flow.env`（解压即有，默认已带内置数据库凭据，连本机 `127.0.0.1`），按需修改：
- `MONGODB_URI` / `REDIS_URL` / `CELERY_BROKER_URL` / `CELERY_RESULT_BACKEND` / `QDRANT_URL`
- 外接**无认证** Mongo：把 `MONGODB_URI` 里的 `agentflow:changeme@` 去掉

数据迁移：`data/` 布局与原项目一致（`data/{mongodb,redis,qdrant,workspaces,...}`；
另有 `caddy/`、`caddy-config/` 为反向代理运行时状态，随目录一起迁移即可），
换机/升级拷贝整个 `data/` 目录即可。

安全密钥（`JWT_SECRET_KEY` / `MODEL_ENCRYPTION_KEY`）已内置默认值，一般无需修改。
注意：`MODEL_ENCRYPTION_KEY` 一旦有业务在用就**不要再改**，否则已保存的模型 API Key 无法解密。

### 4. 启动与激活
```bash
./agent-flow start                 # 浏览器 http://<服务器IP>:8000/ 出现激活向导
./agent-flow fingerprint           # 指纹发给供应商
./agent-flow license install <供应商回发的 license.key>
./agent-flow create-admin --username admin --password '强密码' --email a@b.c
```

DB 连不通时 uvicorn 会直接报错退出（不会"贴心"重试）。

---

## B. 混合（app 走系统服务 + DB 走 Docker）

前置：Docker（仅用于起 DB 容器）。

### 1–2. 解压 + 初始化环境
同 A 的 1–2 步。

### 3. 配置（可选）
`etc/agent-flow.env` 里可改数据根目录（留空则用默认 `$BASE/data`）、
内置数据库密码（默认 `changeme`，改后需同步 `MONGODB_URI`）：
```
# 数据根目录：混合模式 B 与全 Docker 模式 C 共用；B/C 切换零迁移
AF_DATA_DIR=
```

### 4. 启动（DB 容器 + app 进程一条命令）
```bash
./agent-flow start --with-infra
```

- 三个 DB 容器起来后，`--wait` 会等 Mongo/Redis 通过 healthcheck
- 数据落在 `$AF_DATA_DIR/{mongodb,redis,qdrant}`，默认 `$BASE/data`
- backend/worker/beat 走系统进程（pid 在 `run/`、日志在 `logs/`）

### 5. 激活 + 创建管理员
同 A 的 4 步。

---

## C. 全 Docker

前置：Docker。

### 架构
启动后跑 5 个容器 + 3 个数据卷：

| 容器 | 镜像 | 作用 |
|---|---|---|
| `agent-flow-caddy` | caddy:2-alpine | 对外 :80/:443；serve 前端 + 反代 `/api/*` → app |
| `agent-flow-app` | agent-flow-app:\<ver\> | uvicorn（API + WebSocket） |
| `agent-flow-worker` | agent-flow-app:\<ver\> | celery worker（异步任务） |
| `agent-flow-beat` | agent-flow-app:\<ver\> | celery beat（调度） |
| `agent-flow-mongodb` | mongo:7.0 | 主数据 |
| `agent-flow-redis` | redis:7-alpine | 缓存 + Celery broker |
| `agent-flow-qdrant` | qdrant/qdrant:v1.13.2 | 向量知识库 |

> `app` / `worker` / `beat` 共享同一镜像（首次启动自动构建），仅 `command:` 不同。

### 1. 启动（推荐，一条命令）

```bash
./agent-flow start --docker
```

自动完成：构建应用镜像（首次约 2-3 分钟，之后有缓存）→ 连接串适配容器模式
（`127.0.0.1` → 容器服务名 + 补内置数据库默认凭据）→ 启动全部容器。
内置数据库默认密码 `changeme`（在 `etc/agent-flow.env` 改，需同步 `MONGODB_URI`）。

如需使用外部数据库（非内置容器），先手动修改 `etc/agent-flow.env` 连接串再重新启动。

> **直接用 docker compose 启动**（跳过 ./agent-flow）：
> 需先 `docker build -f Dockerfile -t agent-flow-app:<版本> .` 手动构建镜像，
> 并在 `etc/agent-flow.env` 中将数据库主机名改为容器服务名
> （`mongodb` / `redis` / `qdrant`），确保 `MONGO_ROOT_PASSWORD` 已设置；
> 启动命令带 `--env-file`：`docker compose --env-file etc/agent-flow.env up -d`
> （compose 的 `${...}` 变量插值只认 --env-file/shell，不读 env_file 段）。

数据落在 `$AF_DATA_DIR/{mongodb,redis,qdrant}`，默认 `./data`。
caddy 把前端和 API 收口在 :80（标准 HTTP 端口）。

> 容器以 root 运行，`data/` 下文件属主为 root——之后若切回手动部署模式，
> 需 `chown -R <运行用户> data/`，否则应用无权写入。

### 2. 激活
浏览器打开 `http://<服务器IP>/`，按向导走（网页向导激活亦可，授权文件会写回宿主 `etc/jasper.identity`）：

```bash
# 宿主机执行（--docker 为容器部署模式的统一命令入口）
./agent-flow fingerprint --docker                     # 指纹（MAC 地址）发给供应商
./agent-flow license install <jasper.identity> --docker   # 收到回发的授权文件后激活
```

未激活时 worker 容器会自动退出并由 Docker 反复拉起（属正常）；
激活成功后下一次自动拉起即恢复工作，无需手动操作。

### 3. 创建管理员
```bash
./agent-flow create-admin --docker --username admin --password '强密码' --email a@b.c
```

### 常用命令
```bash
docker compose -f docker-compose.yml ps                # 5 个服务状态
docker compose -f docker-compose.yml logs -f app      # app 日志
docker compose -f docker-compose.yml logs -f worker    # celery worker
docker compose -f docker-compose.yml logs -f beat      # 调度
docker compose -f docker-compose.yml logs -f caddy     # 反代
docker compose -f docker-compose.yml restart caddy     # 只重启 caddy（如改了 Caddyfile）
docker compose -f docker-compose.yml down              # 全停（数据保留；-v 才删）
```

### 升级
```bash
# 本地构建新镜像
docker build -f Dockerfile -t agent-flow-app:<新版本> .
# 重启（无 -d 数据卷销毁）
docker compose -f docker-compose.yml up -d
```

> 数据和 license 文件都在 `./data` 和 `./etc/license.key`，升级不动它们。

### 改前端只动 Caddyfile
```bash
# 编辑 Caddyfile 后让 caddy 重新加载
docker compose -f docker-compose.yml restart caddy
```

---

## 日常运维

| 模式 | 状态 | 日志 | 启停 | 开机自启 |
|---|---|---|---|---|
| A | `agent-flow status` | `agent-flow logs backend` | `agent-flow start/stop/restart` | `sudo agent-flow install-service` |
| B | `agent-flow status` | `agent-flow logs [backend\|worker\|beat\|infra]` | `agent-flow start/stop/restart [--with-infra]` | `sudo agent-flow install-service` |
| C | `docker compose -f docker-compose.yml ps` | `docker compose logs -f [app\|mongodb\|redis\|qdrant]` | `docker compose up/down` | 由宿主 init（systemd）管 |

## 升级

获取新版本 zip，先停服，用新文件夹的 `app/ web/ infra/ requirements.lock.txt agent-flow` 替换旧的（**`etc/`（配置与授权）和 `data/`（业务数据）保留**），依赖有变化时再跑一次 `./agent-flow setup`，然后 start。授权不受升级影响。

或者用升级命令：
```bash
./agent-flow upgrade <新版 agent-flow-x.x.x.zip>
```

## 常见问题

| 现象 | 处理 |
|---|---|
| 提示"未找到 Python 3.12" | 安装 Python 3.12（apt/yum install python3.12 python3.12-venv）；或索取 `--with-runtime` 版本包 |
| 启动后浏览器显示"系统激活" | 正常——完成激活流程即可 |
| `license install` 报 `LIC_E_FINGERPRINT` | license 与本机不匹配：重新 `fingerprint` 发给供应商重签 |
| `LIC_E_EXPIRED` | 授权到期：续费后覆盖 install 新 key |
| setup 报某依赖装不上 | 先确认 `python3 --version` 是 3.12；网络受限改用 `setup --offline` |
| B 模式报 `MONGO_ROOT_PASSWORD 未设置` | 用 `./agent-flow start --with-infra`（启动器自动注入；不要手动 `docker compose -f infra/... up`） |
| B 改了 env 内置库密码但连不上 | MongoDB 初始化密码仅首次生效；确需更换：停服 → 删 `data/mongodb/`（**先备份**）→ `start --with-infra` |
| B → C 切换后数据还在吗 | 在的。B/C 共用 `$AF_DATA_DIR`，`agent-flow stop` 不删数据，`docker compose down` 不删数据（除非加 `-v`） |
| C 模式启动后 `Connection refused` | 检查 `AF_DATA_DIR` 与 `data/mongodb` 是否存在；首次启动 MongoDB 初始化要 10-30s |
| 改了 env 里 `AF_DATA_DIR` 但 `workspaces` 等还在原位 | 旧版 bug；当前版本 `__AF_DATA_DIR__` 占位符在 `load_env` 运行时按 `AF_DATA_DIR` 替换——**改完 `start` 即可生效**。若升级自旧版，删 `etc/agent-flow.env` 重新生成 |
