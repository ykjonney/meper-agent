---
stepsCompleted: [1, 2, 3, 4]
epicsStage: 'epics-designed'
inputDocuments:
  - prds/prd-agent-flow-2026-06-05/prd.md
  - architecture.md
  - ux-designs/ux-agent-flow-2026-06-08/DESIGN.md
  - ux-designs/ux-agent-flow-2026-06-08/EXPERIENCE.md
deferredEpics:
  - epic: 7
    name: '知识库管理'
    frs: [FR-16, FR-17]
    reason: '主人确认 MVP 范围暂不考虑知识库（2026-06-08）'
    revisit: 'post-MVP Sprint 2 评估 RAG 需求强度'
workflowType: 'epics-stories'
project_name: 'Agent Flow'
user_name: 'Logan_hu'
date: '2026-06-09'
---

# Agent Flow - Epic Breakdown

## Overview

This document provides the complete epic and story breakdown for Agent Flow, decomposing the requirements from the PRD, UX Design, and Architecture requirements into implementable stories organized by user value.

**Sources scanned:**
- PRD: `prd-agent-flow-2026-06-05/prd.md` (35 FRs across 13 features + 6 NFR categories)
- UX Design: `ux-designs/ux-agent-flow-2026-06-08/` (DESIGN.md + EXPERIENCE.md)
- Architecture: `architecture.md` (1977 lines, 24 critical decisions, 5 pattern categories)

## Requirements Inventory

### Functional Requirements

#### Agent 创建与配置（FR-1~FR-3）

| ID | 描述 | 来源 |
|----|------|------|
| FR-1 | Agent 生命周期管理：创建、编辑、复制、删除、发布 Agent。包含名称、描述、系统提示词、工具选择、知识库绑定、工作流绑定、模型配置和运行时参数。 | PRD §4.1 |
| FR-2 | Agent 能力组合：用户可从工具池中选择零个或多个工具、绑定零个或多个工作流、关联零个或多个知识库。Agent 能力可选组合。 | PRD §4.1 |
| FR-3 | Agent 模型配置：默认运行模型 + 动态路由规则（条件-模型对列表，按序匹配，无匹配用默认）。支持 5-10 个主流 LLM。 | PRD §4.1 |

#### Agent 自主规划与执行（FR-4~FR-8）

| ID | 描述 | 来源 |
|----|------|------|
| FR-4 | Job 评估与执行路径选择：Agent 收到输入后由模型自主判断选择直接执行/规划执行/工作流执行三条路径。判断依据记录在执行日志中。 | PRD §4.2 |
| FR-5 | 直接执行模式：REACT 推理（Reasoning + Acting），不生成执行计划。每步思考过程和工具调用记录日志。 | PRD §4.2 |
| FR-6 | 规划执行模式：计划→执行→验证三阶段。Agent 生成结构化计划，逐步执行，检查结果是否满足要求。 | PRD §4.2 |
| FR-7 | 工作流执行模式：Agent 调用 Workflow 创建 Task 实例，传入 Job 上下文（按 input_schema 浅拷贝）。Task 完成后结果返回 Agent。 | PRD §4.2 |
| FR-8 | 调用深度与循环保护：Workflow 级节点深度限制 + 全局调用链深度上限。超出时终止并返回错误。 | PRD §4.2 |

#### 工作流编排（FR-9~FR-12A）

| ID | 描述 | 来源 |
|----|------|------|
| FR-9 | DAG 工作流编辑器：可视化拖拽编辑，支持缩放、平移、自动布局。检测并阻止环路，保存时验证必需参数。 | PRD §4.3 |
| FR-10 | 核心节点类型：8 种（start/end/agent/tool/human/gateway/parallel/subflow），每种有独立配置 schema 和执行语义。 | PRD §4.3 |
| FR-11 | 条件边配置：节点输出判断 + 数据条件两种条件类型。统一表达式引擎内置 try-catch，变量未定义走 fallback。 | PRD §4.3 |
| FR-12 | 工作流版本管理：每次修改保存创建新版本，历史版本只读。发布后才能被 Agent 调用。 | PRD §4.3 |
| FR-12A | 工作流模板管理：DB+文件双写，semver 版本号，Task 绑定模板快照。规则引擎执行装配，LLM 不参与结构变更。提供 migrate_task 接口。 | PRD §4.3 |

#### Task 生命周期管理（FR-29~FR-33）

| ID | 描述 | 来源 |
|----|------|------|
| FR-29 | Task 状态机：7 状态（pending/running/waiting_human/paused/completed/failed/cancelled）+ 16 种状态转换规则。终态不可转换，所有转换记录审计日志。 | PRD §4.3A |
| FR-30 | Task 前后台模式：前台阻塞等待 30s 自动转后台。同一 Session 允许多后台并行，前台仅一个。不同推送策略（前台逐节点推送，后台仅关键节点）。 | PRD §4.3A |
| FR-31 | Task 流程干预：8 种操作（approve/reject/skip/pause/resume/cancel/rollback/inject）。使用乐观锁 version 字段防并发冲突。所有操作记录审计日志。 | PRD §4.3A |
| FR-32 | Agent 系统级 Task 工具：9 种工具（search_workflow/get_workflow_schema/create_task/task_query/task_intervene/task_list/cancel_task/get_task_timeline/update_task_variables）。 | PRD §4.3A |
| FR-33 | Agent 与 Workflow 交互（能力地图）：Agent 启动时 Workflow Registry 注入（when_to_use/required_entities/has_human_node/side_effects）。决策机制：只读→Direct，写操作/需审批→创建 Task。 | PRD §4.3A |

#### 工具系统（FR-13~FR-15）

| ID | 描述 | 来源 |
|----|------|------|
| FR-13 | Skill 管理：三种来源（前端创建/Git 拉取/文件上传）。解析后注册到工具池。 | PRD §4.4 |
| FR-14 | MCP 连接管理：配置 MCP 服务器地址和认证 → 自动发现工具列表 → 选择注册。工具状态实时反映连接状态。 | PRD §4.4 |
| FR-15 | 工具池与统一接口：Skill 和 MCP 工具统一格式呈现。Agent 配置时不感知来源差异。删除被引用工具时确认影响范围。 | PRD §4.4 |

#### 知识库管理（FR-16~FR-17）— 🔴 Epic 6 DEFERRED

| ID | 描述 | 来源 |
|----|------|------|
| FR-16 | 知识库创建与文档管理：上传文档（PDF/Word/Markdown），自动解析分块索引，增删改操作。 | PRD §4.5 |
| FR-17 | 知识库检索：Agent 运行时自动检索绑定知识库，获取相关文档片段，包含相关度评分。 | PRD §4.5 |

#### API/SDK 接口（FR-18~FR-19）

| ID | 描述 | 来源 |
|----|------|------|
| FR-18 | Agent 调用 API：外部系统通过 REST API 向 Agent 发送任务。支持同步和异步调用。API Key 认证。 | PRD §4.6 |
| FR-19 | 事件回调：外部系统注册回调 URL，Agent 任务完成或状态变更时主动通知。回调失败按重试策略重试。 | PRD §4.6 |

#### 对话交互（FR-20~FR-21）

| ID | 描述 | 来源 |
|----|------|------|
| FR-20 | Agent 对话界面：Web 对话界面，文本输入多轮交互。Agent 回复展示工具调用和推理过程。对话历史持久化。 | PRD §4.7 |
| FR-21 | 对话触发工作流：用户输入多步骤任务时，Agent 自动匹配并执行对应 Workflow。执行结果在对话中展示。 | PRD §4.7 |

#### 上下文管理（FR-22~FR-24）

