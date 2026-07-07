# Workflow 定时触发系统设计文档

**日期:** 2026-07-07
**状态:** 设计中
**决策人:** Logan_hu

---

## 1. 概述

### 1.1 目标

为 Workflow 引擎添加定时触发能力，支持：
- **重复执行**：基于 Cron 表达式的定期触发（如"每天 9 点"）
- **一次性执行**：指定时间点触发（如"2026-07-10 14:00"）

### 1.2 非目标

- Workflow 版本管理系统（当前使用最新版本）
- 复杂的触发条件（事件触发、依赖触发等）
- 分布式调度（单实例 Celery Beat）

---

## 2. 技术决策

### 2.1 核心决策

| 决策点 | 选择 | 理由 |
|--------|------|------|
| 调度机制 | Celery Beat 动态注册 | 复用现有基础设施，成熟稳定 |
| 触发配置存储 | Workflow 模型字段 | 简单，后续需要再拆分 |
| 版本一致性 | 始终使用最新 Workflow | MVP 简单模式，后续实现版本化 |
| Cron 表达式 | 前端可视化构建器生成 | 降低用户门槛 |
| 时区处理 | 固定 UTC，前端转换 | 简化后端逻辑 |
| 默认参数 | 支持 Jinja2 模板 | 灵活，可动态填充（如 `{{ now() }}`） |

### 2.2 触发类型

| 类型 | 标识 | 用途 |
|------|------|------|
| Cron 重复 | `cron` | 按 Cron 表达式定期执行 |
| 一次性 | `once` | 指定时间点执行一次 |

---

## 3. 数据模型设计

### 3.1 Workflow 模型扩展

在现有 `Workflow` 模型中新增 `trigger_config` 字段：

```python
from typing import Any
from pydantic import BaseModel, Field
from datetime import datetime

class TriggerConfig(BaseModel):
    """Workflow 定时触发配置"""

    type: str  # "cron" | "once"
    enabled: bool = False
    cron_expression: str | None = None  # Cron 表达式（type=cron 时必填）
    execute_at: datetime | None = None  # 执行时间（type=once 时必填）
    default_input: dict[str, Any] = Field(default_factory=dict)
    # 默认输入参数，支持 Jinja2 模板语法
    # 例: {"date": "{{ now() }}", "department": "engineering"}
    last_triggered_at: datetime | None = None  # 上次触发时间
    next_trigger_at: datetime | None = None  # 下次触发时间（计算得出）
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

class Workflow(BaseModel):
    # ... 现有字段 ...
    trigger_config: TriggerConfig | None = None
```

### 3.2 MongoDB 文档示例

```json
{
  "_id": "wf_xxx",
  "name": "每日数据报告",
  "trigger_config": {
    "type": "cron",
    "enabled": true,
    "cron_expression": "0 9 * * *",
    "execute_at": null,
    "default_input": {
      "date": "{{ now() }}",
      "department": "engineering"
    },
    "last_triggered_at": "2026-07-07T09:00:00Z",
    "next_trigger_at": "2026-07-08T09:00:00Z",
    "created_at": "2026-07-01T10:00:00Z",
    "updated_at": "2026-07-07T09:00:00Z"
  }
}
```

---

## 4. 后端架构设计

### 4.1 服务层

#### TriggerSchedulerService

负责管理 Celery Beat 调度的动态注册。

```python
class TriggerSchedulerService:
    """定时触发调度服务"""

    async def start(self) -> None:
        """服务启动时初始化调度器"""
        # 1. 扫描所有 trigger_config.enabled=true 的 Workflow
        # 2. 注册到 Celery Beat
        pass

    async def register_trigger(self, workflow_id: str) -> None:
        """注册单个触发任务到 Celery Beat"""
        # Cron 类型 → 添加到 beat_schedule
        # Once 类型 → send_task(eta=execute_at)
        pass

    async def unregister_trigger(self, workflow_id: str) -> None:
        """从 Celery Beat 移除触发任务"""
        pass

    async def update_trigger(self, workflow_id: str) -> None:
        """更新触发配置（先移除再注册）"""
        pass
```

#### 位置

