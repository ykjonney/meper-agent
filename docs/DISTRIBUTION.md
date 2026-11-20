# 闭源商业分发手册（v2 极简形态）

一个文件夹 + 一个启动命令。签发工具独立、与主项目零耦合。

## 一、交付物（客户拿到的全部）

```
agent-flow/                  ← zip 解压即得
├── agent-flow               ← 唯一执行文件
├── app/                     ← .so 编译产物（无 .py 业务源码）
├── runtime/                 ← 捆绑 Python + 依赖（客户免装 Python）
├── web/                     ← 前端产物（backend 直接托管，无需 Caddy/nginx）
├── infra/                   ← 可选内置数据库（--with-infra 时用）
├── etc/                     ← 配置 + jasper.identity（激活后生成）
├── data/  logs/  run/       ← 运行时目录
├── LICENSE  NOTICE
```

**零依赖**：不需要 root、systemd、Docker、Python——数据库连接你的已有实例。
**可选**：`--with-infra` 用 Docker 起内置 MongoDB/Redis/Qdrant；`install-service` 注册 systemd 开机自启。

## 二、客户使用（三条命令）

```bash
./agent-flow start            # 首次自动生成配置；未激活时只起 backend 显示激活向导
./agent-flow fingerprint      # 取指纹发给供应商
./agent-flow license install <供应商发回的 jasper.identity>   # 激活 + 自动补起 worker/beat

./agent-flow status           # 进程 + license 状态
./agent-flow logs backend     # 日志（backend|worker|beat|infra）
./agent-flow stop / restart
./agent-flow create-admin --username admin --password '<密码>' --email a@b.c
```

## 三、授权签发（公司 IdentityLoader 体系）

license 为公司统一签发（`jasper.identity`，RSA-SHA256 + AES，绑 MAC 地址 + 到期日），
本仓库不再包含签发工具：

1. 客户侧：`./agent-flow fingerprint`（或 `--docker`）取得本机 MAC（`XX-XX-...` 格式）发给商务
2. 商务走公司签发系统出 `jasper.identity` 回传
3. 客户执行 `./agent-flow license install <jasper.identity>` 激活（热生效，无需重启）

验签公钥/AES 密钥已硬编码在 `backend/app/core/license.py`（兼容公司 Java IdentityLoader）。

## 四、发布构建（一条命令，交互选择平台）

```bash
# dev 构建（license 不强制，内部/测试用——最常用）
make build-release VERSION=1.0.6

# 正式构建（license 强制，交付客户）
make build-release VERSION=1.0.6 RELEASE=1
```

运行后自动检测环境并让你选择：

```
 请选择构建方式：
   [1] 本机构建      产物平台: darwin-arm64  ⚠ 本机平台包不能给 Linux 服务器客户使用（仅本机测试）
   [2] Docker 构建   可选平台: linux/amd64（客户服务器主流，默认）/ linux/arm64
```

- **本机构建**：产物平台 = 本机平台（快速测试用；Linux x86_64 机器上即正式交付包）
- **Docker 构建**：跨平台产物（mac 上也能产 Linux 包；Apple Silicon 编 amd64 走 Rosetta 较慢）
- 非交互（CI）：`make build-release-local` / `make build-release-docker PLATFORM=linux/arm64`
- 全流程一条龙：前端 build + Cython 编译 + runtime 捆绑 + 组装 + zip（`release/build_package.sh`）
- 产物命名自带平台：`agent-flow-1.0.0-linux-x86_64.zip`，发错平台一眼可见

构建要点：**license 强制（LICENSE_ENFORCED=True）在编译期编入 .so**（客户改 env 无法降级）；
`app/cli` 与 `_cycompat.py` 保留 .py（runpy/补丁先行限制）；前端 dist 无 sourcemap。
dev/正式唯一区别就是该布尔值；构建容器 npm 走 npmmirror 镜像（官方源经代理常 ECONNRESET）。
产物 sha256 校验文件随 zip 生成；验证包内强制标志：解压后在 linux 容器 import
`app.core.build_flags` 看 `LICENSE_ENFORCED`。

**完整性链（安全报告修复 1+2）**：构建期对 `license.so`（strip 后）计算 sha256，连同
强制真值一起注入三个独立校验点（`license_mw` / `celery_app` / workflow `engine`）的
占位符（缺占位符即构建中止）。校验点的强制判定**不经任何 import**——meta_path 拦截
`build_flags` 翻转总开关只骗得了 license 模块自身，三个校验点靠内联真值识别矛盾并
fail-closed（403 `LIC_E_INTEGRITY` / worker exit 78）；文件定位以校验点自身 `__file__`
为锚点物理推算（不走 `find_spec`，防 `sys.modules` 假模块伪造 origin），并核对已加载
模块的 `__spec__.origin` 与物理文件一致。

## 五、到期与安全行为

- 到期前 30 天 UI 警告条 / 7 天 `X-License-Expiring` 响应头
- **到期即停**：业务 API 403、worker 停拉；数据导出保留；粘贴新 key 热恢复
- 防御层级：RSA-SHA256 防伪造（私钥只在签发端）→ MAC 绑机+到期防滥用（商业）→ Cython .so 抬高 patch 成本 → 完整性链防校验器替换 → EULA 法律兜底

