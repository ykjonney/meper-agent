# Agent Flow License 体系完整报告

> 版本：随 1.0.2 交付包体系定稿。面向：研发、交付、销售、售后。

## 一、一句话概述

客户拿到的是**不含源码的二进制交付包**（.so），必须用厂商签发的 `license.key` 激活才能使用；
授权与**机器绑定**、可设**有效期**；升级新版本**无需重新激活**；支持订阅（到期即停）与买断（永久）两种商业模式。

## 二、设计目标

| 目标 | 实现结果 |
|---|---|
| 源码不泄露 | 后端 412 个模块 Cython 编译为 .so，包内无业务 .py |
| 防一份拷贝多客户用 | license 绑机器指纹（machine-id + 磁盘序列号），换机失效 |
| 订阅制收费 | expires_at 到期即停（API 403、worker 停拉），保留数据导出 |
| 升级零感知 | 授权凭证在 etc/，升级流程保留；公钥不变则旧 key 永续有效 |
| 客户零网络依赖 | 纯离线校验（本地验签），不需要连厂商服务器 |
| 开箱即用 | 未激活降级模式：后端可启动、显示激活向导；激活后热放行 |

## 三、技术栈

| 技术 | 用在哪 |
|---|---|
| **Ed25519**（cryptography 库） | license 签名/验签——私钥签名、公钥验证，数学上不可伪造 |
| **Cython 3 + gcc** | 源码 → .so 二进制；公钥、强制开关作为常量编译进去，客户不可改 |
| SHA-256 | 机器指纹哈希；license 内容摘要 |
| HMAC | 防时钟回拨状态文件（license.state）的完整性保护 |
| SQLite | 厂商签发台账（licensegen 内置） |
| bash | 交付包启动器（agent-flow 一体化命令） |

## 四、核心概念（三方两物）

```
【厂商内网】                      【客户服务器】
签发机 ~/.af-keys/                agent-flow 交付包/
  ├─ private.pem（口令加密私钥）     ├─ app/*.so（内嵌公钥+强制开关）
  ├─ public.pem（公钥）             ├─ etc/license.key（激活凭证）
  └─ ledger.sqlite（签发台账）       └─ etc/license.state（防回拨状态）

客户回传：40 位机器指纹（向导页展示 / fingerprint 命令）
```

- **私钥**：只在厂商签发机，口令加密，永不外发
- **公钥**：编译进每个交付包的 .so，只能验签不能签发
- **指纹**：sha256(/etc/machine-id + 根磁盘序列号)，代表"这台机器"；同一台机器手动/Docker 两种部署形态指纹一致（Docker 由启动器注入宿主磁盘序列号 + 挂载宿主 machine-id）
- **license.key**：一行文本 `base64(payload).base64(签名)`；payload 含授权方/版本/指纹/签发时间/到期时间（买断则无到期）

## 五、实现架构（客户端校验体系）

### 5.1 校验流程（每次 API 请求，60 秒缓存）

```
请求 → LicenseMiddleware（只管 /api/ /ws/ 业务面）
  → evaluate_license()
      ① is_enforced()     编译期固化（.so 常量，env 只能加强不能削弱）
      ② 读 license.key    → base64 解码
      ③ Ed25519 验签      （公钥在 .so 内）
      ④ 指纹比对          payload.fingerprint == 本机指纹？
      ⑤ 时钟三重校验      issued_at 底线 + state 高水位(HMAC) + uptime 单调
      ⑥ 有效期            now ≤ expires_at
  → 全过放行；任一失败 403 + 错误码（前端映射为中文提示）
```

### 5.2 分散校验点（加固：patch 单点不够）

| 校验点 | 位置 |
|---|---|
| 主闸门 | API middleware |
| Worker 闸门 | Celery 启动信号（无 license 拒绝启动，exit 78）+ 每 task 前置检查 |
| 引擎闸门 | 工作流引擎执行入口独立复核 |
| 周期复验 | backend 每 30 分钟、worker 每 1 小时（处理运行中途到期） |
| 公钥双副本 | .so 内两处冗余互验，篡改任一即 fail-closed |
| **完整性链** | 见 5.6——license 模块自身被替换即自曝（防 meta_path/模块替换攻击） |

### 5.3 未激活降级模式

后端**正常启动**但只放行：激活向导页、指纹/状态/激活 API、静态资源、健康检查；业务 API 全部 403。
激活成功（网页或 CLI）→ **热放行**，无需重启。启动器附带 watcher：网页激活（HTTP，启动器视野外）后自动补起 worker/beat。

### 5.4 到期策略：提前警告、到期即停

