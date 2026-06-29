# flow-task

## 一、平台整体架构

```
┌──────────────────────────────┐
│         用户交互层            │
│   对话（Direct）/ Task 查询与干预 │
└──────┬──────────┬──────────┬──┘
       │          │          │
       ▼          ▼          ▼
┌────────────┐ ┌────────────┐ ┌────────────┐
│  Direct    │ │ Interactive│ │  Scheduled │
│  模式      │ │  Workflow  │ │  Workflow  │
│ （查数据）  │ │ （交互流程） │ │ （定时任务） │
└─────┬──────┘ └─────┬──────┘ └─────┬──────┘
      │              │              │
      ▼              ▼              ▼
┌────────────┐ ┌────────────┐ ┌────────────┐
│ Agent直接   │ │ Task调度器  │ │ 定时触发器  │
│ 调用Tool   │ │ （状态机）   │ │ （Cron）    │
└────────────┘ └─────┬──────┘ └─────┬──────┘
                     │              │
                     ▼              ▼
                ┌────────────┐ ┌────────────┐
                │Workflow引擎│ │ 预取数据    │
                │ 节点执行器  │ │ 自动执行    │
                └─────┬──────┘ └────────────┘
                      │
                      ▼
┌──────────────────────────────┐
│      能力层（Tool/MCP）        │
│  查MES / 写PLC / 调ERP / 发邮件 │
└──────────────────────────────┘
```

## 二、核心概念定义

| 概念 | 定义 | 类比 |
|-|-|-|
| **Tool / MCP / Plugin** | 原子能力（查库存、调API、读PLC） | "手" |
| **Agent** | 绑定能力，具备推理决策，可调用工具或创建任务 | "工人" |
| **Workflow** | 流程模板（类），定义"怎么做"，预定义 + 动态装配 | "作业指导书" |
| **Task** | Workflow 的运行时实例（对象），有状态、可前后台切换 | "一张工单" |

> ℹ️ 原文档用"Skill"作为能力层概念之一。为避免与 BMad skill 命名冲突，统一改为 **Plugin**。若领域内已确立 Skill 术语，可在上下文注释中说明。

## 三、Workflow 设计

### 3.1 生成方式：预定义模板 + 上下文动态装配

- 不是完全动态生成（LLM 实时生成不可靠）
- 模板库：`defect_handling_v2`、`schedule_adjustment_v1` 等
- 动态装配：注入变量、条件渲染节点、调整参数

#### 模板管理机制

| 维度 | 方案 |
|------|------|
| **存储** | 数据库（MongoDB）+ 文件系统双写，DB 负责索引/查询，文件系统负责版本 diff |
| **版本化** | semver 语义版本号，每次编辑生成新版本，旧版本只读不可编辑 |
| **兼容性** | 模板版本与 Task 运行时版本解耦：已创建的 Task 永远使用其创建时的模板快照 |
| **装配执行** | 规则引擎执行装配（变量替换 + 条件节点渲染），LLM 仅参与参数推荐，不参与结构变更 |
| **迁移** | 提供 `migrate_task` 接口将运行中 Task 升级到新版本模板（需节点级兼容性检查） |

### 3.2 两种形态

| 类型 | 触发方式 | 人工节点 | 输入来源 | 失败处理 |
|-|-|-|-|-|
| **Interactive** | 用户对话 / 事件 | ✅ 必须有 | 外部传入（`input_schema`） | 挂起等待干预 |
| **Scheduled** | Cron 定时 | ❌ 无 | 自拉取（`prefetch`） | 自动重试 + 告警 |

### 3.3 节点类型