## 五A、威胁模型边界与剩余风险（诚实声明）

自托管交付形态下，客户拥有宿主机 root——授权机制的定位是**抬高随手克隆的成本并留下
审计痕迹**，不是对抗决心伪造的专家。当前边界：

- **已封堵**（2026-10 安全报告三条路径）：模块整体替换（完整性链哈希 + 矛盾检测）、
  拦截 build_flags 翻转总开关（强制真值内联进校验点，不经 import）、`AGENT_FLOW_MAC`
  注入链退役（物理网卡实测 + 宿主 /sys 只读挂载，两部署形态同源同值；手动覆盖值
  与实测不一致留 `license_mac_env_mismatch` 审计事件）。
- **残余面 1**：校验比对的是磁盘文件哈希，无法从纯 Python 层证明"内存中运行的模块
  对象"就是该文件编译的——攻击者理论上可伪造一个 `__spec__.origin` 指向真 .so 的
  假模块。但该假模块还须让 `evaluate_license` 返回 enforced=True/ok=True 且通过
  三处独立校验，成本已远高于报告原始的 15 行。
- **残余面 2**（v2 已收窄）：绑机指纹 = 物理网卡实测——手动部署直读宿主
  `/sys/class/net`，Docker 部署经 compose 只读挂载宿主 /sys 读同一目录（整挂 /sys——
  device 判据是相对链接、指向 /sys/devices；与启动方式无关，手动
  `docker compose up` 同样生效），按"device 链接 + carrier + PCI 槽位序"
  选物理网卡；`AGENT_FLOW_MAC` 注入已退役为手动覆盖项。
  剩余边界 = 宿主 root 仍可 `ip link set <iface> address XX` 改系统级
  标识——离线形态原理上限，与手动部署一致；覆盖值与实测不一致会留下
  `license_mac_env_mismatch` 审计事件。
- **信息面**：生产构建（`APP_ENV=production`）已关闭 `/docs` `/redoc` `/openapi.json`
  （main.py 按 env 条件关闭 + license 中间件白名单不放行双保险）；异常统一错误信封，
  traceback 不回传客户端（仅入服务端日志）。

## 六、本地真实场景测试（拼装交付包形态，客户视角全流程）

```bash
cd backend
scripts/dev_package_local.sh build     # 拼装 /tmp/agent-flow-local（= 客户拿到的包）

cd /tmp/agent-flow-local
./agent-flow start                     # dev 构建无需激活直接可用；正式构建出现激活向导
./agent-flow fingerprint               # MAC 指纹
./agent-flow license install <公司签发的 jasper.identity>   # 激活 + 自动补起 worker/beat
./agent-flow create-admin --docker --username admin --password '<密码>' --email a@b.c
./agent-flow start --docker            # Docker 模式全流程（80 端口，caddy 收口）
```

测试完 `scripts/dev_package_local.sh clean`。独立数据库 agent_flow_e2e，不污染开发库。

## 七、私有仓库镜像分发（Harbor）

### 分支驱动的构建模型（CI 自动）

| 分支动作 | 产物 | tag |
|---|---|---|
| push `dev` | 开发三镜像 `agent-flow-{backend,caddy,sandbox}`（源码 .py，license 不强制） | `dev.<时间戳>`（快照）+ `dev`（指针） |
| 合并 `main`（先 bump 根目录 `VERSION` 文件） | 编译镜像 `agent-flow-app`（.so + license 强制） | `<VERSION>.<时间戳>` + `<VERSION>` + `latest` |

### tag 语义

- **快照 tag**（`1.0.8.20261029-1543`）：一次构建一份，永不覆盖——复现问题/回滚/审计用；Harbor 可对该 tag 模式设 immutable
- **指针 tag**（`dev` / `latest` / `1.0.8`）：始终指向该线最新构建——**环境文件写指针即"永远最新"，更新只需 `docker compose pull && up -d`，零配置改动**
- 回滚 = 部署时指定历史快照 tag

### 手动构建/推送（与 CI 同一套脚本）

```bash
make build-image-deploy VERSION=1.0.8-dev REGISTRY=harbor.corp/af PUSH=1   # 开发三镜像
make build-image-app    VERSION=1.0.8 REGISTRY=harbor.corp/af PUSH=1 LATEST=1  # 编译镜像（需先 build-release）
# 认证：已 docker login 免密，或传 DOCKER_USER/DOCKER_PASS
```

### 部署侧消费

- **测试环境**：`deploy/.env` 写 `BACKEND_IMAGE=harbor.../agent-flow-backend:dev` 等，更新 = `docker compose pull && up -d`
- **生产**：deploy.yml 手动触发，`image_tag` 填指针（追新）或快照（锁定/回滚）
- **客户（能通 Harbor）**：交付包 `etc/agent-flow.env` 设 `APP_IMAGE=harbor.../agent-flow-app:1.0.8`，
  `./agent-flow start --docker` 自动 pull，无需 zip 与本地构建；升级 = 改一行 tag 后 `restart --docker`
- **客户（离线）**：维持 zip / 镜像 tar + `docker load`