```
backend/app/services/
├── trigger_scheduler_service.py  # 新增：触发调度服务
```

### 4.2 Celery Task

```python
# backend/app/workers/tasks/scheduled_workflow.py

from celery import shared_task
from app.services.task_service import TaskService
from app.engine.workflow.engine import WorkflowEngine

@shared_task
def execute_scheduled_workflow(workflow_id: str) -> dict:
    """定时触发执行 Workflow

    Args:
        workflow_id: Workflow ID

    Returns:
        Task 执行结果摘要
    """
    # 1. 加载 Workflow + trigger_config
    # 2. 渲染 default_input 模板
    # 3. 创建 Task 实例
    # 4. 执行 Workflow
    # 5. 更新 last_triggered_at
    pass
```

### 4.3 API 设计

#### 路由

```
POST   /api/workflows/{workflow_id}/trigger          # 创建/更新触发配置
GET    /api/workflows/{workflow_id}/trigger          # 获取触发配置
DELETE /api/workflows/{workflow_id}/trigger          # 删除触发配置
PATCH  /api/workflows/{workflow_id}/trigger/toggle   # 启用/禁用切换
```

#### 请求/响应示例

**创建触发配置：**
```http
POST /api/workflows/wf_xxx/trigger
Content-Type: application/json

{
  "type": "cron",
  "enabled": true,
  "cron_expression": "0 9 * * *",
  "default_input": {
    "date": "{{ now() }}",
    "department": "engineering"
  }
}
```

**响应：**
```json
{
  "type": "cron",
  "enabled": true,
  "cron_expression": "0 9 * * *",
  "execute_at": null,
  "default_input": {
    "date": "{{ now() }}",
    "department": "engineering"
  },
  "last_triggered_at": null,
  "next_trigger_at": "2026-07-08T09:00:00Z",
  "created_at": "2026-07-07T10:00:00Z",
  "updated_at": "2026-07-07T10:00:00Z"
}
```

**切换启用状态：**
```http
PATCH /api/workflows/wf_xxx/trigger/toggle
Content-Type: application/json

{
  "enabled": false
}
```

### 4.4 模板渲染

`default_input` 支持 Jinja2 模板语法：

```python
from jinja2 import Template
from datetime import datetime, timezone

def render_default_input(default_input: dict) -> dict:
    """渲染默认输入参数模板"""
    context = {
        "now": lambda: datetime.now(timezone.utc).isoformat(),
        "today": lambda: datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }

    rendered = {}
    for key, value in default_input.items():
        if isinstance(value, str) and "{{" in value:
            template = Template(value)
            rendered[key] = template.render(**context)
        else:
            rendered[key] = value

    return rendered
```

**内置模板变量：**
- `{{ now() }}` → 当前 UTC 时间（ISO 格式）
- `{{ today() }}` → 当前日期（YYYY-MM-DD）
- 后续可扩展更多

---

## 5. 前端设计

### 5.1 页面位置

Workflow 详情页新增"定时触发"Tab。

### 5.2 UI 组件

#### TriggerConfigEditor

```
┌─────────────────────────────────────────────────────────┐
│ 定时触发配置                                             │
├─────────────────────────────────────────────────────────┤
│                                                          │
│ 触发类型:                                                │
│   ○ Cron 重复执行                                       │
│   ○ 一次性执行                                          │
│                                                          │
│ ─── Cron 模式 ───                                       │
│                                                          │
│ 执行频率: [下拉选择]                                     │
│   ├── 每小时                                            │
│   ├── 每天 [09:00 ▼]                                    │
│   ├── 每周 [周一 ▼] [09:00 ▼]                           │
│   ├── 每月 [1 ▼ 号] [09:00 ▼]                           │
│   └── 自定义（高级）                                     │
│                                                          │
│ ┌─ 自定义模式（折叠）──────────────────────────────┐   │
│ │ 分: [0 ▼]  时: [9 ▼]  日: [* ▼]  月: [* ▼]  周: [* ▼] │
│ │ 预览: 每天 09:00                                   │   │
│ └──────────────────────────────────────────────────────┘   │
│                                                          │
│ ─── 一次性模式 ───                                      │
│                                                          │
│ 执行时间: [2026-07-10] [14:00] [时区: UTC]              │
│                                                          │
│ ─── 默认输入参数 ───                                    │
│                                                          │
│ ┌────────────┬────────────────────┬──────┐              │
│ │ 参数名     │ 值                 │ 操作 │              │
│ ├────────────┼────────────────────┼──────┤              │
│ │ date       │ {{ now() }}        │  ✕   │              │
│ │ department │ engineering        │  ✕   │              │
│ └────────────┴────────────────────┴──────┘              │
│ [+ 添加参数]                                            │
│                                                          │
│ 提示: 支持模板语法，如 {{ now() }}、{{ today() }}       │
│                                                          │
│ ─── 状态 ───                                            │
│                                                          │
│ 状态: [● 已启用] [切换]                                 │
│ 下次执行: 2026-07-08 09:00 (UTC)                        │
│ 上次执行: 2026-07-07 09:00 (UTC)                        │
│                                                          │
│         [保存]  [删除触发配置]                            │
└─────────────────────────────────────────────────────────┘
```