| 类型 | 职责 | 关键配置 |
|------|------|----------|
| `agent` | 调用 LLM Agent 推理（根因分析、方案生成） | `model`, `prompt_template`, `temperature`, `max_retry` |
| `tool` | 直接调用外部 Tool（写 MES、调 PLC） | `tool_name`, `params_schema`, `timeout_ms`, `retry_policy` |
| `human` | 等待人工输入 / 审批（班长确认、工程师审批） | `timeout_ms`, `escalation`（升级路径）, `default_action` |
| `gateway` | 条件分支路由（表达式判断） | `conditions[]`, `default_branch`, `fallback_on_error` |
| `parallel` | 并行分支（fork/join） | `branches[]`, `join_strategy`（all/any/n-of-m）, `scope`（shared/isolated） |
| `timer` | 延时 / 定时触发 | `delay_ms`, `cron_expr`, `pause_on_suspend`（Task 挂起时是否暂停计时） |
| `event` | 等待外部事件（IoT 信号） | `event_key`, `timeout_ms`, `timeout_action`（fail/skip/default_branch） |
| `subflow` | 嵌套调用另一个 Workflow | `workflow_id`, `input_mapping`, `result_mapping` |
| `start` / `end` | 流程起止、变量初始化 / 结果汇总 | `input_schema`, `output_schema` |

#### 节点关键语义说明

**`parallel`（并行分支）：**
- **join_strategy = `all`**：所有分支完成才继续（默认）
- **join_strategy = `any`**：任一分支完成即继续，其余分支取消
- **join_strategy = `n-of-m`**：指定 N 个分支完成后继续，其余分支取消
- **scope = `shared`**：分支共享变量池（可互相读取）
- **scope = `isolated`**：分支拥有独立变量沙箱，join 时按 mapping 合并
- 任一分支失败 → 根据 join_strategy 决定：`all` 模式直接整体失败；`any`/`n-of-m` 模式视必要分支数决定

**`event`（外部事件）：**
- 必须配置 `timeout_ms`，**不允许无超时的 event 节点**
- `timeout_action` 定义超时后的行为：
  - `fail` — Task 进入 `failed` 状态
  - `skip` — 跳过 event 节点继续后续流程
  - `default_branch` — 走网关指定的默认分支
- 超时触发前到达的事件数据写入变量池

**`timer`（定时器）：**
- `pause_on_suspend` 控制 Task 进入 `paused`/`waiting_human` 状态时，timer 是否暂停倒计时
- timer 触发时若 Task 处于 `waiting_human` 状态：优先执行 timer 动作（如发送超时通知），不干扰人工节点

### 3.4 输入输出机制：变量池 + 表达式注入

- 运行时变量池：Task 级隔离，节点间通过 `{{node_id.field}}` 读取
- 输入：`input_schema` 声明创建时必须传入的变量
- 节点输出：按 `output_schema` 结构化写入（前缀为节点 ID，如 `n1.cause`）
- 输出：Task 完成后按 `output_schema` 映射回 Session 上下文

```json
{
  "condition": "{{n1.confidence}} >= 0.9 && {{rate}} > 0.10",
  "params": {
    "line_id": "{{line_id}}",
    "reason": "{{n1.cause}}"
  }
}
```

## 四、Task 设计

### 4.1 本质

- Workflow = Class（模板）
- Task = Instance（实例）
- 一个 Workflow 可生成多个 Task

### 4.2 状态机

```
                                            ┌─────────────────┐
                                            │    pending      │
                                            └────────┬────────┘
                                                     │ create
                                                     ▼
                                            ┌─────────────────┐
                              ┌─────────────│    running      │
                              │             └───┬────┬────┬───┘
                              │                 │    │    │
                              │      event wait  │    │    │ agent/tool/subflow 完成
                              │                 │    │    │
                              ▼                 ▼    │    ▼
                    ┌──────────────┐   ┌───────────┐ │  ┌──────────┐
                    │  event_wait  │   │ timer_wait│ │  │ completed│
                    │  (外部事件)   │   │  (定时器)  │ │  └──────────┘
                    └──────┬───────┘   └─────┬─────┘ │
                           │                 │       │
                           └──── 超时 ───────┘       │
                                    │                │
                                    ▼                │
                            ┌──────────────┐         │
                            │   failed     │◄────────┘
                            │  / timeout   │
                            └──────────────┘

  ═══════════════════════ 人工交互子状态 ═══════════════════════

  running ── 到达 human 节点 ──► waiting_human
       ▲                            │
       │  resume              approve / reject / skip
       │                            │
       └────────────────────◄───────┘
       (reject → 走失败分支 / skip → 继续下一节点)

  running ── pause ──► paused ── resume ──► running
       │                    │
       │                    ├── timeout ──► failed
       │                    └── cancel  ──► cancelled
       │
       └── cancel ──► cancelled
```

#### 状态转换完整表

