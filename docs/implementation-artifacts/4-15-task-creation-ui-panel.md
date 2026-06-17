# Story 4.15: Task 创建 UI 面板

**Epic:** Epic 4 — DAG 工作流编排 + Task 运行时
**Status:** ready-for-dev
**Story ID:** 4-15
**Story Key:** 4-15-task-creation-ui-panel

## Story

As a 操作员/开发者，
I want 通过 Web 界面创建一个 Task，选择工作流模板、填写输入参数、查看执行状态，
So that 我可以不通过 Agent 直接在网页上创建和管理 Task。

> ⚠️ **关键背景**：Task 面板是用户与 Task 运行时系统交互的主要入口。
> 用户可以通过三种方式创建 Task：
> 1. **Task 面板** — 直接在工作流详情页或 Task 管理页创建
> 2. **Agent 对话** — Agent 询问用户确认后创建
> 3. **定时调度** — 系统自动按 cron 创建（Story 4-13）
>
> 本 Story 实现方式 1 — Task 面板的创建和管理 UI。
> Task 面板使用 Ant Design 组件，嵌入到工作流详情页和独立 Task 管理页面。

## Acceptance Criteria

### AC1: Task 管理页面
**Given** 用户访问 Task 管理页面（`/tasks`）
**When** 页面加载
**Then** 展示 Task 列表，列包含：ID 前缀、工作流名称、状态（状态徽章）、创建者、创建时间、操作按钮
**And** 列表支持分页（20 条/页），按状态筛选（全部/pending/running/waiting_human/completed/failed/cancelled）
**And** 支持按工作流名称搜索
**And** 加载中展示骨架屏，空状态时展示"还没有 Task"提示 + "创建第一个 Task"按钮
**And** 接口失败展示错误提示 + 重试按钮

### AC2: Task 创建模态框
**Given** 用户点击"创建 Task"按钮
**When** 模态框打开
**Then** 展示多步创建流程：

**Step 1 — 选择工作流：**
- 展示已发布的工作流列表（卡片式，含名称、描述、tags、has_human_node 标记）
- 支持搜索和按标签筛选
- 选中后显示该工作流的简要信息

**Step 2 — 填写输入参数：**
- 根据所选工作流的 input_schema 动态生成表单
- 支持 JSON 直接编辑（适合复杂输入）和表单项模式（适合简单输入）
- 标记必填字段
- 参数校验（按 Schema 类型约束）

**Step 3 — 确认提交：**
- 展示 Task 创建摘要（工作流名称、输入参数概览、是否含人工审批节点）
- 如果工作流包含 human 节点，展示黄色提示："该工作流包含人工审批节点"
- 点击"创建"后调用 `POST /api/v1/tasks`
- 创建成功后模态框关闭，Task 出现在列表中

**And** 点击"取消"或在遮罩层点击时弹出确认提示（"确定取消创建吗？"）

### AC3: Task 详情面板
**Given** 用户在 Task 列表中点击某 Task
**When** 详情面板打开（Drawer 或 Modal）
**Then** 展示以下信息：
**基本信息：** 状态徽章、工作流名称、创建者、创建时间、更新时间、版本号
**输入/输出：** 格式化 JSON 展示 input 和 output
**变量池：** 键值对表格展示当前变量池（节点名 → 输出摘要）
**执行时间线：** 时间线组件展示执行事件（按时间倒序，含事件类型、时间、节点名）
**错误信息（如有）：** 红色错误卡片展示错误信息

### AC4: Task 干预操作
**Given** 用户在 Task 详情面板中
**When** Task 处于可干预状态
**Then** 根据当前状态展示不同的操作按钮：

| 状态 | 可用操作 |
|------|---------|
| pending | 取消 |
| running | 暂停、取消 |
| waiting_human | 审批、驳回、跳过 |
| paused | 恢复、取消 |
| failed | 重试（如可重试） |
| completed | 无 |
| cancelled | 无 |

**And** 操作前弹出确认对话框（含操作说明）
**And** 操作成功后详情面板更新状态
**And** 操作失败（如版本冲突 409）展示错误提示"状态已变更，请刷新后重试"

### AC5: 工作流详情页内的 Task 面板
**Given** 用户在工作流详情页（`/workflows/{id}`）
**When** 查看该工作流的 Task 列表
**Then** 展示该工作流关联的 Task 列表（精简版，仅最近的 20 条）
**And** 提供"创建 Task"快捷按钮，自动选中当前工作流（跳过 Step 1）
**And** 提供"查看全部"链接跳转到 Task 管理页面（带工作流筛选参数）

### AC6: 实时状态更新
**Given** 用户在 Task 管理页面或详情面板
**When** Task 状态变更
**Then** 运行中的 Task（pending/running/waiting_human）每 5 秒自动轮询更新
**And** 状态变更时列表项和详情面板同步更新
**And** 状态变更时展示 Toast 提示（"Task #{id} 状态已更新：running"）
**And** Task 变为终态后停止轮询

## Key Files

| 文件 | 操作 |
|------|------|
| `frontend/src/pages/tasks-page.tsx` | **新建** — Task 管理列表页 |
| `frontend/src/pages/task-detail-page.tsx` | **新建** — Task 详情页面 |
| `frontend/src/components/task-create-modal.tsx` | **新建** — Task 创建模态框（三步流程） |
| `frontend/src/components/task-detail-panel.tsx` | **新建** — Task 详情 Drawer 面板 |
| `frontend/src/components/task-timeline.tsx` | **新建** — 执行时间线组件 |
| `frontend/src/services/task-api.ts` | **新建** — Task API 服务 |
| `frontend/src/routes/index.tsx` | **改造** — 添加 Task 页面路由 |
| `backend/app/api/v1/workflows.py` | **改造** — 添加工作流 Task 列表端点 |