### 5.3 组件结构

```
frontend/src/components/workflows/
├── TriggerConfigEditor.tsx        # 触发配置编辑器
├── CronPresetSelector.tsx         # Cron 预设选择器
├── CronCustomBuilder.tsx          # Cron 自定义构建器
├── DefaultInputEditor.tsx         # 默认参数编辑器
└── TriggerStatusDisplay.tsx       # 触发状态显示
```

### 5.4 Cron 预设映射

| 预设选项 | 生成的 Cron 表达式 |
|----------|-------------------|
| 每小时 | `0 * * * *` |
| 每天 09:00 | `0 9 * * *` |
| 每周一 09:00 | `0 9 * * 1` |
| 每月 1 号 09:00 | `0 9 1 * *` |
| 自定义 | 用户输入 |

### 5.5 API 调用

```typescript
// frontend/src/services/workflow-trigger-api.ts

export const WorkflowTriggerAPI = {
  // 创建/更新触发配置
  async updateTrigger(workflowId: string, config: TriggerConfig) {
    return request.post(`/api/workflows/${workflowId}/trigger`, config);
  },

  // 获取触发配置
  async getTrigger(workflowId: string) {
    return request.get(`/api/workflows/${workflowId}/trigger`);
  },

  // 删除触发配置
  async deleteTrigger(workflowId: string) {
    return request.delete(`/api/workflows/${workflowId}/trigger`);
  },

  // 切换启用状态
  async toggleTrigger(workflowId: string, enabled: boolean) {
    return request.patch(`/api/workflows/${workflowId}/trigger/toggle`, { enabled });
  },
};
```

---

## 6. 执行流程

### 6.1 完整流程

```
┌─────────────────────────────────────────────────────────────┐
│ 1. 服务启动                                                  │
│    └── TriggerSchedulerService.start()                       │
│        ├── 扫描所有 trigger_config.enabled=true 的 Workflow  │
│        └── 注册到 Celery Beat / 发送延迟任务                 │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│ 2. Celery Beat 触发（每天 09:00 UTC）                        │
│    └── 调用 execute_scheduled_workflow(workflow_id)          │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│ 3. 执行逻辑                                                  │
│    ├── 加载 Workflow + trigger_config                        │
│    ├── 渲染 default_input 模板                               │
│    │   └── {{ now() }} → "2026-07-08T09:00:00Z"             │
│    ├── 调用 TaskService.create_task(                         │
│    │       workflow_id,                                      │
│    │       input_data=rendered_input,                        │
│    │       created_by="system",                              │
│    │       created_by_type="system"                          │
│    │   )                                                     │
│    └── 更新 last_triggered_at, next_trigger_at               │
└─────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│ 4. Task 执行                                                  │
│    └── Task 状态: PENDING → RUNNING → COMPLETED/FAILED       │
│        └── WorkflowEngine 执行 Workflow（使用渲染后的 input） │
└─────────────────────────────────────────────────────────────┘
```

### 6.2 错误处理

