# 致开发：Agent Flow 授权强制机制可被绕过 —— 技术报告（含发现过程）

**日期**：2026-10-26
**测试环境**：隔离实验区（独立服务器 + 独立容器），未触碰任何生产系统
**适用版本**：agent-flow-1.0.6-linux-x86_64

---

## 一、结论（TL;DR）

授权强制机制存在**系统性绕过**，已实证 3 条独立路径，其中最省事的一条只需 **15 行 Python / 翻一个布尔值**：

| # | 路径 | 成本 | 结果 |
|---|------|------|------|
| 1 | 复制授权文件 + 伪造机器指纹（注入 `HOST_MAC` 环境变量） | 一行环境变量 | 异机激活成功 |
| 2 | 导入拦截替换 `app.core.license` 模块 | 80 行 / 30 分钟 | 零授权永久激活 |
| 3 | 导入拦截替换 `app.core.build_flags`，翻转 `LICENSE_ENFORCED=False` | **15 行 / 10 分钟** | **零授权激活 + 全局停止强制** |

共同根因：**所有授权相关模块（license、build_flags）都没有完整性保护**——CPython 导入时不校验模块真伪，代码里也没有任何一处对模块文件做哈希/签名核对。

---

## 二、"总开关"是怎么被发现的（发现过程复盘）

这一节写给开发同学，完整还原定位过程——**反过来读就是加固线索**。

### 第 1 步：状态接口里的两个可疑字段

授权状态接口 `/api/v1/system/license/status` 的返回：

```json
{"activated":true, "enforced":true, "dev_mode":false, "code":"LIC_OK", ...}
```

`enforced` 和 `dev_mode` 两个字段的存在，说明代码里有"强制开/关"与"开发模式"的分支逻辑。**有分支就有条件，有条件就有开关**——这是整个 hunt 的起点。

### 第 2 步：静态搜索扑空（顺便发现字符串被压缩）

- 翻 `env.template`：只有 `APP_ENV=production`，没有任何 dev/enforce 相关项
- 翻启动脚本（明文 bash）：无相关环境变量
- 对 `license.so` 做字符串提取：只有 `is_enforced` 函数名和残缺片段 `E_ENFORC`
- 同时在字符串里发现了 `LZSS string data decompression failed`——**Cython 把一部分字符串常量 LZSS 压缩了**，静态搜索天然有盲区

### 第 3 步：换动态手段——运行时内省

静态看不见，就让它自己交代。在容器内直接 `dir()` 授权模块，列出**全部成员和模块级常量**（编译产物运行时藏不住属性）：

```bash
docker exec <app容器> python -c "
from app.core import license as L
print([n for n in dir(L) if not n.startswith('__')])
for n in dir(L):
    if not n.startswith('__') and not callable(getattr(L, n)):
        print(n, '=', repr(getattr(L, n)))
"
```

输出里立刻浮出三样高价值目标：

1. `settings.LICENSE_ENFORCE_EXTRA=False` —— 运行时配置里的"额外强制"开关（默认关）
2. `_AES_KEY_B64`、`_RSA_PUB_PEM` —— **授权文件的解密密钥与验签公钥，以明文模块属性形式可读**（附件可离线解密授权载荷）
3. `build_flags` —— 一个名为"编译期标志"的独立 .so 模块

### 第 4 步：锁定开关

内省 `build_flags` 模块，它全部成员只有一个：

```python
from app.core import build_flags as B
print([n for n in dir(B) if not n.startswith('__')])
# ['LICENSE_ENFORCED']
print(B.LICENSE_ENFORCED)   # True  <- 整个授权强制体系的总开关
```

### 第 5 步：验证开关真的能翻

用导入拦截（`sitecustomize.py` 装 `sys.meta_path` finder，仅拦 `app.core.build_flags`，返回 `LICENSE_ENFORCED=False` 的假模块；**license 模块保持原装、不装授权文件、不注入指纹**）：

```python
class _FlagsFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "app.core.build_flags":
            spec = importlib.machinery.ModuleSpec(fullname, _FlagsLoader())
            return spec
sys.meta_path.insert(0, _FlagsFinder())
```

