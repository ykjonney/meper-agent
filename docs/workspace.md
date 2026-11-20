# Workspace 设计（重设计版）

> 本文是 workspace 层的唯一设计文档：域模型、双后端、环境感知、缺陷修复与
> 待定决策。代码位于 `backend/packages/harness/src/agent_flow_harness/workspace/`
> （策略）与 `backend/app/engine/tool/workspace.py`（宿主装配）。

## 1. 设计原则与职责切分

| 层 | 职责 | 不做什么 |
|---|---|---|
| **工具**（`sandbox/tools.py`） | 只讲语法：路径怎么传（相对/绝对）、old_string 匹配规则 | 不携带 workspace 语义（目录布局/写策略） |
| **prompt**（`## Environment` 段） | 讲环境：目录地图、读写策略、双坐标系对应 | 不做校验 |
| **layout**（`workspace/` 包） | 讲策略：路径解析、越权/角色校验、写策略硬闸 | 不做 I/O（纯函数，易测） |
| **Sandbox** | 执行：bash（Docker/本机）+ 文件读写（宿主路径） | 不自带映射逻辑（原两份 ~100 行重复代码已删） |

环境段由 `WorkspaceLayout.describe()` 生成，宿主注入 system prompt
（`render_system_prompt_full` 的 `environment` 参数，插在工具声明之前）。
**环境是"地图"，工具声明是"用法"**——模型开局即知 workspace 全貌，
不再靠工具描述碎片和错误反馈试错。

## 2. 双后端

### CloudLayout（`mode="cloud"`，默认）

平台托管的三目录角色分区（原有语义收编）：

```
{WORKSPACES_ROOT}/{user_id}/{session_id}/
    tmp/     工作区（bash cwd = 容器内 /workspace/tmp；read/edit 裸路径默认）
    input/   只读用户附件（write/edit 一律拒绝）
    output/  产物（write 唯一去向，用户可下载）
```

- 双坐标系：bash 看容器路径 `/workspace/{tmp,input,output}`，文件工具收
  相对路径（前缀映射）——对应关系由 `describe()` 显式告知模型。
- **A1 写策略硬闸**（`resolve_write`）：write 指向 `tmp/`、`input/`（含
  容器风格 `/workspace/tmp/...`）→ 显式报错引导用 edit。修复原"静默错
  路由到 output/tmp/..."的缺陷。
- 非 workspace 模式（独立使用 Sandbox，如治理 code 工具）：保持旧行为，
  无 tmp/input 角色故不设闸。

### LocalLayout（`mode="local"`，本地接入）

同机目录接入（类 Claude Code cwd）：backend 与用户目录同机/同内网，
agent 直接操作用户指定的目录树。

- 单 root 全权：read/write/edit 限 root 树内（绝对路径在树内允许；
  符号链接逃逸经 resolve + is_within 拦截）。
- 无 input/output 职能 → uploads 端点返回 400；不建托管目录（Sandbox
  跳过 output/ mkdir，禁止污染用户文件系统）。
- bash 本机执行（LocalSandbox），**cwd = root**。

### 本地接入启用方式

1. `LOCAL_WORKSPACE_ROOT`（env）设为白名单根目录；空 = 禁用（默认）。
2. 用户需 `local_workspace:write` 权限键（`role_service.ALL_PERMISSION_KEYS`，
   admin/developer 默认授予，backfill v6；operator/viewer 不开放，可经
   自定义角色授予）。
3. 创建会话：`POST /api/v1/sessions` 带 `local_dir`（白名单内相对路径；
   服务端校验权限/白名单/目录存在性）。
4. 执行链路：`resolve_harness_context(local_dir=...)` → LocalSandbox +
   LocalLayout，不建容器/挂载。

## 3. 缺陷修复（本次融入）

| 编号 | 缺陷 | 修复 |
|---|---|---|
| A1 | write 静默错路由（tmp/ → output/tmp/） | `CloudLayout.resolve_write` 硬闸 + 引导文案 |
| A3 | 并发互斥只覆盖单次 run（进程内锁） | `file_lock.py` 加 `fcntl.flock`（目标文件 fd，LOCK_EX 包住读改写临界区），跨进程互斥；bash 不经锁仍由 freshness mtime 兜底 |
| B7 | grep/glob 全量盲扫（.git/node_modules/.venv） | `workspace/scan.py`：pathspec 解析各级 .gitignore + 硬跳过噪音目录，grep/glob 共用 |

## 4. 生命周期预留（未实装，仅数据位）

- **B5 预配**：`SetupSpec`（layout.setup 字段）——未来对齐 Codex setup
  script 模式，容器/workspace 冷启动时装依赖，解决"复用容器被清扫后
  依赖蒸发"的环境漂移。
- **B4 快照**：`WorkspaceLayout.snapshot()` 存根（NotImplementedError）。
- **本地 bash 安全策略**（**TBD，待讨论**）：候选方案 ① 直接执行（信任
  环境）② HITL 审批门（复用 ask_clarification/human 设施）③ 静态约束
  （路径白名单 + 命令黑名单）。`LocalSandbox.execute_command` 预留
  `command_policy` 策略位，默认放行——拍板后接入，不阻塞当前交付。

## 5. 相关文件索引

| 层 | 文件 |
|---|---|
| 策略 ABC | `packages/harness/src/agent_flow_harness/workspace/layout.py` |
| 云端布局 | `.../workspace/cloud.py`（含 A1 闸 + describe） |
| 本地布局 | `.../workspace/local.py` |
| gitignore 扫描 | `.../workspace/scan.py` |
| Sandbox 接线 | `.../sandbox/local.py`、`.../sandbox/docker.py`（`layout` 参数，默认 CloudLayout 向后兼容） |
| 宿主装配 | `app/engine/tool/workspace.py`（`Workspace.mode/local_dir`、`get_local_workspace`、`layout_for_workspace`） |
| 沙箱选择 | `app/engine/harness_integration/context.py`（`local_dir` 参数 → LocalSandbox 分支） |
| 环境段注入 | `app/engine/agent/slot_renderer.py`（`environment` 参数）+ 服务层 `agent_execution_service._build_environment_section` + workflow `node_executor` |
| 会话绑定 | `app/api/v1/sessions.py`（`SessionCreate.local_dir` + `local_workspace:write` 校验 + uploads 拒绝） |
| 配置 | `LOCAL_WORKSPACE_ROOT`（`app/core/config.py`） |
| 测试 | harness `tests/workspace/`（策略矩阵/scan）、`tests/sandbox/test_file_lock.py`（flock 跨进程）、backend `tests/services/test_local_workspace.py` |

## 6. 已知边界

- flock 是 advisory lock：bash（sed 等）不经锁，靠 freshness 事后兜底；
  NFS 上 flock 语义弱——当前假设单机工作区。
- 本地模式下 agent 触及的是宿主真实文件系统——bash 安全边界未定稿前
  建议 `LOCAL_WORKSPACE_ROOT` 只在可信环境（私有化交付）开启。
- 旧字段兼容：`SessionResponse.local_dir` 空串 = 云端会话，前端可选展示。