| 当前状态 | 操作 | 目标状态 | 说明 |
|----------|------|----------|------|
| `pending` | 创建 & 启动 | `running` | Task 开始执行 |
| `running` | 到达 human 节点 | `waiting_human` | 等待人工输入/审批 |
| `running` | 用户暂停 | `paused` | 主动暂停执行 |
| `running` | 用户取消 | `cancelled` | 主动取消 Task |
| `running` | 节点完成 | `running` | 继续执行下一节点 |
| `running` | 所有节点完成 | `completed` | Task 正常结束 |
| `running` | 不可恢复错误 | `failed` | 引擎级或节点级错误 |
| `running` | 超时 | `failed` | 超过全局超时时间 |
| `waiting_human` | 人工审批通过 | `running` | 恢复执行 |
| `waiting_human` | 人工驳回 | `failed` | 走失败处理路径 |
| `waiting_human` | 跳过 | `running` | 跳过当前节点继续 |
| `waiting_human` | 超时未响应 | `failed` | 超时升级机制生效 |
| `paused` | 恢复 | `running` | 从暂停点继续 |
| `paused` | 取消 | `cancelled` | 不恢复，直接取消 |
| `paused` | 超时 | `failed` | 暂停超时自动失败 |
| `cancelled` | — | 终态 | 不可转换 |
| `completed` | — | 终态 | 不可转换 |
| `failed` | — | 终态 | 不可转换 |

### 4.3 前后台模式

| 模式 | 特征 | 切换条件 |
|-|-|-|
| **前台** | 阻塞对话，用户等待结果 | 简单流程、用户主动等待 |
| **后台** | 异步执行，用户可干别的 | 复杂流程、超 30 秒自动转后台 |
| **挂起** | 暂停等待外部输入 | 人工节点、用户主动暂停 |

#### 前后台切换规则

- 前台 Task 在 30 秒内未完成 → 自动转后台，通知用户"任务已转为后台执行，可查询进度"
- 前台 Task 转后台后，用户可继续在对话中发送新消息（新消息不会干扰已有 Task）
- 同一 Session 允许多个后台 Task 并行，前台 Task 同时仅允许一个
- 前台 Task 转后台时，未返回的中间结果通过 `task_query` 获取

### 4.4 上下文隔离与同步

- 隔离：Task 变量池与 Session 上下文物理隔离，防止失败污染对话
- 继承：创建时按 `input_schema` 声明字段从 Session 浅拷贝 + 类型转换（**非全量深拷贝**，避免循环引用/超大对象/敏感数据泄漏风险）
- 同步：事件驱动，只同步状态摘要（`status`、`current_node`、`can_intervene`），不同步内部节点变量

#### 变量池访问规则

- 每个变量访问表达式 `{{node_id.field}}` 必须包含 fallback 或 null-safe 处理
- 变量未定义（节点未执行/执行失败）时求值规则：
  - `gateway` 条件表达式：视为 `false`，走 `fallback_on_error` 分支
  - `params` 注入：视为 `null`，由接收节点自行处理 null 值
- 表达式引擎内置 try-catch，语法错误不传播到 Workflow 引擎级

### 4.5 流程干预

```json
{
  "action": "approve / reject / pause / resume / skip / rollback / inject",
  "node_id": "n3",
  "operator": "user_boss",
  "comment": "同意停线"
}
```

## 五、Agent 与 Workflow 的交互

### 5.1 核心原则：Agent 必须前置感知 Workflow

> Agent 启动时就必须"知道"所有 Workflow 的"什么时候用"，而不是运行时临时检索。

> ⚠️ **注册表膨胀对策**：随着模板数量增长，支持将注册表拆分为"核心（高频）"和"扩展（低频）"两层。核心注册表挂载在 System Prompt 中，扩展注册表通过 RAG 检索获得。Agent 在核心注册表未命中时自动降级检索扩展注册表。

能力地图（Workflow Registry）注入 Agent：

```json
{
  "workflow_registry": [
    {
      "id": "defect_handling_v2",
      "when_to_use": "产线出现质量异常、不良率超标、缺陷报警时",
      "required_entities": ["station", "defect_type", "rate"],
      "has_human_node": true,
      "side_effects": ["可能停线"]
    }
  ]
}
```

