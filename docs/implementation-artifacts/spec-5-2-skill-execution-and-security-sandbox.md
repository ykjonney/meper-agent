---
status: draft
story_key: 5-2-skill-execution-and-security-sandbox
epic: 5
title: Skill 执行安全沙箱与 Workspace 隔离
created: 2026-06-17
---

# Story 5-2: Skill 执行安全沙箱与 Workspace 隔离

## 背景

当前 Agent 内置工具（bash / read / write）直接在 Backend 容器进程内裸执行，无隔离。多用户并发时：
- bash 可执行任意 shell 命令，无文件系统/网络限制
- read/write 可访问 Backend 容器内任意路径
- 不同用户 Session 产生的文件混杂在同一 `PROJECT_ROOT` 下，无法区分归属
- 用户无法下载 Agent 生成的文件

## 设计决策

### 隔离粒度：Session 级 Workspace

```
/data/workspaces/{user_id}/{session_id}/
├── input/        ← 用户上传的附件
├── output/       ← Agent 生成的可下载文件
└── tmp/          ← bash 执行的工作区（沙箱容器挂载点）
    └── tasks/{task_id}/  ← Task 子工作区（继承自 Session）
```

- Session 是主隔离单位（覆盖聊天直接执行和 Task 工作流两条路径）
- Task workspace 是 Session 下的子目录，继承归属关系
- 文件下载 API 统一在 Session 维度暴露

### 执行模型：分级沙箱

| 工具 | 执行位置 | 隔离机制 |
|------|---------|---------|
| `bash` | Docker 临时沙箱容器 | 容器隔离：无网络、资源限制、根文件系统只读、`--rm` 用完销毁 |
| `read` | Backend 进程内 | 路径守卫：限定 workspace 树内 + SKILLS_DIR 只读 |
| `write` | Backend 进程内 | 路径守卫：限定 workspace 树内，区分 output/tmp |
| `load_skill` | Backend 进程内 | 无风险（只读 Markdown） |
| MCP tools | Backend 进程内 → 外部 MCP Server | 网络隔离（MCP Server 独立进程） |
| Task tools | Backend 进程内 | 无风险（MongoDB 操作） |

### 沙箱镜像：前期单一镜像

`agent-sandbox:latest` — 预装 Python 3.12 + Node.js + 常用库（pandas, numpy, matplotlib, requests, pyyaml, jinja2, openpyxl, beautifulsoup4, pillow 等），后续按需支持定制镜像。

### 沙箱容器挂载

```
/workspace    → Session workspace/tmp (rw)
/input        → Session workspace/input (ro)
/data/skills  → SKILLS_DIR (ro) — 路径与 Backend 一致，无需路径转换
```

### Docker 集成方式

挂载 Docker Socket（方案 A），Backend 内通过 docker-py 创建临时容器：
```yaml
# docker-compose.yml backend service
volumes:
  - /var/run/docker.sock:/var/run/docker.sock
```

单机部署可接受，后续多节点部署时切换为 DinD sidecar。

## 实施计划

### Phase 1: Workspace 基础 + 路径守卫 + 文件下载 API

**目标**：建立 Session 级文件隔离，修复 read/write 安全漏洞，提供文件下载能力。

#### Task 1.1: Workspace 管理器

- 新建 `backend/app/engine/tool/workspace.py`
- 实现 `WorkspaceManager` 类：
  - `create_workspace(user_id, session_id)` — 创建 input/output/tmp 目录结构
  - `get_workspace(session_id)` — 返回 workspace 路径对象
  - `safe_resolve_path(base, user_path)` — 路径安全检查（`..` 遍历、符号链接）
  - `cleanup_workspace(session_id, max_age_days=30)` — 过期清理
- Workspace 根目录通过 `settings.WORKSPACES_DIR` 配置（默认 `/data/workspaces`）
- 编写单元测试

#### Task 1.2: Session 创建时自动建立 Workspace

- 修改 `backend/app/services/session_service.py`
- `SessionService.create()` 中调用 `WorkspaceManager.create_workspace()`
- 确保异常时目录回滚

#### Task 1.3: 改造 read/write 内置工具 — 路径守卫

- 修改 `backend/app/engine/agent/builtin_tools.py`
- `read` 工具：
  - 接受 `session_workspace` 上下文参数
  - `safe_resolve_path()` 检查路径必须在 workspace 树内
  - 允许只读访问 `/data/skills/` 下的 Skill 文件
  - 越界返回 `"Error: Access denied — path outside workspace"`
- `write` 工具：
  - 路径守卫同上
  - 支持 `as_output: bool = False` 参数，True 写 output/，False 写 tmp/
  - 自动创建父目录

#### Task 1.4: Workspace 上下文注入

- 修改 `backend/app/engine/agent/builder.py`
- `_resolve_execution_context()` 中获取当前 session_id
- 将 workspace 路径注入到工具闭包（通过 partial 或闭包变量）
- 修改 `react_executor.py` 中工具调用链路，传递 workspace 上下文

#### Task 1.5: 文件下载 API