结果（系统自报）：

```json
{"activated":true, "enforced":false, "dev_mode":true, "code":"LIC_OK", "licensee":null}
```

- 授权文件不存在，系统却报 `activated:true / LIC_OK`
- `enforced:false` 后业务接口全部放行到登录层（401 而非 403），worker 正常常驻
- 附带解谜：`dev_mode:true` == "未强制模式"，即 dev 版 = 不校验授权的构建

---

## 三、三条路径的攻击明细

### 路径 1：授权克隆（指纹信源可注入）
- compose 经 `x-host-fp` 将宿主 `HOST_MAC` 以 `AGENT_FLOW_MAC` 注入容器；`license._read_primary_mac` **信任注入值而非实测硬件**
- 实测：生产授权文件 + `HOST_MAC=02-42-98-FA-54-52` → 异机 `activated:true`
- 顺带：`_AES_KEY_B64` 可读意味着授权载荷可离线解密阅读（licensee/到期时间等）

### 路径 2：模块替换（license 模块无完整性校验）
- 80 行 `sitecustomize.py` meta_path 拦截 `app.core.license`，按字符串表里的接口清单（`evaluate_license`/`ensure_licensed`/`LicenseStatus`...）返回全"有效"应答
- 接口清单来源：二进制字符串 + 运行时异常回显（堆栈泄露 `app/api/v1/system.py:53` 等行号），两轮迭代完成
- 结果：`LIC_OK, expires_at=2099-12-31, days_left=99999`，零授权文件

### 路径 3：总开关翻转（build_flags 无完整性校验）
- 见第二节，15 行

### 已验证的防守有效项（不需要修的）
- RSA-2048 签名：伪造授权文件不可行（公钥内嵌，私钥不在包内）
- 未激活 fail-closed：worker exit 78、业务端点 403、仅剩激活向导（实测成立）
- `/license/install` 接口：虽免认证，但先验签后写入，垃圾数据 400 拒绝且不落盘（MD5 前后一致）
- `/docs`、`/openapi.json`：后端已关闭（此前的"开放"为前端兜底页误报，已撤回）

---

## 四、根因

**保护了"授权数据不可伪造"（RSA），没有保护"校验程序不可替换"（无完整性校验）。** 而授权校验的最终输出只是一个布尔，攻击者不需要理解内部逻辑，只需要冒名输出"有效"——或直接把"是否需要校验"这个输入改掉。

## 五、修复建议（按优先级）

1. **模块完整性链**：构建期对 `license.so`、`build_flags.so` 计算摘要并用供应商私钥签名，清单内置于其他核心模块；启动时及运行期随机验签，不符即拒绝启动。这是封堵全部三条路径的关键一招。
2. **去单点化**：关键路径（工作流执行、任务派发、API 中间件）内联独立校验，不单一信任 `app.core.license` 的返回值，也不单一信任 `build_flags`。
3. **指纹实测**：`_read_primary_mac` 直接读系统网卡，注入值仅作容器场景的辅助并交叉核对；异常注入值（与实测不符）记日志告警。
4. **时间锚点**：数据目录持久化"最后可见时间"并签名，检测到时钟大幅回跳即锁死（防到期后回拨复活）。
5. **可选**：在线心跳 + 离线宽限期，建立吊销能力；`LICENSE_ENFORCE_EXTRA` 建议文档化或在生产默认开启。
6. **附带项**：`_AES_KEY_B64`/`_RSA_PUB_PEM` 可读虽是设计使然（客户端必须能解密），但建议至少将密钥与模块绑定完整性校验配合使用，避免"密钥+密文+可替换校验器"同包共存。

## 六、开发自测复现要点

- 实验：解压包 → 起容器（不装授权）→ 挂载上述 sitecustomize → 观察 status 接口与 worker 状态
- 断言基准：`enforced:false` 时 status 返回 `activated:true` 即复现路径 3；`/api/v1/agents` 由 403 变 401 即中间件放行
- 注意：请在隔离环境操作；正式授权文件勿放置于实验环境