### 5.2 决策机制

| 情况 | 决策 |
|-|-|
| 查数据、问状态、单次只读 | **Direct** 工具调用 |
| 涉及停线、改参数、跨系统写、需审批 | **必须 Workflow** |
| 匹配 `when_to_use` | 走对应 Workflow |
| 不确定 | 先 Direct 回答，提示"可走流程" |

### 5.3 Agent 的系统级工具

Agent 必须拥有以下 Task 管理 Skill：

| 工具 | 用途 |
|-|-|
| `search_workflow` | 语义检索 Workflow（辅助，非必须） |
| `get_workflow_schema` | 获取指定 Workflow 的输入参数定义 |
| `create_task` | 创建 Task（传入 `workflow_id` + `variables`） |
| `task_query` | 查询 Task 进度 |
| `task_intervene` | 审批、跳过、暂停、恢复等干预操作 |
| `task_list` | 列出用户关联的 Task |
| `cancel_task` | 取消一个不再需要的 Task（仅 `running` / `waiting_human` / `paused` 状态可取消） |
| `get_task_timeline` | 获取 Task 的执行时间线 / 审计日志 |
| `update_task_variables` | 运行时修正变量（如用户纠正参数："产线是 S04 不是 S03"） |

### 5.4 变量提取流程

1. Agent 从当前用户输入提取明确实体
2. 从 Session 上下文补充（产线、班次等）
3. 按 `input_schema` 类型转换（`"15%"` → `0.15`）
4. Required 缺失 → 主动询问用户
5. 调用 `create_task`

## 六、上下文管理

### 6.1 三层上下文

| 层级 | 作用域 | 内容 | 生命周期 |
|------|--------|------|----------|
| **Session Context** | 对话级，持久化 | 用户实体、偏好、话题引用、Task 状态摘要 | 对话全周期 |
| **Task Context** | Task 级，隔离 | 节点变量、执行状态、审计日志 | Task 全周期，完成/失败后可配置保留 N 天后清理 |
| **Node Context** | 节点级，临时 | Agent Prompt、Tool 参数、节点输出 | 保留至 Task 结束，不提前清理（human 节点审批时仍可查看前置 Agent 的输出） |

### 6.2 流转规则

```
Session（用户说" S03 划痕 15%"）
    │
    │ 创建 Task 时深拷贝
    ▼
Task Context（station="S03", defect_type="划痕", rate=0.15）
    │
    │ n1[Agent] 执行后写入
    ▼
n1.cause="换模偏差", n1.confidence=0.92
    │
    │ n2[Gateway] 读取判断
    ▼
n3[Human] 等待审批
    │
    │ 事件同步（只同步状态）
    ▼
Session.context_pool.task_001 = {
  "status": "waiting_human",
  "current_node": "n3"
}
```

## 七、状态同步与事件驱动

### 7.1 事件类型

- `task.node.completed` — 节点完成
- `task.human.waiting` — 等待人工
- `task.status.changed` — 状态变更
- `task.completed` / `task.failed` — 完成 / 失败

### 7.2 同步路径

Workflow 引擎 → 事件总线 → Task 状态机更新 → 持久化 → 推送 Session

#### 事件总线可靠性约定

| 维度 | 方案 |
|------|------|
| **投递语义** | at-least-once（消费端需幂等去重） |
| **重试策略** | 指数退避（初始 100ms，最大 30s，最多 5 次），超出进死信队列 |
| **死信队列** | 死信事件人工/自动巡检后手动重放或丢弃 |
| **背压处理** | 事件总线缓冲区水位线告警，超阈值时降级为仅持久化不同步（恢复后追赶） |
| **消费端幂等** | 事件 ID 全局唯一，消费端按事件 ID 去重 |

### 7.3 用户查询与推送

- 前台 Task：节点完成自动推送进度
- 后台 Task：关键节点（人工等待、完成、失败）选择性推送
- 用户主动查询：通过 `task_query` 返回当前状态 + 时间线

## 八、系统保障

### 8.1 高可用（HA）