| ID | 描述 | 来源 |
|----|------|------|
| FR-22 | 三层上下文隔离：Session（对话级持久化）/ Task（变量池隔离）/ Node（节点级临时）。流转规则：按 input_schema 浅拷贝，只同步状态摘要，按 output_schema 映射结果。 | PRD §4.8 |
| FR-22A | 对话上下文压缩：超出模型上下文窗口时自动压缩历史消息，保留关键决策和结果。 | PRD §4.8 |
| FR-23 | Task 触发对话：Workflow 中 Agent 节点可创建新对话或恢复已有对话。对话和 Task 生命周期独立。 | PRD §4.8 |
| FR-24 | 变量池与表达式注入：Task 运行时独立变量池。{{node_id.field}} 表达式读取上游输出。null-safe：未定义变量 gateway 走 fallback，params 注入为 null。 | PRD §4.8 |

#### 执行日志与可观测性（FR-25~FR-26）

| ID | 描述 | 来源 |
|----|------|------|
| FR-25 | 执行日志记录：全量记录 Job 执行路径、推理过程、工具调用、Task 节点执行。审计日志附加操作人和时间戳。 | PRD §4.9 |
| FR-26 | 调用链追踪：Agent→Task→Agent 嵌套调用完整执行树。跨 subflow 链路串联。分布式 tracing（OpenTelemetry）。 | PRD §4.9 |

#### 权限管理（FR-27）

| ID | 描述 | 来源 |
|----|------|------|
| FR-27 | 用户认证与角色管理：登录认证 + 四角色（管理员/开发者/操作员/只读）。不同角色对 Agent/Workflow/工具/知识库有不同操作权限。 | PRD §4.10 |

#### Web 管理界面（FR-28）

| ID | 描述 | 来源 |
|----|------|------|
| FR-28 | 统一管理界面：侧边导航 + 主内容区布局。主要模块：仪表盘/Agent 管理/工作流管理/Task 管理面板/工具管理/知识库管理/对话面板/执行日志/系统设置。全部功能 Web 可操作。 | PRD §4.11 |

### Non-Functional Requirements

| ID | 类别 | 描述 | 指标 |
|----|------|------|------|
| NFR-1 | 性能 | API 同步调用响应时间 | 直接执行 ≤ 30 秒返回首条结果 |
| NFR-2 | 性能 | Web 界面首屏加载 | ≤ 3 秒 |
| NFR-3 | 性能 | 流式输出 | 对话流式输出，不等待完整响应 |
| NFR-4 | 性能 | 前台超时转后台 | 前台 Task 30s 自动转后台 |
| NFR-5 | 可靠性 | API 调用成功率 | ≥ 99%（排除 Agent 自身错误和外部故障） |
| NFR-6 | 可靠性 | 单组件故障隔离 | 单个组件故障不导致整个平台不可用 |
| NFR-7 | 可靠性 | Engine 降级模式 | Workflow Engine 不可用时 Direct 模式仍可用 |
| NFR-8 | 可靠性 | 日志持久化 | 执行日志不因服务重启丢失 |
| NFR-9 | 可靠性 | Tool 熔断隔离 | 单 Tool 超时/熔断不影响其他 Tool |
| NFR-10 | 安全 | API 认证 | 所有 API 调用需认证（API Key 或 JWT Token） |
| NFR-11 | 安全 | 密码安全 | 用户密码加密存储（bcrypt），不落明文日志 |
| NFR-12 | 安全 | 日志脱敏 | 执行日志中敏感信息脱敏处理 |
| NFR-13 | 安全 | 变量池隔离 | Task 变量池隔离，不泄漏跨 Task 数据 |
| NFR-14 | 扩展性 | 单机部署容量 | 支持 50 用户同时在线 |
| NFR-15 | 扩展性 | 单用户并发 | 单用户 ≤ 5 个并发 Task |
| NFR-16 | 扩展性 | 全局并发上限 | 全局 ≤ 50 并发 Task（可配置） |
| NFR-17 | 并发 | 乐观锁冲突 | Task 干预使用 version 字段，冲突提示重新获取 |
| NFR-18 | 数据 | 日志保留 | 运行时日志 30 天，审计日志 90 天（可配置） |
| NFR-19 | 数据 | 文件上传限制 | 默认单文件 ≤ 50MB |

### Additional Requirements (Architecture)

1. **项目初始化** — Vite + React 19 + FastAPI + LangGraph 1.0.8+ 初始脚手架搭建（Architecture §Starter Template）
2. **Docker Compose 单机部署** — 6 服务（frontend/backend/mongodb/redis/celery-worker/caddy），NFR 单机约束（Architecture §Decision Priority）
3. **MongoDB 7.0+ 基础设施** — 主库 + Atlas Vector Search + MongoDBSaver Checkpointer。统一一个 DB 减少组件（Architecture Decision 1.1/1.2/1.3）
4. **Celery + Redis 任务队列** — 双重角色（缓存 + Celery broker）。MVP 负载低，一站式降低组件数（Architecture Decision 1.4/1.5）
5. **JWT 认证体系** — access token 15min + refresh token 7d HttpOnly Cookie。外部 API Key 格式 `af_live_{32位随机}`（Architecture Decision 2.1/2.2）
6. **RBAC 手写装饰器** — `Depends(require_role("admin"))` 依赖注入，角色定义集中在 `core/security.py`（Architecture Decision 2.3）
7. **WebSocket + SSE 双协议** — WebSocket 对话/工作流双向，SSE 事件订阅单向推送（Architecture Decision 3.4）
8. **OpenAPI 3.1 + openapi-typescript** — 前端 API 类型从后端自动生成，不手写（Architecture Decision 3.6）
9. **三层状态管理** — TanStack Query（服务端缓存/轮询）+ Zustand（客户端 UI）+ AntD Form（表单）（Architecture Decision 4.1）
10. **目录分离 monorepo** — backend/（FastAPI）+ frontend/（Vite React）+ deploy/（Docker Compose）（Architecture §Starter Template）
11. **Task 状态机实现** — Python enum + 转换规则表 + MongoDB `findOneAndUpdate` 原子更新乐观锁（Architecture Decision 6.1/6.2）
12. **变量池表达式引擎** — MongoDB 嵌入文档 + jinja2 sandbox 安全求值（Architecture Decision 6.3）
13. **Workflow Registry** — Agent StateGraph 构建时 System Prompt 注入全量已发布 Workflow 元数据（Architecture Decision 6.4）
14. **前后台模式实现** — Celery 异步执行 + 30s 超时自动转后台 + WebSocket 推送（Architecture Decision 6.5）
15. **流程干预 REST API** — `POST /api/v1/tasks/{task_id}/intervene` + version 乐观锁 + 409 Conflict（Architecture Decision 6.6）
16. **Node Executor Strategy 模式** — `BaseNodeExecutor` 抽象类 + 8 种节点实现（Architecture Decision 6.7）
17. **前端组件分层** — pages/（路由页）+ features/（13 个业务特性）+ components/（通用）+ hooks/ + services/（API）+ stores/（全局）（Architecture §Frontend Architecture）
18. **GitHub Actions CI/CD** — PR 检查（lint + type-check + test）+ main 镜像构建（Architecture §CI/CD）
19. **co-located 测试** — 前端 vitest + 后端 pytest，测试文件与源文件同目录（Architecture §File Structure）
20. **代码规范工具链** — ruff（后端）+ ESLint/Prettier（前端）+ mypy 类型检查（Architecture §Enforcement）

### UX Design Requirements

**设计令牌与主题系统：**