| 场景 | 处理方式 |
|------|---------|
| Workflow 被删除 | 自动清理触发配置和 Beat 任务 |
| Workflow 禁用触发 | 从 Beat 移除，不删除配置 |
| 执行失败 | Task 标记为 FAILED，不影响下次触发 |
| 模板渲染失败 | 使用原始值，记录错误日志 |

---

## 7. 实施计划

### 7.1 阶段划分

#### 阶段 1：后端基础（P0）

- [ ] Workflow 模型扩展（TriggerConfig）
- [ ] TriggerSchedulerService 实现
- [ ] Celery Task: execute_scheduled_workflow
- [ ] API: CRUD + toggle
- [ ] 模板渲染工具函数

#### 阶段 2：前端实现（P0）

- [ ] TriggerConfigEditor 组件
- [ ] CronPresetSelector 组件
- [ ] DefaultInputEditor 组件
- [ ] API 调用层
- [ ] 集成到 Workflow 详情页

#### 阶段 3：测试与优化（P1）

- [ ] 单元测试：服务层 + 模板渲染
- [ ] 集成测试：API + 调度
- [ ] 前端 E2E 测试
- [ ] 性能优化：大量触发配置的 Beat 注册

### 7.2 文件清单

**后端新增：**
```
backend/app/services/trigger_scheduler_service.py
backend/app/workers/tasks/scheduled_workflow.py
backend/tests/services/test_trigger_scheduler_service.py
backend/tests/workers/test_scheduled_workflow.py
```

**后端修改：**
```
backend/app/models/workflow.py                    # 新增 TriggerConfig
backend/app/api/v1/workflows.py                   # 新增触发 API
backend/app/workers/celery_app.py                 # 注册新 task
backend/app/core/startup.py                       # 启动 TriggerSchedulerService
```

**前端新增：**
```
frontend/src/components/workflows/TriggerConfigEditor.tsx
frontend/src/components/workflows/CronPresetSelector.tsx
frontend/src/components/workflows/CronCustomBuilder.tsx
frontend/src/components/workflows/DefaultInputEditor.tsx
frontend/src/components/workflows/TriggerStatusDisplay.tsx
frontend/src/services/workflow-trigger-api.ts
frontend/src/types/workflow-trigger.ts
```

**前端修改：**
```
frontend/src/pages/WorkflowDetailPage.tsx         # 新增定时触发 Tab
```

---

## 8. 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| Celery Beat 单点故障 | 定时任务不执行 | 后续可实现多实例调度（Redis 分布式锁） |
| 大量触发配置 | Beat 注册慢、内存占用高 | 分页加载、懒注册 |
| 模板注入攻击 | 安全风险 | Jinja2 sandbox 模式，限制可用函数 |
| Workflow 修改影响定时任务 | 执行结果不一致 | 当前用最新版，后续实现版本化 |

---

## 9. 后续扩展

### 9.1 Post-MVP

- **版本管理**：Workflow 发布时创建快照，触发配置绑定版本
- **事件触发**：监听平台事件（Task 完成、Agent 错误等）
- **Webhook 触发**：外部系统 HTTP 回调触发
- **触发历史**：记录每次触发的详细信息
- **触发统计**：成功率、失败率、平均执行时间
- **分布式调度**：多实例部署下的调度协调

### 9.2 可能的优化

- **动态模板变量**：支持更多内置变量（如 `{{ last_result() }}`）
- **触发依赖**：Workflow A 完成后触发 Workflow B
- **触发链**：多个触发条件组合（AND/OR）

---

## 10. 验收标准

### 10.1 功能验收

- [ ] 用户可以创建 Cron 类型的定时触发配置
- [ ] 用户可以创建一次性类型的定时触发配置
- [ ] 用户可以启用/禁用触发配置
- [ ] 用户可以配置默认输入参数（支持模板语法）
- [ ] Cron 触发按时间表自动执行
- [ ] 一次性触发在指定时间自动执行
- [ ] 前端可视化构建 Cron 表达式
- [ ] 触发配置可以删除

### 10.2 非功能验收

- [ ] 服务重启后触发配置自动恢复
- [ ] 执行失败不影响下次触发
- [ ] 模板渲染失败时降级处理
- [ ] API 响应时间 < 200ms

---

**文档结束**