| 时间 | 行为 |
|---|---|
| T-30 天 | UI 顶部警告条 |
| T-7 天 | API 响应头 X-License-Expiring |
| T+0 | 业务 API 全 403（LIC_E_EXPIRED）、worker 停拉任务；**数据导出保留**（防挟持数据纠纷） |
| 装入新 key | 热恢复 |

### 5.5 关键防护

- **防时钟回拨**（无限续期）：license.state 记录"见过的最新时刻"（HMAC 防篡改）+ /proc/uptime 单调性 + 签名内 issued_at 底线
- **防 env 绕过**：强制开关 = 编译期常量 OR env（单向，env 关不掉）
- **防换公钥**：公钥双副本互验，替换不一致即拒
- **防模块替换**：完整性链（5.6）
- **错误码化**：二进制内零明文错误文案（不给逆向者路标），前端映射中文

### 5.6 完整性链（防校验模块整体替换）

**威胁**：CPython 导入机制不校验模块文件真实性——校验逻辑若单点收敛于 `app.core.license`，攻击者用 meta_path 导入拦截器（如 sitecustomize.py）整体替换该模块即可绕过全部授权（安全评估报告攻击④）。

**机制**（构建期两段式编译，`backend/scripts/build_compiled.py`）：

```
第一段：只编 app/core/license.py → 删源/清中间/strip 定稿 → 算产物 sha256
   ↓ 占位符注入（__LICENSE_SO_SHA256__ → 真实哈希，写进 staging 源码）
第二段：编译其余全部模块
```

3 个校验点（`license_mw.py` / `celery_app.py` / `engine.py`）各自**独立实现**完整性自检
（不共享 verify 函数、常量折叠进各自 .so），运行期校验：

- 强制判定用 `build_flags.LICENSE_ENFORCED`（独立模块）——防被替换的 license 模块谎报"未强制"
- license 模块文件必须是 `.so`/`.pyc` 编译形态（防替换回 .py 源码）
- 文件 sha256 ≠ 构建期嵌入常量 → fail-closed：middleware 403 `LIC_E_INTEGRITY`（license 端点仍可达，激活向导是恢复通道）/ worker exit 78 / 任务拒绝

**攻击成本**：替换 license 模块 → 必须同时定位并替换 license.so + build_flags.so + 3 个调用方 .so 中的校验逻辑（Cython 产物、无源码对齐、docstring 已剥离）。

**RELEASE 篡改验证步骤**（每次正式构建后建议执行）：

```bash
unzip dist/agent-flow-<ver>-<plat>.zip && cd agent-flow-<ver>-*/
# 篡改 license 模块一个字节
printf '\x00' | dd of=app/app/core/license.*.so bs=1 seek=100 conv=notrunc
./agent-flow start
# 预期：业务 API 全部 403 (LIC_E_INTEGRITY)；./agent-flow license status 仍可达
#       worker 启动即 exit 78；还原 zip 重新解压即恢复
```

**防线边界**：完整性链防"模块替换"，不防"重打包"（攻击者可重排产物后自算哈希）；
授权数据伪造仍由 RSA 体制兜底（无供应商私钥不可行）。

## 六、生命周期全景

```
厂商初始化(一次)     构建发版            客户部署激活          运行              变更
─────────────    ─────────────     ──────────────     ──────────     ──────────
licensegen        build-release      解压→start          正常使用        续费:重签覆盖
keygen 生成密钥对  (公钥+强制编译进so)  向导取指纹→回传      (纯离线校验)    换机:新指纹重签
(+备份离线介质)    产出 zip 包         issue→install       到期前警告      到期:停服/导出
                                    create-admin        到期即停        升级:无需动license
```

## 七、厂商操作手册

### 7.1 初始化（一次性）

```bash
cd licensegen && pip3 install cryptography
python3 licensegen.py keygen --keys ~/.af-keys        # 设强口令（存密码管理器）
```
**三条铁律**：私钥目录永不外发；备份到离线介质（连同口令）；永远不要 keygen --force
（换密钥对 = 所有已发授权全部失效，需按台账逐个重签）。

### 7.2 发版

```bash
make build-release VERSION=1.0.0 KEYS_DIR=~/.af-keys
# 交互选择：本机构建（快速测试）/ Docker 构建（linux-amd64/arm64 正式交付包）
# 产物：dist/agent-flow-1.0.0-linux-x86_64.zip（约 25MB，含部署指南）
```
不传 KEYS_DIR = dev 构建（license 不强制，仅内部测试用，**不可交付**）。

### 7.3 签发