| ID | 描述 | 来源 |
|----|------|------|
| UX-DR1 | **设计令牌系统** — Tailwind CSS 变量映射 Ant Design 5.x 品牌色。Primary #1E5EFF、Accent #00D4FF，含灰度/语义/角色色。暗色模式预留 CSS 变量 MVP 不实现。 | DESIGN.md §Colors |
| UX-DR2 | **字体系统** — 系统 sans UI 字体（PingFang SC/Microsoft YaHei）+ SF Mono 等宽代码字体。标题 24/20/16px，正文 14px，辅助 12px。 | DESIGN.md §Typography |
| UX-DR3 | **间距与圆角** — 8px 基座间距（4/8/12/16/24/32/48px）。克制圆角（0/2/4/8/12/50%），节点/Tag 零圆角。 | DESIGN.md §Layout, §Shapes |
| UX-DR4 | **阴影与层级** — 四级阴影（sm/md/lg/xl），元素最多 1 层阴影。AntD 卡片用 md、Modal 用 lg、Drawer 用 xl。 | DESIGN.md §Elevation |
| UX-DR5 | **应用外壳布局** — 56px 顶栏（Logo + 搜索 + 用户菜单）+ 240px 可折叠侧栏（折叠 64px）+ 最大 1440px 主内容区。 | EXPERIENCE.md §IA |
| UX-DR6 | **信息架构导航** — 10 项侧栏导航按角色过滤（工作台/对话/Agent/工作流/工具/知识库/执行日志/API Key/用户管理/设置）。Cmd+K 全局搜索。 | EXPERIENCE.md §IA |
| UX-DR7 | **工作流编辑器布局** — 全屏模式（无侧栏折叠），顶部 48px 工具栏。左节点调色板 + 中画布 + 右节点参数面板。 | EXPERIENCE.md §IA |
| UX-DR8 | **对话界面布局** — 左 30% 会话列表 + 右 70% 对话区。流式输出青色脉冲点。 | EXPERIENCE.md §IA |

**UI 组件库：**

| ID | 描述 | 来源 |
|----|------|------|
| UX-DR9 | **按钮组件** — 6 种变体（Primary/Default/Danger/Text/Disabled/Loading），3 种尺寸（large 40/middle 32/small 24px），Loading 态 Spinner。 | DESIGN.md §Components/Buttons |
| UX-DR10 | **输入框组件** — 4 种状态（Default/Focus/Error/Disabled），border 1px+focus 2px blue glow，blur 校验。 | EXPERIENCE.md §Component Patterns/Inputs |
| UX-DR11 | **卡片组件** — 3 种变体（Static/Interactive/Loading），1px border `#E5E6EB`，圆角 4px。Interactive hover 灰底+阴影。 | EXPERIENCE.md §Component Patterns/Cards |
| UX-DR12 | **表格组件** — 表头灰底 `#F7F8FA` medium，行高 40px，hover 高亮，选中左 3px primary 边。服务端分页 20 条/页。 | EXPERIENCE.md §Component Patterns/Tables |
| UX-DR13 | **状态徽章** — 7 种状态（Draft/Publised/Running/Success/Failed/Warning/AIProcessing），各有色值+文字+图标。 | DESIGN.md §Components/Tags |
| UX-DR14 | **弹窗与抽屉** — Modal 宽 520/720/960px shadow lg；Drawer 宽 480px shadow xl。Esc/遮罩/右上 X 关闭。危险确认不响应遮罩点击。 | EXPERIENCE.md §Component Patterns/Modals |
| UX-DR15 | **加载状态组件** — 5 种场景（页面 Spin 大 + 遮罩 / 区块 Spin / 按钮内置 Spinner / 骨架屏 3-5 行 / 流式青色脉冲点）。 | EXPERIENCE.md §State Patterns |
| UX-DR16 | **空状态组件** — AntD Empty 居中 108x108px 插画 + 14px 灰字说明 + 可选 CTA 按钮。 | EXPERIENCE.md §State Patterns |
| UX-DR17 | **错误状态组件** — 全局 404/403/500 独立页 + 内联红色错误条（含错误码+重试）+ Toast 右上角（成功 3s 自动消失/错误手动关闭）。 | EXPERIENCE.md §State Patterns |

**交互模式：**

| ID | 描述 | 来源 |
|----|------|------|
| UX-DR18 | **键盘快捷键** — Cmd+K 搜索 / Cmd+S 保存 / Cmd+Enter 发送 / Esc 关闭 / g+d/a/w 导航 / ? 帮助面板。 | EXPERIENCE.md §Interaction Primitives |
| UX-DR19 | **工作流编辑器拖拽** — 节点调色板拖放、连线（output→input handle）、多选 Shift+click、复制粘贴 Cmd+C/V（偏移粘贴）、撤销 50 步。 | EXPERIENCE.md §Interaction Primitives |
| UX-DR20 | **通用状态矩阵** — 每个异步组件处理 5 状态（Loading 初始 Skeleton/Loading 后台刷新微 Spinner/Empty AntD+CTA/Error 红色条+重试/Success 正常态）。 | EXPERIENCE.md §State Patterns |
| UX-DR21 | **执行状态可视化** — 节点级：执行中节点青色脉冲 glow、已完成绿色、Agent 流式输出青色脉冲点"AI 正在思考..."。 | EXPERIENCE.md §State Patterns |

**关键用户流：**

| ID | 描述 | 来源 |
|----|------|------|
| UX-DR22 | **Agent 创建向导** — 4 步流程（基本信息→能力选择→提示词模板→测试发布）。AntD Steps + 上一步/下一步/保存草稿。 | EXPERIENCE.md §Key Flows/Flow 1 |
| UX-DR23 | **操作员对话流** — Agent 选择→流式输出→工具调用可视化→Workflow 触发进度→文件下载。 | EXPERIENCE.md §Key Flows/Flow 2 |
| UX-DR24 | **API Key 管理流** — 创建 Key→唯一展示含复制按钮（不二次显示）→Webhook 配置→测试回调。 | EXPERIENCE.md §Key Flows/Flow 3 |
| UX-DR25 | **Task 管理面板** — Task 列表（按 7 种状态筛选）→详情面板（状态/变量池/时间线）→干预操作栏（approve/reject/skip/pause/resume 按钮）。 | EXPERIENCE.md §IA |

**无障碍与响应式：**

| ID | 描述 | 来源 |
|----|------|------|
| UX-DR26 | **键盘导航** — 语义 HTML（button/nav/main）、Tab 顺序视觉一致、Skip Link、Focus 2px primary outline。 | EXPERIENCE.md §Accessibility |
| UX-DR27 | **屏幕阅读器** — 图标按钮 aria-label、Toast aria-live polite、错误 aria-live assertive、表单 label 关联。 | EXPERIENCE.md §Accessibility |
| UX-DR28 | **状态不依赖颜色** — Tag 必须同时用文字 + 图标 + 颜色，不单靠颜色区分。 | EXPERIENCE.md §Accessibility |
| UX-DR29 | **响应式适配** — 桌面优先 90% 全功能，平板 10% 侧栏折叠，移动端显示"请使用桌面浏览器"。 | EXPERIENCE.md §Responsive |

### FR Coverage Map