| 组件 | HA 方案 |
|------|---------|
| **Workflow Engine** | 多副本部署，无状态设计，共享 Task 状态存储；单副本宕机不影响其他副本 |
| **Task 调度器** | 主从模式，主节点故障自动选举 |
| **事件总线** | 基于消息队列（如 Redis Stream / RabbitMQ）的持久化队列 |
| **能力层（Tool/MCP）** | 单 Tool 超时/熔断不影响其他 Tool |
| **降级策略** | Workflow Engine 整体不可用时：Direct 模式仍可用（查数据、问状态），新建 Task 排队等待 |

### 8.2 并发与资源管理

| 维度 | 方案 |
|------|------|
| **Engine 并发上限** | 单实例最大 50 并发 Task 执行（可配置），超出排队 |
| **同 Workflow 并发** | 同一模板允许最多 N 个并行 Task（N 在模板定义中声明） |
| **限流** | 全局速率限制 + 用户级配额（单用户 ≤ 5 并发 Task） |
| **熔断** | Tool 级熔断：连续失败超阈值后自动熔断，恢复后渐进重试 |

### 8.3 审计与可观测性

| 维度 | 方案 |
|------|------|
| **审计日志** | 全量记录：Task 创建、节点执行、干预操作、状态变更，附加操作人/时间 |
| **调用链追踪** | 支持分布式 tracing（OpenTelemetry），跨 subflow 链路串联 |
| **日志保留** | 运行时日志 30 天，审计日志 90 天，可配置 |
| **监控告警** | Task 失败率、pending 队列积压、事件总线背压、Engine CPU/内存 — 统一上报 Prometheus |

### 8.4 并发干预与乐观锁

- Task 干预操作使用**乐观锁**（version 字段）：读取时获取版本号，提交时校验版本号
- 版本不匹配 → 提示"Task 状态已变更，请重新获取"，不走自动覆盖
- 干预日志记录所有并发请求的发起时间 + 结果（成功/拒绝），用于事后审计

### 8.5 Scheduled Workflow 增强

| 场景 | 处理 |
|------|------|
| 重试仍失败 | 执行 `escalation` 定义的降级动作（使用默认值 / 调用备用服务 / 发送告警到指定渠道） |
| 失败会导致停线 | 自动插入一个"待人工确认"的暂停点，等待确认后才继续 |
| 需审批后才执行动作 | 模板中可声明 `requires_approval: true`，Scheduled 创建 Task 后进入 `waiting_human` 等待审批 |
| Prefetch 数据源 | 在 `prefetch` 段中声明数据源类型（HTTP / DB / File）、连接参数、轮询频率；失败按 Scheduled 重试机制处理 |

## 九、关键设计决策清单

| 决策 | 方案 |
|-|-|
| Workflow 是否动态生成 | **否**，预定义模板 + 上下文装配 |
| 模板如何管理 | **DB + 文件系统双写**，semver 版本化，Task 绑定模板快照 |
| 装配由谁执行 | **规则引擎**执行，LLM 仅参与参数推荐 |
| Task 是否隔离 | **是**，按 input_schema 拷贝初始化，事件同步状态摘要 |
| Agent 如何知道用 Workflow | **启动时注入能力地图**（`when_to_use` 注册表），支持检索增强式注入防膨胀 |
| 变量缺失怎么办 | **Required 必询问用户**，不猜测 |
| Gateway 表达式异常 | **安全求值**，undefined 变量视为 false，语法错误走 fallback 分支 |
| 人工节点超时 | 可配置升级（通知上级、自动驳回、转默认分支） |
| event 节点 | **必须配置超时**，不允许无限等待 |
| parallel join 策略 | **默认 all**，支持 any / n-of-m，分支失败按策略决定 |
| 事件投递语义 | **at-least-once** + 消费端幂等去重 |
| 状态同步 | 事件驱动，**只同步摘要**（status / current_node / can_intervene） |
| Scheduled 失败 | 自动重试 + **escalation 降级**（默认值/备用服务/告警） |
| 对话中如何干预 Task | Agent 调用 `task_intervene`，用户无感知底层 API |
| Workflow Engine HA | **多副本无状态**，共享存储，单副本故障不影响全局 |
| 并发控制 | 全局 50 Task 上限，单用户 ≤ 5 并发 |
| 多人干预冲突 | **乐观锁**（version 字段），冲突时提示重新获取 |
| 审计 | **全量审计日志** + OpenTelemetry 调用链追踪 |