- 新建 `backend/app/api/v1/sessions_files.py`
- 三个端点：
  - `GET /api/v1/sessions/{session_id}/files` — 列出 output/ 下所有文件（含大小、修改时间）
  - `GET /api/v1/sessions/{session_id}/files/{path}` — 下载单个文件（StreamingResponse）
  - `GET /api/v1/sessions/{session_id}/files.zip` — 打包下载全部 output（zipfile 流式生成）
- 权限校验：`session.user_id == current_user.id`，否则 403
- 路由注册到 `api/v1/router.py`

#### Task 1.6: 前端文件列表与下载

- 修改 `frontend/src/pages/agent-detail-page.tsx` 或 Session 页面
- 添加文件列表区域（AntD Table），展示 output/ 下文件
- 下载按钮调用文件下载 API
- 新增 `frontend/src/services/session-file-api.ts`

### Phase 2: bash 工具容器化

**目标**：bash 工具在 Docker 沙箱容器内执行，与 Backend 文件系统完全隔离。

#### Task 2.1: 沙箱镜像构建

- 新建 `deploy/Dockerfile.sandbox`
- 基础镜像 `python:3.12-slim`
- 安装：curl, git, jq, wget, unzip, tree, Node.js 22
- pip 安装：pandas, numpy, scipy, matplotlib, openpyxl, requests, httpx, pyyaml, jinja2, toml, beautifulsoup4, lxml, pillow, tabulate, rich
- 创建非 root 用户 `sandbox`
- 设置 `WORKDIR /workspace`
- docker-compose.yml 或 Makefile 中添加构建命令

#### Task 2.2: Sandbox 管理器

- 新建 `backend/app/engine/tool/sandbox.py`
- 实现 `SandboxExecutor` 类：
  - `__init__(image, default_timeout, mem_limit)` — 从 settings 读取配置
  - `execute(command, workspace, timeout, env_vars)` → `SandboxResult(stdout, stderr, exit_code, timed_out)`
  - 内部使用 `docker.containers.run()` 创建临时容器
  - 挂载配置：workspace/tmp(rw), workspace/input(ro), SKILLS_DIR(ro)
  - 安全配置：`network_mode="none"`, `read_only=True`, `auto_remove=True`, `security_opt=["no-new-privileges"]`
  - 资源限制：`mem_limit`, `cpu_quota`, `tmpfs`
  - 超时控制：`docker-py` timeout + 容器 kill
- 连接 Docker Socket 的健康检查
- 编写单元测试（mock docker-py）

#### Task 2.3: 改造 bash 内置工具

- 修改 `backend/app/engine/agent/builtin_tools.py`
- `bash` 工具从 `subprocess.run()` 切换到 `SandboxExecutor.execute()`
- 保持原有的输出截断逻辑（50KB 限制）
- 保持超时机制（默认 120s，可通过容器 timeout 控制）
- 错误处理：Docker 不可用时返回明确错误信息

#### Task 2.4: docker-compose 配置更新

- `deploy/docker-compose.yml` backend 服务添加 Docker Socket 挂载
- 添加 `SANDBOX_IMAGE` 环境变量
- 添加 `WORKSPACES_DIR` 环境变量和 volume 挂载
- 可选：添加 `create-admin` 服务（之前丢失的功能）

#### Task 2.5: ToolNodeExecutor 沙箱集成

- 修改 `backend/app/engine/workflow/node_executor.py` 中 `ToolNodeExecutor`
- 当工具类型为内建/Python Skill 时，走 SandboxExecutor
- MCP 工具保持现有逻辑不变

### Phase 3: 生命周期管理 + 加固

**目标**：Workspace 清理、配额、熔断、审计增强。

#### Task 3.1: Workspace 生命周期管理

- Celery 定时任务：扫描过期 workspace（Task 完成后 N 天）
- 清理策略：tmp/ 优先清理，output/ 保留更久
- 可配置的保留天数（settings 级别）

#### Task 3.2: 配额控制

- Workspace 大小上限（默认 500MB）
- 写入前检查剩余配额
- 超限返回明确错误

#### Task 3.3: 工具熔断机制

- 实现 `CircuitBreaker` 类（基于 Story 3.5 AC）
- 每个工具独立熔断器
- 状态：closed → open（5 次中 3 次失败）→ half-open（探测恢复）
- 熔断时返回 `"工具暂时不可用"`
- 熔断状态记录到日志

#### Task 3.4: 审计日志增强

- 每次沙箱执行记录：session_id, user_id, command, exit_code, duration, memory_used
- 文件读写操作记录到审计日志
- 异常事件告警（连续超时、配额超限等）

## 依赖

| 依赖 | 说明 |
|------|------|
| `docker-py` | Python Docker SDK，`uv add docker` |
| Docker Socket | docker-compose 配置变更 |
| `agent-sandbox` 镜像 | Phase 2 构建 |

## Spec Change Log

| 日期 | 变更 |
|------|------|
| 2026-06-17 | 初始版本 — 基于方案讨论确认的设计 |