| FR | Epic | 说明 |
|----|------|------|
| FR-1 | Epic 2 | Agent 生命周期管理（创建/编辑/复制/删除/发布） |
| FR-2 | Epic 2 | Agent 能力组合（工具/工作流/知识库） |
| FR-3 | Epic 2 | Agent 模型配置（默认模型 + 动态路由） |
| FR-4 | Epic 5 | Job 评估与执行路径选择 |
| FR-5 | Epic 5 | 直接执行模式（REACT） |
| FR-6 | Epic 5 | 规划执行模式（计划→执行→验证） |
| FR-7 | Epic 5 | 工作流执行模式（创建 Task） |
| FR-8 | Epic 5 | 调用深度与循环保护 |
| FR-9 | Epic 4 | DAG 工作流编辑器 |
| FR-10 | Epic 4 | 核心节点类型（8 种） |
| FR-11 | Epic 4 | 条件边配置 |
| FR-12 | Epic 4 | 工作流版本管理 |
| FR-12A | Epic 4 | 工作流模板管理 |
| FR-13 | Epic 3 | Skill 管理（三来源） |
| FR-14 | Epic 3 | MCP 连接管理 |
| FR-15 | Epic 3 | 工具池与统一接口 |
| FR-16 | Epic 7 🔴 | 知识库创建与文档管理 — DEFERRED |
| FR-17 | Epic 7 🔴 | 知识库检索 — DEFERRED |
| FR-18 | Epic 8 | Agent 调用 API（同步/异步） |
| FR-19 | Epic 8 | 事件回调（Webhook） |
| FR-20 | Epic 2 | Agent 对话界面 |
| FR-21 | Epic 5 | 对话触发工作流 |
| FR-22 | Epic 4/5/6 | 三层上下文隔离：Node→Epic 4 / Session→Epic 5 / Task→Epic 6 |
| FR-22A | Epic 5 | 对话上下文压缩 |
| FR-23 | Epic 5 | Task 触发对话 |
| FR-24 | Epic 4 | 变量池与表达式注入 |
| FR-25 | Epic 6 | 执行日志记录 |
| FR-26 | Epic 6 | 调用链追踪 |
| FR-27 | Epic 1 | 用户认证与角色管理（四角色） |
| FR-28 | Epic 1 | 统一管理界面 |
| FR-29 | Epic 6 | Task 状态机（7 状态 16 转换） |
| FR-30 | Epic 6 | Task 前后台模式（30s 自动转后台） |
| FR-31 | Epic 6 | Task 流程干预（8 种操作 + 乐观锁） |
| FR-32 | Epic 6 | Agent 系统级 Task 工具（9 种） |
| FR-33 | Epic 6 | Agent 与 Workflow 交互（能力地图 Registry） |

## Epic List

### Epic 1: 平台基础建设
用户可以登录、管理用户和角色、配置平台运行环境。平台可 Docker 一键部署，含 CI/CD 流水线。
**FRs 覆盖:** FR-27（用户认证与角色管理）、FR-28（统一管理界面）
**架构覆盖:** 项目初始化、Docker Compose（6 服务）、MongoDB/Celery/Redis 基础设施、JWT 认证 + API Key、RBAC 手写装饰器、WS/SSE 双协议、OpenAPI 3.1 + 自动类型生成、三层状态管理、目录分离 monorepo、GitHub Actions CI/CD、co-located 测试、代码规范工具链
**UX 覆盖:** 设计令牌系统（色/字体/间距/圆角/阴影）、应用外壳布局、信息架构导航、通用组件库（按钮/输入框/卡片/表格/徽章/弹窗/抽屉/加载/空/错误）、键盘快捷键、通用状态矩阵、无障碍

### Epic 2: Agent 配置与管理
开发者可以创建、编辑、发布 Agent，为其组合提示词、工具、模型和工作流能力。创建后可立即通过对话界面测试。
**FRs 覆盖:** FR-1（Agent 生命周期管理）、FR-2（Agent 能力组合）、FR-3（Agent 模型配置 + 动态路由）、FR-20（Agent 对话界面）
**架构覆盖:** `api/v1/agents/crud`、`services/agent_service`、`engine/agent/builder`（StateGraph 构建）、`features/agent_management/`、`features/conversation/`
**UX 覆盖:** Agent 创建向导 4 步流（UX-DR22）、操作员对话流（UX-DR23）

### Story 2.1: Agent 数据模型与后端 CRUD API

As a 开发者，
I want 可以创建和管理 Agent 的数据模型，并通过 REST API 对 Agent 进行增删改查，
So that 后续的前端页面和 Agent 执行引擎可以基于这些 API 工作。

**Acceptance Criteria:**

**Given** 平台后端已部署
**When** 开发者通过 API 创建 Agent（传入 name、description、system_prompt 等字段）
**Then** Agent 记录写入 MongoDB，返回包含 agent_ulid 的完整对象
**And** 支持通过 `/api/v1/agents` 查询列表（分页）、通过 `/api/v1/agents/{id}` 获取详情
**And** 支持编辑 Agent 配置（PUT 更新）、删除 Agent（需检查是否有活跃引用）
**And** Agent 数据模型包含字段：id、name、description、system_prompt、tool_ids、workflow_ids、knowledge_base_ids、model_config、status、version、created_at、updated_at
**And** 编辑已发布的 Agent 后不影响正在进行的对话，新对话使用新配置

### Story 2.2: Agent 配置前端页面

As a 开发者，
I want 在 Web 界面中查看 Agent 列表、创建和编辑 Agent，
So that 我可以方便地管理所有 Agent 配置，无需直接调用 API。

**Acceptance Criteria:**

**Given** 用户已登录并拥有开发者角色
**When** 用户访问 Agent 管理页面（`/agents`）
**Then** 展示 Agent 列表，包含名称、状态、创建时间、操作按钮
**And** 列表支持分页、按状态筛选、按名称搜索
**And** 点击"新建 Agent"进入创建向导，完成后 Agent 出现在列表中
**And** 点击 Agent 进入详情/编辑页面，可修改配置后保存
**And** 空状态时展示"还没有 Agent"提示 + "创建第一个 Agent"按钮
**And** 加载中展示骨架屏，接口失败展示错误提示 + 重试按钮

### Story 2.3: Agent 能力组合配置

As a 开发者，
I want 在 Agent 配置页面中从工具池选择工具、绑定工作流，
So that Agent 拥有所需的能力组合，运行时可使用这些能力。

**Acceptance Criteria:**

**Given** 用户在 Agent 编辑页面
**When** 用户进入"能力配置"步骤
**Then** 展示当前可用的工具池列表（多选）、工作流列表（多选），每个项包含名称和描述
**And** 用户选择后保存，Agent 的 tool_ids 和 workflow_ids 字段更新
**And** 已选择的能力在列表中高亮显示，支持取消选择
**And** 未配置任何能力的 Agent 仅使用模型自身推理能力
**And** 工具/工作流被删除时，引用该工具的 Agent 在保存时提示

### Story 2.4: Agent 模型配置与动态路由

As a 开发者，
I want 为 Agent 配置默认运行模型和动态路由规则，
So that Agent 根据任务特征自动选择最适合的模型执行。

**Acceptance Criteria:**

**Given** 用户在 Agent 编辑页面
**When** 用户进入"模型配置"步骤
**Then** 可选择平台已接入的模型作为默认模型
**And** 可配置多条模型路由规则（条件-模型对列表），支持添加、删除和排序
**And** 路由规则按顺序匹配，无匹配时使用默认模型
**And** 修改模型配置后，新对话使用新模型，已有对话不受影响

### Story 2.5: Agent 发布管理

As a 开发者，
I want 将配置完成的 Agent 发布为可用状态，并管理版本历史，
So that Agent 可以被 API 调用或在对话面板中使用。

**Acceptance Criteria:**

**Given** Agent 配置已完成
**When** 用户点击"发布"
**Then** Agent 状态变为"已发布"，出现在 Agent 可用列表中
**And** 已发布的 Agent 可被 API 调用或在对话中选择使用
**And** 发布后编辑配置保存时创建新版本，不影响运行中的对话
**And** Agent 详情页展示版本历史和当前版本号
**And** 支持下架操作，下架后新调用拒绝，已有对话不受影响