```bash
LICENSEGEN_PASSPHRASE=口令 python3 licensegen.py issue \
  --keys ~/.af-keys --licensee "客户A" \
  --fingerprint <客户回传的40位指纹> \
  --expires 2027-10-09 --out 客户A.key      # 买断改 --perpetual
```

### 7.4 台账管理

```bash
python3 licensegen.py list --keys ~/.af-keys                    # 全部签发记录
python3 licensegen.py list --keys ~/.af-keys --expiring-within 60  # 销售跟进清单
python3 licensegen.py inspect --keys ~/.af-keys 客户A.key        # 查验
```

## 八、客户使用（部署指南摘要）

### 8.1 首次部署

```bash
unzip agent-flow-1.0.0-linux-x86_64.zip && cd agent-flow-1.0.0-*/
./agent-flow start              # 环境自动初始化；浏览器 http://IP/ 出激活向导
./agent-flow fingerprint        # 复制指纹发给供应商（或直接抄向导页面）
# 收到 license.key 后，两种激活方式任选：
#   网页：向导粘贴 key 内容 → 激活（watcher 自动补起后台任务进程）
#   命令：./agent-flow license install license.key
./agent-flow create-admin --username admin --password '强密码' --email a@b.c
```

三种部署形态（同一套命令，加参数切换）：
- 默认：手动进程（自备或自动安装 Python 3.12 + venv）
- `start --with-infra`：数据库也用内置 Docker 容器
- `start --docker`：全容器（caddy 80/443 + app/worker/beat + 数据库）

### 8.2 日常运维

```bash
./agent-flow status / logs backend / restart / stop
sudo ./agent-flow install-service     # 可选：systemd 开机自启
```

### 8.3 续签（客户视角）

收到新 license.key → `./agent-flow license install 新.key`（或网页粘贴）→ 热生效，数据不动。

### 8.4 升级（客户视角）

```bash
./agent-flow upgrade agent-flow-1.1.0-linux-x86_64.zip
# etc/(授权/配置) data/(数据) .venv 全保留 → start 即用，无需重新激活
```

### 8.5 错误码对照（客户排障）

| 码 | 含义 | 处理 |
|---|---|---|
| LIC_E_NOT_ACTIVATED | 未激活 | 完成激活流程 |
| LIC_E_FINGERPRINT | 与本机不匹配 | 重新 fingerprint 发给供应商重签 |
| LIC_E_SIGNATURE | 授权文件无效 | 确认从官方渠道获取 |
| LIC_E_EXPIRED | 已到期 | 联系供应商续费，装入新 key |
| LIC_E_CLOCK | 系统时钟异常 | 校准服务器时间 |
| LIC_E_INTEGRITY | 程序文件被篡改 | 重新下载官方安装包（数据不受影响） |

## 九、安全边界（诚实评估）

| 防线 | 强度 |
|---|---|
| Ed25519 伪造 | 数学上不可（除非私钥泄露） |
| 绑机+到期防滥用 | 商业层面防死（换机/到期必然失效） |
| Cython .so 防逆向 | 大幅抬高成本（远难于 .pyc），决心足够的专业者仍可 patch |
| 加固层 | 把 patch 成本从小时级抬到周级 |
| 法律 | EULA（根目录 LICENSE）+ 侵犯著作权追责兜底 |

现实定位：B2B 私有化交付无盗版分发市场，真实威胁是客户滥用（多装/到期不续）——本体系已防死；
破解组织级攻击为行业共性无解，靠成本+法律威慑。

## 十、代码与文件索引

| 文件 | 职责 |
|---|---|
| backend/app/core/license.py | 校验核心（payload/验签/指纹/防回拨/缓存/包根锚定） |
| backend/app/core/build_flags.py | 编译期注入标志（构建时替换） |
| backend/app/api/middleware/license_mw.py | API 闸门（降级/到期/导出豁免/头标记） |
| backend/app/api/v1/system.py | 激活向导端点（status/install/request） |
| backend/app/_cycompat.py | Cython/pydantic 兼容补丁（常驻源码） |
| backend/tests/core/test_license.py | 23 个全场景测试 |
| backend/tests/core/test_license_integrity.py | 完整性链测试（3 校验点语义 + 占位符注入 + 403 集成） |
| licensegen/ | 独立签发工具（keygen/issue/inspect/list + 台账） |
| release/agent-flow | 一体化启动器（start/setup/upgrade/--docker/watcher） |
| release/build_package.sh | 全流程构建（前端+so+依赖锁+组装+zip） |
| backend/scripts/build_compiled.py | Cython 编译核心 |
| release/DEPLOY.md | 客户部署指南（随包分发） |