### Story 2.6: Agent 对话测试界面

As a 开发者/操作员，
I want 在 Agent 创建或发布后可直接通过对话界面与之交互，
So that 开发者可以测试 Agent 行为，操作员可以使用 Agent 能力。

**Acceptance Criteria:**

**Given** Agent 已创建或已发布
**When** 用户进入对话界面并选择该 Agent
**Then** 展示对话输入框和历史消息列表
**And** 发送消息后以流式方式展示 AI 回复（青色脉冲点 + 逐 token 输出）
**And** Agent 调用工具时展示工具调用可视化（工具名称、输入参数、返回结果）

**Given** 用户发送多条消息
**When** 对话持续进行
**Then** 对话自动保存到历史记录
**And** 侧边栏展示最近对话列表，支持切换和继续对话

**Given** Agent 触发工作流
**When** 工作流开始执行
**Then** 对话界面显示工作流触发状态和进度

**Given** 对话出现错误
**When** Agent 调用失败或超时
**Then** 对话界面展示错误提示，包含可执行的建议（如重试）

### Epic 3: 工具系统
开发者可通过三种来源注册 Skill、配置 MCP 连接自动发现工具。所有工具在工具池统一管理，Agent 不感知来源差异。
**FRs 覆盖:** FR-13（Skill 管理三来源）、FR-14（MCP 连接管理）、FR-15（工具池与统一接口）
**架构覆盖:** `engine/tool/{registry,mcp_client,skill_runner,sandbox}`、`api/v1/tools/{skills,mcp,discover}`、`features/tool_registry/`

### Story 3.1: Skill 管理与注册

As a 开发者，
I want 通过三种来源（内建/Python/MCP）注册和管理 Skill，包含版本控制，
So that 可以集中管理所有工具能力，Agent 运行时统一调用。

**Acceptance Criteria:**

**Given** 开发者进入工具管理页面
**When** 点击"注册 Skill"
**Then** 支持三种注册来源：
- **内建 Skill** — 平台预置的通用工具（如文件搜索、代码执行），开箱即用
- **Python Skill** — 上传 Python 脚本，平台解析函数签名自动生成工具接口
- **MCP Skill** — 配置 MCP 服务地址，自动发现并注册工具列表

**Given** Skill 已注册
**When** 开发者查看 Skill 列表
**Then** 列表展示：名称、来源类型、版本号、状态、最后更新時間
**And** 支持按来源类型过滤和按名称搜索
**And** 支持查看 Skill 详情（输入参数 Schema、输出格式、示例）

**Given** Skill 需要更新
**When** 开发者上传新版本
**Then** 系统自动递增版本号，保留历史版本（可回滚）
**And** 使用旧版本的运行中 Agent 不受影响

### Story 3.2: MCP 连接管理

As a 开发者，
I want 配置 MCP 服务连接，自动发现并管理通过 MCP 协议暴露的工具，
So that 外部系统（MES、ERP）的能力可通过 MCP 快速集成到平台。

**Acceptance Criteria:**

**Given** 开发者进入 MCP 管理页面
**When** 点击"添加 MCP 服务"
**Then** 需要配置：服务名称、URL/地址、认证方式（无/API Key/Basic）、超时时间
**And** 配置完成后点击"连接测试"，验证服务可达

**Given** MCP 服务连接成功
**When** 系统自动调用 MCP 发现接口
**Then** 自动拉取该服务暴露的所有工具列表
**And** 每个工具的输入输出 Schema 自动解析并注册到工具池
**And** 如有工具更新，MCP 重连时自动同步

**Given** MCP 服务连接断开
**When** 健康检查失败
**Then** 系统按指数退避策略自动重连（初始 5s，最大 5min）
**And** MCP 来源的工具标记为"不可用"，但保留注册信息
**And** Agent 调用时返回明确的"MCP 服务不可达"错误

### Story 3.3: 工具池与统一调用封装

As a 开发者，
I want Skill 和 MCP 工具在工具池中统一管理，通过一致接口调用，
So that Agent 不感知工具来源差异，调用方只需关心输入输出格式。

**Acceptance Criteria:**

**Given** 多种来源的工具已注册到工具池
**When** 开发者查看工具池
**Then** 工具列表统一展示，每个工具标注来源（内建/Python/MCP）
**And** 每个工具包含：名称、描述、输入参数 Schema（JSON Schema）、输出格式、示例

**Given** Agent 调用工具
**When** Agent 选择工具并传入参数
**Then** 工具层统一进行参数校验（按 JSON Schema 校验）
**And** 不同来源的工具走对应执行路径
**And** 结果统一格式化为标准响应结构

**Given** 工具调用失败
**When** 执行异常
**Then** 错误信息统一包装，包含错误类型、错误消息、来源信息
**And** 调用方可根据错误类型决定重试或降级

### Story 3.4: Agent 工具绑定与运行时注入

As a 开发者，
I want 在 Agent 配置中选择工具，运行时自动注入到 Agent 的 System Prompt，
So that Agent 能感知可用的工具集并在推理中调用。

**Acceptance Criteria:**

**Given** 开发者进入 Agent 编辑页面
**When** 在能力配置中进入工具选择
**Then** 展示工具池中的所有工具，支持多选
**And** 已选择的工具高亮展示，支持搜索快速定位
**And** 工具被删除时，引用该工具的 Agent 在保存时提示警告

**Given** Agent 已配置工具并发布
**When** Agent 启动运行时
**Then** 绑定的工具描述自动注入到 System Prompt
**And** 工具调用的函数签名自动映射为 Agent 可调用的函数格式

**Given** Agent 绑定的工具有变更
**When** Agent 重新加载配置
**Then** System Prompt 中的工具描述同步更新
**And** 已有对话不受影响（使用旧配置）

### Story 3.5: 工具执行沙箱与超时熔断

As a 开发者，
I want 工具执行在隔离沙箱中，有超时控制和熔断保护，
So that 单个工具异常不会影响 Agent 和其他工具的正常运行。

**Acceptance Criteria:**

**Given** Agent 调用工具
**When** 工具执行
**Then** 内建/Python 工具在隔离环境执行（子进程/沙箱容器）
**And** 每个工具有独立的超时配置（默认 30s，MCP 工具可单独配置）

**Given** 工具连续失败超过阈值
**When** 错误率超过配置阈值（默认 5 次中 3 次失败）
**Then** 触发熔断，后续调用直接返回"工具暂时不可用"
**And** 熔断恢复后渐进放开并发（先 1 个请求探测，逐步增加）
**And** 熔断状态记录到监控日志

**Given** 大量工具同时被调用
**When** 并发数超过系统限制
**Then** 超出部分排队等待，不拒绝
**And** 排队时间超过超时时间则超时失败

### Epic 4: 工作流编排
开发者可以可视化编辑 DAG 工作流，配置 8 种核心节点和条件边，工作流发布后可作为 Agent 能力被调用。支持版本管理和模板快照。
**FRs 覆盖:** FR-9（DAG 编辑器）、FR-10（8 种核心节点）、FR-11（条件边配置）、FR-12（版本管理）、FR-12A（模板管理 DB+文件双写 + semver）、FR-24（变量池与表达式注入）、FR-22（Node 上下文）
**架构覆盖:** `engine/workflow/{builder,executor,nodes/}`（Strategy 模式 8 种节点）、`engine/task/variable_pool.py`、`engine/task/expression.py`（jinja2 sandbox）、`api/v1/workflows/`、`features/workflow_editor/`、@xyflow/react
**UX 覆盖:** 编辑器全屏布局（UX-DR7）、节点调色板拖放/连线/复制粘贴/撤销（UX-DR19）、节点状态可视化（UX-DR21）

### Story 4.1: 工作流数据模型与后端 CRUD API

As a 开发者，
I want 工作流的数据模型包含节点和边的定义，并通过 REST API 进行增删改查，
So that 工作流编辑器前端和 Workflow 执行引擎可以基于这些 API 工作。

**Acceptance Criteria:**

**Given** 平台后端已部署
**When** 开发者通过 API 创建工作流（传入 name、description、nodes、edges）
**Then** Workflow 记录写入 MongoDB，包含 name、description、nodes[]（node_id、type、config）、edges[]（source、target、condition）、status、version
**And** 支持 8 种节点类型：start、end、agent、tool、human、gateway、parallel、subflow，各有独立 config schema
**And** 支持查询列表（分页）、获取详情、更新、删除
**And** 保存时校验 DAG 合法性（无环、start/end 节点存在、必需参数填写）
**And** 每次保存自动递增版本号

### Story 4.2: DAG 工作流可视化编辑器

As a 开发者，
I want 通过拖拽方式在画布上构建 DAG 工作流，
So that 我可以直观地编排多步骤执行流程，无需编写代码。

**Acceptance Criteria:**

**Given** 用户拥有开发者角色
**When** 用户进入工作流编辑器页面
**Then** 展示左侧节点调色板（8 种节点类型）+ 中央画布 + 右侧参数面板
**And** 用户可从调色板拖拽节点到画布，节点间连线（output handle → input handle）
**And** 编辑器检测并阻止环路创建，给出提示
**And** 支持缩放、平移、自动布局、多选（Shift+click）
**And** 支持撤销/重做（Cmd+Z / Cmd+Shift+Z，深度 50 步）
**And** 保存时验证所有必需节点参数是否已填写

### Story 4.3: 核心节点配置面板

As a 开发者，
I want 在编辑器中为每种节点类型配置独立的参数，
So that 节点在运行时按配置执行（Agent 推理、Tool 调用、Human 审批、Gateway 分支等）。

**Acceptance Criteria:**

**Given** 用户在编辑器画布中放置了节点
**When** 用户点击节点或在右侧参数面板中
**Then** 展示该节点类型对应的配置表单
**And** agent 节点：可选择已创建的 Agent、覆盖提示词、配置 temperature/max_retry
**And** tool 节点：可选择工具、配置参数、设置 timeout_ms/retry_policy
**And** human 节点：配置超时时间、升级路径（escalation）、默认动作
**And** gateway 节点：配置条件表达式列表、默认分支（default_branch）、fallback_on_error
**And** parallel 节点：配置分支列表、join_strategy（all/any/n-of-m）、scope（shared/isolated）
**And** subflow 节点：选择目标 Workflow、配置 input_mapping 和 result_mapping

### Story 4.4: 条件边配置

As a 开发者，
I want 为工作流中的边配置条件表达式，
So that 执行时可根据上游节点输出或变量值动态选择执行路径。

**Acceptance Criteria:**

**Given** 用户在编辑器中选中一条边
**When** 用户在右侧面板配置条件表达式
**Then** 支持两种条件类型：节点输出判断（`{{node_id.field}}` 引用）和数据条件（变量表达式）
**And** 表达式引擎内置 try-catch，语法错误不传播到引擎级
**And** 变量未定义时视为 `false`，走 `fallback_on_error` 分支
**And** Gateway 节点可配置多条条件边，运行时按顺序匹配第一条满足的
**And** 所有条件都不满足时走 default_branch

### Story 4.5: 工作流版本管理与模板发布

As a 开发者，
I want 管理工作流的版本历史，发布后供 Agent 调用，
So that 工作流的变更可控，已创建的 Task 不受模板更新影响。

**Acceptance Criteria:**

**Given** 开发者编辑并保存工作流
**When** 保存时自动创建新版本（semver 格式 v1.0.0 → v1.1.0）
**Then** 历史版本在列表中可查看但不可编辑
**And** 发布后工作流可被 Agent 绑定和调用
**And** Agent 绑定的是指定的已发布版本
**And** Task 创建时绑定当前模板快照，模板更新不影响已创建的 Task
**And** 提供 `migrate_task` 接口将运行中 Task 升级到新版本（需节点级兼容性检查）

### Story 4.6: 工作流执行与基础运行

As a 开发者，
I want 工作流发布后可以被执行，
So that 节点按 DAG 顺序依次运行并传递变量。

**Acceptance Criteria:**

**Given** 工作流已发布
**When** 触发工作流执行（传入 input_schema 定义的变量）
**Then** Workflow 引擎按 DAG 拓扑排序执行节点，从 start 开始到 end 结束
**And** 每个节点执行完成后输出写入变量池，供下游节点通过 `{{node_id.field}}` 引用
**And** agent/tool 节点执行业务逻辑，human 节点进入 waiting_human 状态
**And** gateway 根据条件表达式选择分支，parallel 并行执行多分支
**And** subflow 创建子 Task 执行，等待结果返回
**And** 执行日志记录每个节点的输入输出和耗时

### Epic 5: Agent 自主执行引擎
Agent 收到任何输入后可自主判断大小并选择执行路径：直接执行（REACT）、规划执行（计划→执行→验证）、工作流执行（创建 Task）。对话可触发工作流。
**FRs 覆盖:** FR-4（Job 评估与路径选择）、FR-5（直接执行 REACT）、FR-6（规划执行三阶段）、FR-7（工作流执行模式）、FR-8（深度与循环保护）、FR-21（对话触发工作流）、FR-22A（对话上下文压缩）、FR-22（Session 上下文）、FR-23（Task 触发对话）
**架构覆盖:** `engine/agent/{direct,react,planner}_executor`、`depth_guard`、`features/execution_engine/`、`engine/task/context.py`（Session）
**UX 覆盖:** 流式输出青色脉冲点（UX-DR21）、工具调用可视化

### Story 5.1: Agent 执行引擎基础框架

As a 开发者，
I want Agent 执行引擎提供统一的 StateGraph 构建和三种执行模式的骨架，
So that Agent 可以根据 Job 类型选择不同的执行策略。

**Acceptance Criteria:**

**Given** Agent 已发布且配置完成
**When** Agent 收到执行请求
**Then** 引擎构建 StateGraph，注入 Agent 的提示词、工具列表、Workflow Registry
**And** 引擎根据输入评估选择执行路径（direct/react/planner）
**And** 执行状态通过 MongoDBSaver 持久化
**And** 支持同步和流式两种输出模式
**And** 所有执行步骤记录到执行日志（含 request_id 全链路串联）

### Story 5.2: 直接执行模式（REACT）

As a 开发者，
I want Agent 在简单 Job 时按 REACT 模式直接推理并调用工具返回结果，
So that 简单问答和单步操作快速响应，不经过复杂的规划流程。

**Acceptance Criteria:**

**Given** Agent 收到一个简单 Job（如问答、单步查询）
**When** Agent 评估后选择直接执行模式
**Then** Agent 按 REACT 循环（Reasoning + Acting）推理
**And** Agent 可自主调用已配置的工具获取数据
**And** 每步推理过程和工具调用结果记录在执行日志中
**And** 流式输出推理过程和最终结果
**And** Agent 无法完成任务时返回明确的失败原因

### Story 5.3: 规划执行模式

As a 开发者，
I want Agent 在复杂 Job 时进入"计划→执行→验证"三阶段执行，
So that 多步骤任务有条理地执行，中间结果可调整，最终结果经过验证。

**Acceptance Criteria:**

**Given** Agent 收到一个复杂多步骤 Job
**When** Agent 评估后选择规划执行模式
**Then** Agent 先生成结构化执行计划（列出步骤、工具、预期输出）
**And** 按计划逐步执行，每步结果记录日志
**And** 执行过程中 Agent 可根据中间结果调整后续计划
**And** 执行完成后进入验证阶段，检查结果是否满足原始 Job 要求
**And** 验证不通过时 Agent 可补充执行或调整方案
**And** 执行日志展示计划、实际执行步骤和验证结果三部分

### Story 5.4: 工作流执行模式

As a 开发者，
I want Agent 在需要固定流程时创建 Task 并按工作流模板执行，
So that 标准化流程（如质检报告生成、设备巡检）可靠且可审计。

**Acceptance Criteria:**

**Given** Agent 收到一个适合工作流执行的 Job
**When** Agent 通过 Search Workflow 工具发现匹配的工作流模板
**Then** Agent 调用 Create Task 工具创建工作流 Task
**And** Agent 将 Job 参数映射到工作流 input_schema
**And** Agent 持续查询 Task 执行进度（Task Query 工具）
**And** Task 执行结果返回给 Agent，Agent 进行最终回复
**And** 执行过程中 Agent 可根据需要介入调整 Task 变量

### Story 5.5: 调用深度与循环保护

As a 开发者，
I want 平台限制 Agent→Workflow→Agent 的嵌套深度并检测循环调用，
So that 系统不会因无限递归或过深嵌套导致资源耗尽。

**Acceptance Criteria:**

**Given** Agent 在执行过程中触发工作流 Task
**When** 工作流中包含 Agent 节点且该 Agent 再次触发工作流
**Then** 平台记录调用深度（Agent→Workflow→Agent 计为 2 层）
**And** 嵌套深度达到 3 层时平台拒绝继续创建新 Task 并返回错误提示
**And** 平台检测到循环调用（同一 Agent 被重复触发）时自动终止
**And** 错误信息中包含调用链路径，便于开发者排查
**And** 执行日志中每层嵌套以缩进方式展示调用关系

### Story 5.6: 对话触发工作流

As a 操作员，
I want 在对话中自然触发工作流并看到实时进度，
So that 日常操作可通过对话完成而不需要手动创建工作流。

**Acceptance Criteria:**

**Given** 操作员在对话中与 Agent 交互
**When** Agent 判断需要触发工作流
**Then** 对话界面显示工作流触发状态（"正在创建工作流任务..."）
**And** 工作流开始执行后对话界面展示进度条或实时状态更新
**And** 工作流中出现人工审批节点时对话界面展示审批卡片
**And** 操作员可直接在对话中完成审批/驳回操作
**And** 工作流完成后 Agent 汇总结果回复给操作员
**And** 整个对话历史包含工作流执行摘要

### Epic 6: Task 生命周期管理
Task 作为 Workflow 运行时实例，拥有完整状态机。用户和 Agent 可管理 Task 全生命周期：创建、前后台切换、进度查询、人工审批/驳回/跳过/暂停/恢复/取消、运行时变量修正。Agent 通过能力地图前置感知所有 Workflow。
**FRs 覆盖:** FR-29（Task 状态机 7 状态 16 转换）、FR-30（前后台模式 30s 自动转后台）、FR-31（流程干预 8 种操作 + 乐观锁）、FR-32（Agent 9 种 Task 系统工具）、FR-33（能力地图 Workflow Registry）、FR-22（Task 上下文）、FR-25（执行日志全量记录 + 审计）、FR-26（调用链追踪）
**架构覆盖:** `engine/task/{state_machine,executor,variable_pool,expression,context,intervention,foreground,audit}`、`api/v1/tasks/{crud,intervene,timeline,query}`、`services/workflow_registry.py`、`features/task_management/`、`features/execution_logs/`
**UX 覆盖:** Task 管理面板（UX-DR25）、状态徽章（UX-DR13）、human 审批卡片

### Story 6.1: Task 状态机与数据模型

As a 开发者，
I want 平台定义 Task 的完整状态机（7 状态、16 转换）、数据模型和 CRUD API，
So that 所有 Task 有统一的生命周期管理基础。

**Acceptance Criteria:**

**Given** 平台定义了 Task 状态机
**When** Task 执行过程中触发状态转换
**Then** 仅允许 16 种合法转换：`pending→running, running→waiting_human, running→paused, running→completed, running→failed, waiting_human→running, paused→running, paused→failed, completed→(terminal), failed→(terminal), cancelled→(terminal)`
**And** 非法转换被拒绝并返回 409 Conflict

**Given** Task MongoDB 数据模型已定义
**When** 开发者调用 Task CRUD API
**Then** Task 数据模型包含：`task_id, workflow_id, template_version, status, input, output, variables, context_ids, created_by, created_at, updated_at, version(乐观锁)`
**And** 新创建的 Task 默认进入 `pending` 状态

**Given** 并发干预 Task
**When** 两个请求同时操作同一 Task
**Then** 后提交的请求因 version 不匹配返回 409 Conflict
**And** 提示"请重新获取最新状态后重试"

### Story 6.2: Workflow Registry 与能力地图

As a 开发者，
I want Agent 在启动时通过 Workflow Registry 前置感知所有绑定工作流的元信息（用途、输入结构、人工节点标识、副作用说明），
So that Agent 在运行中能自主判断何时触发哪个工作流。

**Acceptance Criteria:**

**Given** 开发者发布了一个工作流模板
**When** 发布完成
**Then** 该工作流的注册信息写入 Workflow Registry
**And** 注册信息包含：`workflow_id, name, description/when_to_use, input_schema, required_entities[], has_human_node, side_effects[], tags[]`

**Given** Agent 启动或配置变更
**When** Agent 绑定的工作流发生变化
**Then** Agent 的 System Prompt 自动注入绑定工作流的注册信息摘要
**And** 摘要是结构化文本格式，Agent 可通过 Search Workflow 工具进一步查询详情

**Given** Workflow Registry 中有数据
**When** Agent 调用 Search Workflow 工具
**Then** Agent 可按关键词、标签、输入结构搜索匹配的工作流
**And** 搜索结果包含工作流的完整注册信息

### Story 6.3: 前后台执行模式

As a 开发者，
I want Task 支持前台同步等待和后台异步执行两种模式，前台 30 秒超时后自动转后台，
So that 短任务可以实时等结果，长任务不会阻塞前端。

**Acceptance Criteria:**

**Given** 用户触发一个 Task
**When** 创建 Task 时 mode 设置为 `foreground`
**Then** 前端通过 WebSocket 连接实时接收执行状态和结果推送
**And** 前台模式超时时间默认 30 秒（可配置）

**Given** Task 前台执行超过 30 秒
**When** 超时触发
**Then** Task 自动转为 `background` 模式继续执行
**And** 前端收到切换通知，展示"任务已转后台执行"提示
**And** 用户可随时通过 Task 管理面板查看进度

**Given** 用户创建 Task 时指定 `background` 模式
**When** Task 创建成功
**Then** 后端立即返回 `task_id` 和 `status: pending`
**And** 前端显示"后台任务已启动，正在执行..."
**And** 用户可关闭页面，Task 继续执行

### Story 6.4: 流程干预 REST API

As a 开发者/操作员，
I want 通过 REST API 对运行中的 Task 执行 8 种干预操作（审批、驳回、暂停、恢复、取消、跳过、重试、修改变量），
So that Task 执行过程中可人工介入处理异常情况。

**Acceptance Criteria:**

**Given** 一个 Task 处于可干预状态
**When** 用户调用 `POST /api/v1/tasks/{task_id}/intervene`
**Then** 干预请求包含干预类型和 version 乐观锁
**And** 支持以下干预操作：`approve`, `reject`, `skip`, `retry`, `pause`, `resume`, `cancel`, `update_variables`
**And** 每种干预操作仅在合法状态可用（如 pause 仅 running 状态可用）

**Given** 干预请求的 version 与当前 Task 不匹配
**When** 并发冲突发生
**Then** 返回 409 Conflict，提示"请重新获取最新状态后重试"
**And** 响应中包含 Task 最新 status 和 version

**Given** 干预操作成功执行
**When** 状态转换完成
**Then** 审计日志记录：操作人、操作类型、操作时间、操作前后状态
**And** WebSocket 推送状态变更通知到相关前端

### Story 6.5: Agent 系统级 Task 工具

As a 开发者，
I want Agent 拥有一组系统级工具（9 个）在运行时管理和查询 Task，
So that Agent 能自主创建 Task、跟踪进度、介入调整、收集结果。

**Acceptance Criteria:**

**Given** Agent 被创建
**When** Agent 启动
**Then** 以下系统级 Task 工具自动注入 System Prompt：
- `search_workflow(query)` — 搜索匹配的工作流
- `get_workflow_schema(id)` — 获取工作流 input_schema
- `create_task(workflow_id, input)` — 创建 Task
- `task_query(task_id)` — 查询 Task 状态和结果
- `task_intervene(task_id, action)` — 干预 Task（重试/取消/修改变量）
- `task_list(filter)` — 列出当前 Agent 的 Task
- `cancel_task(task_id)` — 取消指定 Task
- `get_task_timeline(task_id)` — 获取 Task 执行时间线
- `update_task_variables(task_id, variables)` — 修改变量池

**Given** Agent 调用 create_task
**When** 参数校验通过
**Then** 后端创建 Task，返回 task_id 和 status
**And** Agent 可通过 task_query 轮询进度或通过 WebSocket 接收推送

**Given** Agent 调用 task_intervene 或 cancel_task
**When** 操作成功
**Then** 审计日志记录 Agent 的干预操作

### Story 6.6: 人工审批节点

As a 操作员，
I want 工作流执行到人工节点时收到通知，在对话或页面中完成审批/驳回/跳过操作，
So that 需要人工判断的环节不会遗漏，超时也有自动降级处理。

**Acceptance Criteria:**

**Given** 工作流执行到 Human 节点
**When** Task 进入 `waiting_human` 状态
**Then** 系统发送通知给相关操作员
**And** 对话界面展示审批卡片（请求内容、上下文、审批/驳回/跳过按钮）
**And** Task 管理面板显示该 Task 处于"等待人工"状态

**Given** 操作员在对话或管理面板操作
**When** 操作员点击"审批"或"驳回"
**Then** 调用 Task 干预 API，Task 继续执行或进入 failed 状态
**And** 审计日志记录操作人、操作类型、操作时间

**Given** Human 节点配置了 `timeout_ms` 和 `timeout_action`
**When** 超时仍未收到人工操作
**Then** 按配置执行超时动作：`fail`（Task 失败）/ `skip`（跳过继续）/ `default_branch`（走默认分支）
**And** 审计日志记录"人工节点超时，执行 timeout_action"

**Given** Human 节点还配置了 `escalation`
**When** 超时且 timeout_action 执行后仍有降级需求
**Then** 执行 escalation 定义的动作（使用默认值/调用备用服务/发送告警到指定渠道）

### Epic 7: 知识库管理 — 🔴 DEFERRED
*用户可创建知识库、上传文档、Agent 运行时检索知识辅助推理。*
**FRs 覆盖:** FR-16（知识库创建与文档管理）、FR-17（知识库检索）
**状态:** 主人 2026-06-08 确认 MVP 暂不考虑，post-MVP Sprint 2 评估

### Epic 8: 外部 API 集成
外部系统（MES/ERP/BI）通过 REST API 和 Webhook 集成平台，调用 Agent 能力。
**FRs 覆盖:** FR-18（Agent 调用 API 同步/异步）、FR-19（事件回调 Webhook + HMAC 签名）
**架构覆盖:** `api/v1/api_keys/`、`api/v1/callbacks/`、`features/api_sdk/`
**UX 覆盖:** API Key 管理流（UX-DR24）

### Story 8.1: API Key 管理

As a 管理员，
I want 创建和管理 API Key，限定作用域和权限，
So that 外部系统可以通过安全的 API Key 调用 Agent 能力。

**Acceptance Criteria:**

**Given** 管理员进入 API Key 管理页面
**When** 点击"创建 API Key"
**Then** 输入名称、选择作用域（agents:invoke, executions:read）和过期时间
**And** 点击"生成"后 Key **一次性展示**在模态框中
**And** 提供复制按钮，提示"请妥善保存，不会再次显示"

**Given** API Key 已创建
**When** 管理员查看 Key 列表
**Then** 列表展示：名称、前缀（前 8 位）、作用域、创建時間、过期时间、状态
**And** Key 值仅创建时展示一次，列表中不显示完整 Key

**Given** API Key 泄露或不再需要
**When** 管理员点击"吊销"
**Then** 确认后 Key 立即失效
**And** 使用该 Key 的请求返回 401 Unauthorized

### Story 8.2: Agent 调用 REST API

As a 开发者，
I want 通过 REST API 同步或异步调用 Agent，携带 API Key 认证，
So that 外部系统（MES/ERP/BI）可以通过 HTTP 集成 Agent 能力。

**Acceptance Criteria:**

**Given** 外部系统持有有效 API Key
**When** 调用 `POST /api/v1/agents/{agent_id}/invoke` 并传入 `mode=sync`
**Then** 请求在超时时间内（默认 30s）同步等待 Agent 执行完成
**And** 返回完整的 Agent 响应结果

**Given** 外部系统调用 `mode=async`
**When** 请求提交成功
**Then** 立即返回 `task_id` 和 `status: pending`
**And** 外部系统可通过 `GET /api/v1/tasks/{task_id}` 轮询结果
**And** 如配置了 Webhook，执行完成后自动推送结果

**Given** 请求使用无效或已吊销的 API Key
**When** API 调用
**Then** 返回 401 Unauthorized
**And** 错误信息不透露具体原因（防止枚举攻击）

### Story 8.3: Webhook 事件回调

As a 开发者，
I want 配置 Webhook 在 Agent/Task 事件发生时自动回调外部系统，
So that 外部系统可以实时接收 Agent 执行结果和处理状态变更。

**Acceptance Criteria:**

**Given** 开发者在 API Key 管理页面配置 Webhook
**When** 点击"添加回调"
**Then** 配置：回调 URL、事件类型（agent.completed, agent.failed, task.completed, task.failed）、HMAC 密钥
**And** 点击"测试"按钮发送模拟回调，验证端点可达

**Given** Agent/Task 事件触发
**When** 事件发生时
**Then** 系统向所有订阅了该事件的 Webhook URL 发送 POST 请求
**And** 请求体包含事件类型、时间戳、payload（执行结果/状态）
**And** 请求头包含 HMAC 签名，供接收方验证请求合法性

**Given** Webhook 回调失败
**When** 目标 URL 返回非 2xx 状态码
**Then** 系统按指数退避策略重试（初始 1s，最大 30s，最多 5 次）
**And** 超出重试次数后记录到 Webhook 投递失败日志
**And** 管理页面展示 Webhook 投递状态和失败记录
