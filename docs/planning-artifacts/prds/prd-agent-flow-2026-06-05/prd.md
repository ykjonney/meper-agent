---
title: Agent Flow
status: final
created: 2026-06-05
updated: 2026-06-09
---

# PRD: Agent Flow

## 0. Document Purpose

本文档是 Agent Flow 平台的产品需求文档（PRD），面向开发团队、利益相关方和下游工作流（UX、架构、史诗拆分）。文档以 Glossary 锚定的术语体系组织，功能按特性分组、功能需求（FR）嵌套其中，推断内容以 `[ASSUMPTION]` 标记并汇总于末尾。

Agent Flow 是一个通用 AI Agent 编排平台。本 PRD 定义 MVP 阶段的范围和要求。

前置输入：产品简报 v2、头脑风暴记录、市场调研报告。

## 1. Vision

Agent Flow 是公司的 AI 能力中台——一个让开发团队在 Web 界面上创建、配置和运行自主 Agent 的通用平台。平台定位为内部产品，服务公司内部各部门的业务系统，几十人使用规模。

每个 Agent 是一组可组合的能力集合：提示词、工具、知识库、工作流。Agent 收到任务后自主规划执行路径——判断走自由推理还是调用某个已配置的工作流走确定性流程。工作流是 Agent 的能力之一，不是 Agent 的牢笼。

用户通过创建 Skill、MCP 连接和工作流来适配自己的业务场景（如 MES 质量分析、ERP 数据处理、BI 报告生成）。平台不绑定任何垂直领域，但第一个落地场景是制造执行系统（MES）。

外部系统通过 API/SDK 接入平台，消费 Agent 的推理、分析、生成等能力。同一个 Agent 可以被 MES 系统调用处理报警，也可以被 BI 系统调用生成报告——同一个能力集合，不同的消费方。

核心设计哲学：**工作流是 Agent 的一种能力**。Agent 不是被工作流编排的执行节点，而是主动选择是否使用工作流的智能体。这让同一个 Agent 在不同场景下自动切换执行策略。

## 2. Target User

### 2.1 Jobs To Be Done

**开发团队（平台建设者）**
- 快速创建和配置具备多种能力的 Agent，不写硬编码逻辑
- 将 Agent 能力暴露给公司的业务系统，成为 AI 能力中台
- 管理和监控 Agent 的运行状态和执行历史
- 通过 Skill 和 MCP 不断扩展 Agent 的能力边界

**业务系统（能力消费者）**
- 通过 API 调用 Agent 能力完成业务任务（质量分析、数据处理、报告生成等）
- 不直接操作平台界面，通过接口消费 Agent 的推理和分析能力

**产线工程师（操作员）**
- 通过 Web 界面查看 Agent 分析结果、调整 Agent 参数、查看执行历史
- 使用简化的操作员视图，不需要了解 Agent 底层配置细节
- 关注"能不能用"、"结果准不准"、"出了问题怎么办"

**平台管理员**
- 管理用户权限、工具注册、模型接入
- 关注系统稳定性、可追溯性和资源管理

### 2.2 Non-Users (v1)

- 终端消费者（不直接使用平台）
- 第三方开发者（不做开放平台，不提供外部开发者注册）
- 需要代码编写能力的非技术用户（v1 的 Skill 创建仍需技术背景）

### 2.3 Key User Journeys

- **UJ-1. 张伟为质量分析场景配置一个新 Agent。**
  - **Persona + context:** 张伟，IT 部门开发工程师，负责 MES 系统和 AI 工具的集成。
  - **Entry state:** 已登录平台，进入 Agent 管理页面。
  - **Path:** 点击"新建 Agent"→ 填写名称和描述 → 编写系统提示词 → 从工具池中选择质量数据查询 MCP 和 SOP 文档知识库 → 绑定"质量异常分析"工作流 → 选择模型 → 保存。平台显示 Agent 已就绪。
  - **Climax:** Agent 配置完成，张伟在测试面板输入"今天 3 号产线的良率异常"，Agent 自主调用质量数据查询工具获取数据、检索 SOP 文档找到异常处理流程、按工作流步骤生成分析报告。
  - **Resolution:** Agent 进入可用状态，张伟获取 API 端点，准备集成到 MES 系统。
  - **Edge case:** 如果选择的工具和提示词存在冲突（如提示词要求搜索但未配置搜索工具），平台在保存时给出提示。

- **UJ-2. 李芳通过 MES 系统调用 Agent 处理质量报警。**
  - **Persona + context:** 李芳，MES 系统的自动化流程，产线质量报警触发时自动调用 Agent Flow API。
  - **Entry state:** MES 检测到 3 号产线良率低于阈值，通过 API 发送报警数据给 Agent Flow。
  - **Path:** MES 调用 Agent API，传入报警上下文（产线 ID、异常参数、时间段）→ Agent 接收任务 → 自主判断这是一个多步分析任务 → 选择调用"质量异常分析"工作流 → 工作流按步骤执行：获取历史数据 → 对比工艺参数 → 匹配已知异常模式 → 生成分析报告和处置建议。
  - **Climax:** Agent 返回结构化分析结果给 MES，包含根因分析、置信度和处置建议。
  - **Resolution:** MES 将结果展示给产线工程师，同时记录到质量追溯系统。调用链完整记录在执行日志中。
  - **Edge case:** 如果 Agent 判断报警数据不足以下结论，返回"需要更多信息"并附上缺失数据清单，MES 自动补采数据后再次调用。

- **UJ-3. 王磊为设备监控场景创建并注册一个 MCP 工具。**
  - **Persona + context:** 王磊，IT 部门工程师，需要让 Agent 能读取 MES 系统中的设备实时状态数据。
  - **Entry state:** 已登录平台，进入工具管理页面。
  - **Path:** 点击"添加 MCP 连接"→ 填写 MCP 服务器地址和认证信息 → 测试连接 → 平台发现 MCP 服务器提供的工具列表（查询设备状态、获取历史数据、订阅报警）→ 王磊选择需要的工具 → 保存到工具池。
  - **Climax:** 新工具出现在工具池中，任何 Agent 配置时都可以选择使用。
  - **Resolution:** 王磊通知张伟新的设备监控工具已可用，张伟将其添加到质量分析 Agent 的工具列表中。
  - **Edge case:** MCP 服务器不可达时，平台在测试连接阶段报错，不阻止保存但标记为"未验证"状态。

- **UJ-4. 陈静创建一个多步骤工作流供 Agent 调用。**
  - **Persona + context:** 陈静，IT 部门开发工程师，需要定义一个确定性的"设备预测维护"流程。
  - **Entry state:** 已登录平台，进入工作流编排页面。
  - **Path:** 创建新工作流 → 拖入"开始"节点 → 拖入"数据采集"节点（配置数据源参数）→ 拖入"条件分支"节点（判断数据是否异常）→ 异常分支连接"分析"节点 → 正常分支连接"结束"节点 → 分析节点连接"生成报告"节点 → 连接"结束"节点 → 保存并发布。
  - **Climax:** 工作流发布后自动注册为可用工具，Agent 配置时可以绑定此工作流。
  - **Resolution:** 陈静在设备维护 Agent 的配置中绑定此工作流。Agent 收到维护预测请求时，可自主选择调用此工作流走确定性流程。
  - **Edge case:** 工作流中存在未连接的节点时，保存时提示补全或删除悬空节点。

## 3. Glossary

- **Agent** — 平台的核心执行单元，由提示词、工具组合、知识库、工作流绑定、模型偏好等构成的可配置能力集合。Agent 是无状态的角色配置，持久的是对话历史而非 Agent 本身。Agent 之间不直接通信，只通过工作流协作。
- **Workflow（工作流）** — 由节点和边组成的有向无环图（DAG），定义确定性的执行步骤序列。Workflow 是流程模板（类），由预定义模板 + 上下文动态装配而成，不依赖 LLM 实时生成。Workflow 可以作为 Agent 的能力被调用，也可以独立通过 API 触发。分为两种形态：
  - **Interactive Workflow** — 用户对话/事件触发，包含人工审批节点，失败时挂起等待干预
  - **Scheduled Workflow** — Cron 定时触发，无人工节点，失败时自动重试 + 告警升级
- **Task** — Workflow 的运行时实例（对象），有完整的状态生命周期（pending → running → completed/failed/cancelled 等）。一个 Workflow 可生成多个 Task。Task 的变量池与 Session 上下文物理隔离，防止失败污染对话。
- **Job** — Agent 收到的任何输入。所有输入都是 Job，由 Agent 判断 Job 大小并选择执行路径。
- **Node（节点）** — Workflow 中的执行步骤。MVP 节点类型：start、end、agent、tool、human、gateway、parallel、subflow。详见 FR-10。
- **Edge（边）** — Workflow 中节点之间的连接，可配置条件表达式决定数据流向。
- **Tool（工具）** — Agent 可调用的外部能力。来源包括 Skill 和 MCP 连接。工具独立于 Agent 存在，Agent 自由组合使用。
- **Skill** — 以 Markdown 格式定义的工具，支持 Git 拉取、目录上传和前端创建三种来源。归一化为统一格式。
- **MCP（Model Context Protocol）** — 外部工具协议连接标准。通过配置 MCP 服务器地址，平台自动发现和注册其提供的工具。
- **Knowledge Base（知识库）** — Agent 可检索的知识集合，支持文档上传和管理。
- **Execution Path（执行路径）** — Agent 处理 Job 的方式。三种模式：直接执行（小 Job）、规划执行（大 Job）、工作流执行（Agent 创建 Task 走确定性流程）。
- **Execution Log（执行日志）** — Agent 和 Task 执行的完整记录，包含调用链、输入输出、耗时和状态，用于审计和调试。
- **Conversation（对话）** — 用户与 Agent 之间的交互上下文，包含消息历史和状态。对话可触发工作流（创建 Task），Task 执行中也可创建/继续对话。
- **Variable Pool（变量池）** — Task 级隔离的数据存储，节点间通过 `{{node_id.field}}` 表达式读取上游输出。支持 null-safe 处理和 fallback 机制。
- **Workflow Registry（能力地图）** — Agent 启动时注入的 Workflow 注册表，包含每个 Workflow 的触发条件（`when_to_use`）、所需实体和副作用信息，使 Agent 前置感知所有可用 Workflow。

## 4. Features

### 4.1 Agent 创建与配置

**Description:** 开发人员在 Web 界面上创建 Agent，为其组合提示词、工具、知识库、工作流绑定和模型偏好。Agent 是可配置的能力集合，不是硬编码的脚本。每个 Agent 的能力在创建时定义，但执行时由 Agent 自主决定使用哪些能力。Realizes UJ-1.

**Functional Requirements:**

#### FR-1: Agent 生命周期管理

用户可以创建、编辑、复制、删除和发布 Agent。每个 Agent 包含名称、描述、系统提示词、工具选择、知识库绑定、工作流绑定、模型配置和运行时参数。Agent 保存后进入"可用"状态，可被 API 调用或在对话面板中使用。

**Consequences (testable):**
- 创建 Agent 后，Agent 列表中出现新条目，状态为"可用"
- 编辑已发布的 Agent 后保存，不影响正在进行的对话，新对话使用更新后的配置
- 删除 Agent 时，平台提示该 Agent 是否有关联的活跃对话或 API 调用

#### FR-2: Agent 能力组合

用户可以从工具池中为 Agent 选择零个或多个工具、绑定零个或多个工作流、关联零个或多个知识库。Agent 的能力是可选组合的——一个 Agent 可以只有提示词和模型配置，也可以组合全部能力类型。

**Consequences (testable):**
- Agent 配置页面展示当前可用的工具池、工作流列表和知识库列表供选择
- 未配置工具的 Agent 仅使用模型自身的推理能力
- 为 Agent 添加新工具后，后续对话中 Agent 可调用该工具

#### FR-3: Agent 模型配置

用户可以为 Agent 选择默认运行模型和运行时参数（温度、最大 Token 数等）。Agent 可配置模型动态路由规则：根据任务特征（如语言、复杂度、是否需要工具调用）自动选择最合适的模型执行。路由规则为条件-模型对列表（如"任务包含代码 → 模型A"、"纯中文问答 → 模型B"），按顺序匹配，无匹配时使用默认模型。平台支持 5-10 个主流 LLM 模型。

**Consequences (testable):**
- Agent 配置中可选择平台已接入的模型
- Agent 可配置多条模型路由规则，运行时根据规则自动切换模型
- 路由规则为有序的条件-模型对列表，支持增删和排序
- 无规则匹配时使用 Agent 配置的默认模型
- 修改模型配置后，新对话使用新模型，已有对话不受影响

**Notes:**
- `[ASSUMPTION:]` MVP 阶段支持 5-10 个模型，包括 OpenAI GPT 系列、Claude 系列和至少一个国产模型。具体模型列表待技术选型确定。
- `[NOTE FOR PM:]` 是否需要模型 A/B 测试能力（同一 Agent 配置两个模型对比效果）？建议 MVP 不做，后续迭代。
### 4.2 Agent 自主规划与执行

**Description:** Agent 收到任何输入后，由模型自身判断 Job 大小并选择执行路径。小 Job 直接执行；大 Job 进入"计划→执行→验证"三阶段；如果 Job 匹配已配置的工作流，Agent 可选择调用工作流创建 Task 走确定性流程。Job 分类由模型完成，不需要外部规则引擎。Realizes UJ-2.

**Functional Requirements:**

#### FR-4: Job 评估与执行路径选择

Agent 收到 Job 后，由模型评估复杂度并自主选择执行路径。三种路径：
- **直接执行** — Job 简单（如问答、闲聊、单步操作），Agent 直接推理并返回结果
- **规划执行** — Job 复杂（如多步骤分析、需要协调多个工具），Agent 进入"计划→执行→验证"三阶段：先制定执行计划，再逐步执行，最后验证结果是否满足要求
- **工作流执行** — Job 匹配已配置的工作流，Agent 调用 Workflow 创建 Task 走确定性流程

模型根据输入内容、可用工具列表和已配置工作流的触发描述（`when_to_use`）综合判断。判断结果和依据记录在执行日志中。

**Consequences (testable):**
- 输入简单问答时，Agent 直接执行并返回结果，不触发规划或工作流
- 输入多步骤 Job 时，Agent 先生成执行计划，再逐步执行，最后验证结果
- Agent 判断 Job 匹配已配置工作流时，创建 Task 执行
- 执行日志中记录路径选择结果、判断依据和执行计划（如有）

#### FR-5: 直接执行模式

Agent 在直接执行模式下，按照 REACT 模式（Reasoning + Acting）推理并返回结果。适用于简单 Job，不生成执行计划。每一步的思考过程和工具调用记录在执行日志中。

**Consequences (testable):**
- Agent 在直接执行模式下能自主决定调用哪些工具
- 每一步的推理过程和工具调用结果记录在执行日志中
- Agent 在无法完成推理时返回明确的失败原因

#### FR-6: 规划执行模式（计划→执行→验证）

Agent 判断 Job 为复杂任务时，进入三阶段执行：
- **计划阶段** — Agent 分析 Job 要求，生成包含具体步骤的执行计划。计划列出需要调用的工具、数据获取步骤和预期输出
- **执行阶段** — Agent 按计划逐步执行，每一步调用工具或进行推理。执行过程中 Agent 可根据中间结果调整计划
- **验证阶段** — Agent 检查执行结果是否满足原始 Job 要求。不满足时，Agent 可补充执行或调整方案

**Consequences (testable):**
- 复杂任务触发时，Agent 先生成结构化执行计划
- 执行过程按计划步骤推进，每步结果记录在执行日志中
- 验证阶段输出通过/不通过判断及理由
- 执行日志中可查看计划、实际执行步骤和验证结果三部分

#### FR-7: 工作流执行模式

Agent 判断 Job 适合某个已配置的 Workflow 时，调用该 Workflow 创建一个 Task 实例并传入 Job 上下文（按 `input_schema` 声明的字段从 Session 浅拷贝，非全量深拷贝）。Task 按定义的节点和边执行，每一步的输入输出记录在执行日志中。Task 执行完成后，结果返回给 Agent，Agent 可选择继续推理或直接返回结果。

**Consequences (testable):**
- Task 按 DAG 定义的顺序依次执行节点
- 每个节点的输入和输出记录在执行日志中
- Task 执行失败时，执行日志记录失败节点和原因
- Agent 收到 Task 返回结果后可继续后续推理步骤
- Task 变量池与 Session 上下文物理隔离，Task 失败不污染对话

#### FR-8: 调用深度与循环保护

平台对 Agent → Workflow（创建 Task）→ Agent 的嵌套调用链设置深度限制。两层保护机制：
- **Workflow 级限制** — 单个 Workflow 内节点执行的最大深度
- **全局调用链限制** — 单次 Job 从入口到最深层的总调用深度上限

超出限制时，平台终止执行并返回明确的深度超限错误。

**Consequences (testable):**
- 全局调用链深度超过上限时，Job 终止并返回错误信息
- Workflow 级执行深度可在 Workflow 配置中自定义上限
- 执行日志记录深度超限的具体位置和当前深度

### 4.3 工作流编排

**Description:** 开发人员在 Web 界面上通过拖拽方式编排工作流。工作流是 DAG（有向无环图）模式，包含核心节点类型和条件边。工作流发布后可作为 Agent 的能力被调用。Realizes UJ-4.

**Functional Requirements:**

#### FR-9: DAG 工作流编辑器

平台提供基于 DAG 的工作流可视化编辑器。用户通过拖拽节点和连线构建工作流。编辑器支持缩放、平移、自动布局。每个节点可配置参数，每条边可配置条件表达式。

**Consequences (testable):**
- 用户能在编辑器中拖拽节点到画布并连接
- 编辑器检测并阻止环路（DAG 不允许有环）
- 保存工作流时验证所有必需节点参数是否已填写

#### FR-10: 核心节点类型

MVP 阶段提供以下核心节点类型，覆盖 Interactive Workflow 的主要编排需求：

| 节点类型 | 职责 | 关键配置 |
|----------|------|----------|
| **`start`** | 流程入口，定义输入参数 Schema 和变量初始化 | `input_schema` |
| **`end`** | 流程出口，定义输出格式和结果汇总 | `output_schema` |
| **`agent`** | 调用指定的 Agent 执行推理（根因分析、方案生成），可配置提示词覆盖和上下文 | `model`, `prompt_template`, `temperature`, `max_retry` |
| **`tool`** | 直接调用外部 Tool（写 MES、调 PLC、查数据），不经 LLM 推理 | `tool_name`, `params_schema`, `timeout_ms`, `retry_policy` |
| **`human`** | 等待人工输入/审批（班长确认、工程师审批），Task 进入 `waiting_human` 状态 | `timeout_ms`, `escalation`（升级路径）, `default_action` |
| **`gateway`** | 条件分支路由，基于表达式判断走哪条边 | `conditions[]`, `default_branch`, `fallback_on_error` |
| **`parallel`** | 并行分支（fork/join），多分支同时执行后合并 | `branches[]`, `join_strategy`（all/any/n-of-m）, `scope`（shared/isolated） |
| **`subflow`** | 嵌套调用另一个 Workflow（创建子 Task） | `workflow_id`, `input_mapping`, `result_mapping` |

**节点关键语义说明：**

**`human`（人工节点）：**
- Task 到达 human 节点时进入 `waiting_human` 状态，等待用户通过对话或任务面板进行审批/驳回/跳过
- 超时未响应触发 `escalation` 升级机制（通知上级、自动驳回、转默认分支）
- 支持人工节点时仍可查看前置 Agent 节点的输出（Node Context 不提前清理）

**`gateway`（网关）：**
- 条件表达式异常时走 `fallback_on_error` 分支
- 变量未定义（上游节点未执行/失败）时视为 `false`，由 fallback 兜底
- 表达式引擎内置 try-catch，语法错误不传播到引擎级

**`parallel`（并行分支）：**
- `join_strategy = all`（默认）：所有分支完成才继续
- `join_strategy = any`：任一分支完成即继续，其余分支取消
- `join_strategy = n-of-m`：指定 N 个分支完成后继续，其余取消
- `scope = shared`：分支共享变量池；`scope = isolated`：分支独立变量沙箱，join 时按 mapping 合并

**`subflow`（子工作流）：**
- 创建独立的子 Task 实例，子 Task 失败不直接影响父 Task（除非显式声明）
- 子 Task 共享全局调用链深度限制

**Consequences (testable):**
- 每种核心节点类型可在编辑器中拖入画布
- Agent 节点可选择平台中已创建的任一 Agent
- tool 节点直接调用工具，不经过 LLM 推理（用于确定性步骤）
- human 节点触发 Task 进入 `waiting_human` 状态
- gateway 节点根据表达式计算结果选择执行路径，异常时走 fallback 分支
- parallel 节点等待所有/任一/N 个分支完成后合并结果（按 `join_strategy`）
- subflow 节点创建子 Task 并等待完成，结果按 `result_mapping` 映射回父 Task

**Notes:**
- `[ASSUMPTION]` MVP 不含 `timer`（定时器）和 `event`（外部事件）节点，后续迭代。
- `[NOTE FOR PM]` Timer/Event 节点涉及外部事件总线集成，复杂度较高，建议在 Scheduled Workflow 形态成熟后再引入。

#### FR-11: 条件边配置

Workflow 中的边可配置条件表达式，支持两种条件类型：节点输出判断（基于上游节点的输出值，通过 `{{node_id.field}}` 引用）和数据条件（基于 Workflow 变量表达式）。条件表达式使用统一的表达式引擎，内置 try-catch，语法错误不传播到引擎级。变量未定义时视为 `false`，走 `fallback_on_error` 分支。

**Consequences (testable):**
- 条件边在编辑器中可配置条件表达式
- 运行时根据条件表达式的计算结果选择执行路径
- 表达式引擎支持基本的比较运算和逻辑运算
- 变量未定义时走 fallback 分支，不抛异常

#### FR-12: 工作流版本管理

工作流每次修改并保存后创建新版本，历史版本可查看但不可编辑。工作流发布后才能被 Agent 调用。Agent 绑定的是已发布的工作流版本。

**Consequences (testable):**
- 保存工作流时自动创建新版本
- 工作流版本列表展示所有历史版本
- Agent 只能绑定已发布状态的工作流版本

#### FR-12A: 工作流模板管理

工作流模板采用数据库 + 文件系统双写方案。数据库负责索引和查询，文件系统负责版本 diff。每次编辑生成新版本（semver 语义版本号），旧版本只读不可编辑。Task 创建时绑定当前模板快照，模板后续更新不影响已创建的 Task。

**装配执行约束**：模板装配由规则引擎执行（变量替换 + 条件节点渲染），LLM 仅参与参数推荐，**不参与 Workflow 结构变更**。这确保了 Workflow 的确定性，避免运行时不可控的结构漂移。

**Consequences (testable):**
- 模板版本号遵循 semver 格式（如 v1.0.0 → v1.1.0）
- 已创建的 Task 使用其创建时的模板快照执行
- 提供 `migrate_task` 接口可将运行中 Task 升级到新版本模板（需节点级兼容性检查）
- Workflow 结构变更只能通过编辑器显式操作，LLM 无法在运行时修改节点拓扑

### 4.3A Task 生命周期管理

**Description:** Task 是 Workflow 的运行时实例，具有完整的状态生命周期、变量隔离和干预机制。本模块定义 Task 从创建到终止的全过程管理。补充 FR-7（工作流执行模式）中 Task 实例化的运行时行为。

**Functional Requirements:**

#### FR-29: Task 状态机

Task 遵循严格的状态机模型，确保执行过程的确定性和可追溯性：

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

**Consequences (testable):**
- Task 创建后进入 `pending` 状态，启动后转为 `running`
- Task 到达 human 节点时自动进入 `waiting_human` 状态
- Task 不允许从终态（`completed`/`failed`/`cancelled`）转换到其他状态
- 所有状态转换记录在审计日志中，包含时间戳和触发原因

#### FR-30: Task 前后台模式

Task 支持前台和后台两种执行模式：
- **前台模式** — 阻塞当前对话，用户等待结果。适用于简单流程
- **后台模式** — 异步执行，用户可继续对话。适用于复杂流程
- **自动切换** — 前台 Task 在 30 秒内未完成，自动转后台，通知用户"任务已转为后台执行"

同一 Session 允许多个后台 Task 并行，前台 Task 同时仅允许一个。前台 Task 转后台后，未返回的中间结果通过 `task_query` 获取。

**Consequences (testable):**
- 简单 Workflow（执行时间 < 30s）可前台阻塞返回结果
- 超过 30 秒的 Task 自动转为后台执行
- 后台 Task 执行期间用户可继续对话
- 前台转后台时用户收到通知
- 前台 Task：每个节点完成后自动推送进度到对话
- 后台 Task：仅在关键节点（人工等待、完成、失败）选择性推送通知
- 用户主动查询：通过 `task_query` 返回当前状态 + 执行时间线

#### FR-31: Task 流程干预

用户和 Agent 可在 Task 执行过程中进行干预操作：

| 操作 | 适用状态 | 说明 |
|------|----------|------|
| `approve` | `waiting_human` | 审批通过，恢复执行 |
| `reject` | `waiting_human` | 驳回，Task 进入 `failed` |
| `skip` | `waiting_human` | 跳过当前节点继续 |
| `pause` | `running` | 暂停执行 |
| `resume` | `paused` | 恢复执行 |
| `cancel` | `running`/`waiting_human`/`paused` | 取消 Task |
| `rollback` | `running` | 回滚到指定节点重新执行 |
| `inject` | `running`/`paused` | 注入/修改变量（如用户纠正参数） |

干预操作使用乐观锁（version 字段），并发冲突时提示"Task 状态已变更，请重新获取"。干预日志记录所有请求的发起时间和结果。

**Consequences (testable):**
- 用户在对话中可对 waiting_human 状态的 Task 执行审批/驳回/跳过
- Agent 可调用 `task_intervene` 执行干预，用户无感知底层 API
- 并发干预时版本冲突被正确检测和提示
- 所有干预操作记录在审计日志中

#### FR-32: Agent 系统级 Task 工具

Agent 必须拥有以下 Task 管理工具，以在对话中无缝管理 Task 生命周期：

| 工具 | 用途 |
|------|------|
| `search_workflow` | 语义检索 Workflow（辅助，非必须） |
| `get_workflow_schema` | 获取指定 Workflow 的输入参数定义 |
| `create_task` | 创建 Task（传入 `workflow_id` + `variables`） |
| `task_query` | 查询 Task 进度（当前状态 + 执行时间线） |
| `task_intervene` | 审批、跳过、暂停、恢复等干预操作 |
| `task_list` | 列出用户关联的 Task |
| `cancel_task` | 取消一个不再需要的 Task |
| `get_task_timeline` | 获取 Task 的执行时间线 / 审计日志 |
| `update_task_variables` | 运行时修正变量（如用户纠正参数） |

**Consequences (testable):**
- Agent 能在对话中根据用户意图自动选择并创建对应 Workflow 的 Task
- 用户询问 Task 进度时，Agent 通过 `task_query` 获取并展示
- 用户表达"同意"/"不同意"时，Agent 自动执行 `task_intervene` 的 approve/reject

#### FR-33: Agent 与 Workflow 交互（能力地图）

Agent 启动时通过 Workflow Registry（能力地图）前置感知所有可用 Workflow，而非运行时临时检索。Registry 包含每个 Workflow 的：
- `when_to_use` — 触发条件描述（如"产线出现质量异常、不良率超标"）
- `required_entities` — 所需输入实体（如 `["station", "defect_type", "rate"]`）
- `has_human_node` — 是否包含人工审批环节
- `side_effects` — 潜在副作用（如"可能停线"）

Agent 决策机制：
- 查数据、问状态、单次只读 → **Direct** 工具调用
- 涉及停线、改参数、跨系统写、需审批 → **必须创建 Task 走 Workflow**
- 不确定时 → 先 Direct 回答，提示"可走流程"

变量提取流程：Agent 从用户输入提取实体 → Session 上下文补充 → 按 `input_schema` 类型转换 → Required 缺失则主动询问用户 → 调用 `create_task`。

**Consequences (testable):**
- Agent 启动时加载所有已发布 Workflow 的 Registry 信息
- 用户描述匹配 `when_to_use` 时，Agent 自动建议创建对应 Task
- 必填变量缺失时，Agent 主动询问用户补充
- 执行日志记录 Agent 的 Workflow 选择决策和变量提取过程

### 4.4 工具系统

**Description:** 工具独立于 Agent 存在，Agent 自由组合使用。工具来源包括 Skill（Markdown 格式）和 MCP（外部协议连接）。平台提供统一的工具接口，Agent 不感知工具来源差异。Realizes UJ-3.

**Functional Requirements:**

#### FR-13: Skill 管理

平台支持三种 Skill 来源：
- **前端创建** — 在 Web 界面中编写 Markdown 格式的 Skill 定义
- **Git 拉取** — 配置 Git 仓库地址，平台自动拉取并解析 Skill 文件
- **文件上传** — 上传 Markdown 文件或包含多个 Skill 的目录

Skill 定义包含工具名称、描述、参数说明和调用方式。平台解析 Skill 文件后注册到工具池。

**Consequences (testable):**
- 前端创建的 Skill 保存后立即出现在工具池中
- Git 拉取成功后，仓库中的 Skill 文件解析并注册到工具池
- 上传的文件解析后注册到工具池
- Skill 定义格式错误时，平台给出明确的错误提示

#### FR-14: MCP 连接管理

用户配置 MCP 服务器地址和认证信息后，平台连接 MCP 服务器并自动发现其提供的工具列表。用户选择需要的工具注册到工具池。MCP 工具的状态（可用/不可用）实时反映连接状态。

**Consequences (testable):**
- 配置 MCP 服务器后，平台列出该服务器提供的所有工具
- 选择工具并保存后，工具出现在工具池中
- MCP 服务器断连时，相关工具状态标记为"不可用"
- MCP 服务器恢复后，工具状态自动恢复为"可用"

#### FR-15: 工具池与统一接口

平台维护统一的工具池。所有工具（无论来自 Skill 还是 MCP）在工具池中以统一格式呈现。Agent 配置时从工具池中选择工具，不感知工具的来源差异。

**Consequences (testable):**
- 工具池列表同时展示 Skill 和 MCP 来源的工具
- Agent 配置界面的工具选择不区分工具来源
- 工具被多个 Agent 引用时，删除操作需确认影响范围

### 4.5 知识库管理

**Description:** 用户创建知识库并上传文档（PDF、Word、Markdown 等）。Agent 配置时绑定知识库，运行时通过检索获取相关知识辅助推理。

**Functional Requirements:**

#### FR-16: 知识库创建与文档管理

用户创建知识库，上传文档，平台自动解析、分块和索引。知识库支持增删改操作，文档更新后自动重新索引。

**Consequences (testable):**
- 上传文档后，平台在合理时间内完成解析和索引
- 知识库列表展示所有知识库及其文档数量和状态
- 删除文档后，Agent 后续检索不再返回该文档的内容

#### FR-17: 知识库检索

Agent 运行时根据任务上下文自动检索绑定的知识库，获取相关文档片段辅助推理。检索结果包含相关度评分。

**Consequences (testable):**
- Agent 在推理过程中能引用知识库中的内容
- 检索结果包含来源文档和片段位置信息

### 4.6 API/SDK 接口

**Description:** 外部系统通过 RESTful API 和 SDK 接入平台，调用 Agent 能力。API 支持同步和异步调用模式。这是平台作为"AI 能力中台"对外输出的核心通道。Realizes UJ-2.

**Functional Requirements:**

#### FR-18: Agent 调用 API

外部系统通过 API 向指定 Agent 发送任务，获取执行结果。支持同步调用（等待结果返回）和异步调用（返回任务 ID，通过回调或轮询获取结果）。

**Consequences (testable):**
- API 接受 Agent ID 和任务内容作为输入
- 同步调用在 Agent 完成后返回结果
- 异步调用返回任务 ID，可通过查询接口获取状态和结果
- API 调用需要认证（API Key 或 Token）

#### FR-19: 事件回调

外部系统可注册回调 URL，Agent 任务完成或状态变更时主动通知。

**Consequences (testable):**
- 注册回调 URL 后，Agent 完成任务时向该 URL 发送通知
- 通知包含任务 ID、状态和结果摘要
- 回调失败时平台按重试策略重试

### 4.7 对话交互

**Description:** 用户在 Web 界面上与 Agent 直接对话，测试 Agent 能力或进行交互式任务。对话中 Agent 可触发已配置的工作流。对话历史持久化保存。

**Functional Requirements:**

#### FR-20: Agent 对话界面

平台提供 Web 对话界面。用户选择一个 Agent 后开始对话。对话支持文本输入和多轮交互。Agent 的回复包含推理过程和工具调用结果（可折叠展示）。

**Consequences (testable):**
- 用户选择 Agent 后可立即开始对话
- 对话历史持久化，刷新页面后可恢复
- Agent 回复中展示工具调用和推理过程的摘要

#### FR-21: 对话触发工作流

用户在对话中输入多步骤任务时，Agent 可自动触发已配置的工作流执行。工作流执行结果在对话中展示。

**Consequences (testable):**
- 用户在对话中输入多步骤指令时，Agent 自动匹配并执行对应工作流
- 工作流执行过程和结果在对话界面中展示
- 用户可以对工作流结果追问，Agent 继续推理

### 4.8 上下文管理

**Description:** 平台管理 Agent 对话和 Task 执行中的上下文信息，采用三层隔离架构（Session/Task/Node），包括消息历史、变量池传递和上下文压缩，确保长对话和多步骤执行的效果。对话与工作流支持双向触发。

**Functional Requirements:**

#### FR-22: 三层上下文隔离

平台维护三层隔离的上下文体系：

| 层级 | 作用域 | 内容 | 生命周期 |
|------|--------|------|----------|
| **Session Context** | 对话级，持久化 | 用户实体、偏好、话题引用、Task 状态摘要 | 对话全周期 |
| **Task Context** | Task 级，隔离 | 变量池、节点执行状态、审计日志 | Task 全周期，完成/失败后可配置保留 N 天后清理 |
| **Node Context** | 节点级，临时 | Agent Prompt、Tool 参数、节点输出 | 保留至 Task 结束（human 节点审批时仍可查看前置 Agent 输出） |

流转规则：
- **创建 Task 时**：按 `input_schema` 声明字段从 Session 浅拷贝 + 类型转换（非全量深拷贝），避免循环引用/超大对象/敏感数据泄漏
- **事件同步**：只同步状态摘要（`status`、`current_node`、`can_intervene`），不同步内部节点变量
- **Task 完成后**：按 `output_schema` 映射结果回 Session 上下文

**Consequences (testable):**
- Task 变量池与 Session 上下文物理隔离，Task 失败不污染对话
- 创建 Task 时仅拷贝 `input_schema` 声明的字段，非全量深拷贝
- Task 状态变更时仅同步摘要到 Session（不泄露节点内部变量）
- human 节点审批时前置 Agent 节点的输出仍可查看

#### FR-22A: 对话上下文压缩

平台自动管理对话上下文，当对话历史超出模型上下文窗口时，自动压缩历史消息（保留关键信息，丢弃冗余内容），确保 Agent 在长对话中保持连贯。

**Consequences (testable):**
- 长对话（超过模型上下文窗口）不导致报错或信息丢失
- 压缩后的上下文保留对话中的关键决策和结果

#### FR-23: Task 触发对话

Workflow 中 Agent 节点可创建新对话或恢复已有对话。对话和 Task 各自生命周期独立：Task 节点执行完成后对话可继续存在，对话中触发的 Task 完成后对话不中断。

**Consequences (testable):**
- Workflow 中 Agent 节点可创建独立的新对话
- Agent 节点可恢复指定 ID 的已有对话继续交互
- Task 执行完成后，被创建/恢复的对话仍可持续使用
- 对话和 Task 的执行日志分别记录，通过调用链关联

#### FR-24: 变量池与表达式注入

Task 运行时维护独立的变量池，节点间通过 `{{node_id.field}}` 表达式读取上游输出。变量池支持以下机制：
- **输入**：`input_schema` 声明创建时必须传入的变量
- **节点输出**：按 `output_schema` 结构化写入（前缀为节点 ID，如 `n1.cause`）
- **输出**：Task 完成后按 `output_schema` 映射回 Session 上下文
- **Null-safe 处理**：变量未定义时，gateway 条件视为 `false` 走 fallback，params 注入视为 `null` 由接收节点处理

**Consequences (testable):**
- Workflow 编辑器中可视配置节点间的数据映射关系
- 运行时数据按 `{{node_id.field}}` 表达式在节点间传递
- 类型不匹配或变量未定义时给出明确提示或走 fallback
- 变量访问表达式求值错误不传播到引擎级

### 4.9 执行日志与可观测性

**Description:** 所有 Agent 推理、工具调用和 Task 执行均记录完整日志。开发人员和管理员可通过 Web 界面查看执行历史、调用链和性能指标。审计日志全量记录，支持分布式调用链追踪。

**Functional Requirements:**

#### FR-25: 执行日志记录

平台记录每一次 Job 执行的完整日志，包括：路径选择结果、每步推理内容、工具调用参数和结果、Task 节点执行详情、耗时和状态。审计日志全量记录 Task 创建、节点执行、干预操作、状态变更，附加操作人和时间戳。

**Consequences (testable):**
- 每次 Job 执行后可查看完整执行日志
- 日志包含调用链（Agent → Task → 节点 → 工具的完整链路）
- 日志支持按时间、Agent、Task 状态等条件筛选
- 审计日志记录所有干预操作（操作人、时间、结果）

#### FR-26: 调用链追踪

平台对 Agent → Task → Agent（嵌套）的调用链进行追踪，展示完整的执行树。支持从单次 Job 入口查看所有下游调用。支持分布式 tracing，跨 subflow 链路串联。

**Consequences (testable):**
- 调用链视图展示 Job 的完整执行树（含 Task、子 Task）
- 支持展开查看每个节点的详细输入输出
- 跨 subflow 的调用链可完整串联

### 4.10 权限管理

**Description:** 平台提供基础的用户认证和权限管理，确保不同角色的用户只能访问其授权的资源。

**Functional Requirements:**

#### FR-27: 用户认证与角色管理

平台支持用户登录认证和角色的划分（管理员、开发者、操作员、只读用户）。不同角色对 Agent、工作流、工具、知识库有不同的操作权限。

**Consequences (testable):**
- 用户登录后才能访问平台功能
- 开发者角色可创建和编辑 Agent、工作流、工具
- 操作员角色可查看 Agent 分析结果、调整已授权的 Agent 参数、查看执行历史
- 只读用户只能查看已有的 Agent 对话
- 管理员可管理用户、角色和平台配置

### 4.11 Web 管理界面

**Description:** 平台提供完整的 Web 管理界面，涵盖 Agent 管理、工作流编排、工具管理、知识库管理、对话面板、执行日志查看和权限管理等全部功能。

**Functional Requirements:**

#### FR-28: 统一管理界面

平台提供基于 Web 的统一管理界面。界面采用侧边导航 + 主内容区布局，主要模块包括：仪表盘、Agent 管理、工作流管理、Task 管理面板（查看 Task 状态、审批/干预）、工具管理、知识库管理、对话面板、执行日志、系统设置。

**Consequences (testable):**
- 所有平台功能通过 Web 界面操作，无需命令行
- 界面响应时间在合理范围内（页面加载 ≤ 3 秒）
- 界面支持中文
- Task 管理面板可查看 Task 状态、执行时间线，支持审批/驳回/跳过/暂停/恢复等操作

## 5. Cross-Cutting NFRs

### Performance
- API 同步调用响应时间：Agent 直接执行模式下 ≤ 30 秒返回首条结果
- Web 界面首屏加载 ≤ 3 秒，工作流编辑器画布操作流畅无明显卡顿
- 对话流式输出，用户无需等待完整响应即可看到中间结果
- 前台 Task 超过 30 秒自动转后台，不阻塞用户对话

### Reliability
- API 调用成功率 ≥ 99%（排除 Agent 自身推理错误和外部工具故障）
- 单个组件故障（如 MCP 服务器断连）不导致整个平台不可用
- Workflow Engine 不可用时：Direct 模式仍可用（查数据、问状态），新建 Task 排队等待
- 执行日志持久化存储，不因服务重启丢失
- 单 Tool 超时/熔断不影响其他 Tool

### Security
- 所有 API 调用需认证（API Key 或 Token）
- 用户密码加密存储，不落明文日志
- 执行日志中敏感信息（API Key、密码等）脱敏处理
- Task 变量池隔离，不泄漏跨 Task 数据

### Scalability
- 单机部署，支持 50 用户同时在线
- 单用户同时运行 ≤ 5 个并发 Task，全局并发上限 ≤ 50（可配置）
- 同一 Workflow 允许最多 N 个并行 Task（N 在模板定义中声明）

### Concurrency
- Task 干预操作使用乐观锁（version 字段），冲突时提示重新获取
- 审计日志记录所有并发干预请求的发起时间和结果

### Data
- 对话历史和执行日志持久化，支持按时间范围查询
- 运行时日志保留 30 天，审计日志保留 90 天（可配置）
- 文档上传大小限制可配置（默认单文件 ≤ 50MB）

## 6. Non-Goals (Explicit)

- **不做 SaaS 多租户和计费系统** — 内部产品，单租户，不需要计费
- **不做应用市场 / 模板市场** — MVP 不做 Skill 或工作流的市场化分发
- **不做移动端界面** — 仅 Web 界面
- **不做 100+ LLM 模型支持** — 5-10 个主流模型足够
- **不做有环状态图模式** — MVP 只做 DAG，高级模式后续迭代
- **不做代码执行节点** — Workflow MVP 不含代码执行和 HTTP 请求节点
- **不做 Scheduled Workflow** — MVP 不支持 Cron 定时触发和 prefetch 自动执行。后续迭代引入 Timer/Event 节点和 Scheduled Workflow 形态
- **不做 Timer 节点和 Event 节点** — 涉及外部事件总线集成，复杂度较高，在 Scheduled Workflow 形态成熟后再引入
- **不做断点续跑** — 后续迭代
- **不做部门级隔离** — MVP 权限为扁平的四角色模型，不区分部门。部门级资源隔离和跨部门共享后续迭代
- **不做事件驱动的 Agent 自动触发** — MVP 不支持 Agent 主动监听外部数据流（如 MQTT、OPC-UA）并自动触发执行，仅支持 API 调用和对话触发的请求-响应模式。后续迭代。
- **不做开放平台** — 不提供外部开发者注册和第三方接入
- **不做通用 RAG 管线** — 不与 Dify 竞争 RAG 能力，MVP 提供基础文档检索即可

## 7. MVP Scope

### 7.1 In Scope

- Agent 完整生命周期（创建、配置、发布、调用、删除）
- Agent 自主规划与执行（模型自主 Job 分类 + REACT 自由推理 + 工作流执行）
- DAG 工作流编排器（8 种核心节点：start/end/agent/tool/human/gateway/parallel/subflow + 条件边）
- Task 生命周期管理（完整状态机 + 前后台模式 + 流程干预）
- 变量池与表达式注入（节点间数据流转 + null-safe 处理）
- Agent-Workflow 交互（Workflow Registry 能力地图 + 变量提取 + Task 工具集）
- 三层上下文隔离（Session/Task/Node）
- 工具系统（Skill 三种来源 + MCP 连接 + 统一工具池）
- 知识库（文档上传、解析索引、基础检索）
- API/SDK（Agent 调用接口 + 事件回调）
- 对话交互（Web 对话界面 + 对话触发 Workflow 创建 Task）
- 上下文管理与压缩
- 执行日志与调用链追踪（含审计日志）
- 基础权限管理（登录认证 + 四角色）
- Web 管理界面（统一界面 + Task 管理面板，全部功能可操作）

### 7.2 Out of Scope for MVP

- Scheduled Workflow（Cron 定时触发 + prefetch + escalation） — 后续迭代
- Timer 节点和 Event 节点 — 依赖事件总线，后续迭代
- 高级工作流模式（有环状态图） — 复杂度高，DAG 已覆盖大部分场景
- 代码执行节点和 HTTP 请求节点 — 通过 MCP 和 Skill 扩展可覆盖部分需求
- Workflow 模板导出/导入 — 后续迭代
- 断点续跑 — 后续迭代
- 模型 A/B 测试 — 后续迭代
- 高级 RAG（混合检索、重排序） — MVP 做基础检索
- 事件总线（at-least-once 投递、死信队列、背压处理） — 基础设施层，架构阶段设计
- Workflow Engine 高可用（多副本、主从选举） — 基础设施层，架构阶段设计
- `[NOTE FOR PM:]` Scheduled Workflow 和 Timer/Event 节点是用户呼声最高的后续功能，如果 MVP 验证顺利，应优先排期。

## 8. Success Metrics

**Primary**
- **SM-1**: 开发者创建到可用 — 从新建 Agent 到完成配置并成功执行一次 Job 的时间 ≤ 30 分钟。Validates FR-1, FR-2, FR-28.
- **SM-2**: Job 评估准确率 — Agent 对 Job 大小判断（直接执行 vs 规划执行 vs 工作流匹配）的准确率 ≥ 85%。Validates FR-4.
- **SM-3**: 外部系统调用成功率 — MES 等外部系统通过 API 调用 Agent 的成功率 ≥ 99%（排除 Agent 自身推理错误）。Validates FR-18, FR-19.

**Secondary**
- **SM-4**: Workflow 编排效率 — 开发者从创建 Workflow 到发布可用的平均时间 ≤ 15 分钟。Validates FR-9, FR-10.
- **SM-5**: 工具注册到可用时间 — 新 Skill 或 MCP 工具从注册到 Agent 可调用的时间 ≤ 5 分钟。Validates FR-13, FR-14, FR-15.
- **SM-6**: 执行日志完整性 — 每次 Job 执行可查看完整调用链的比例 = 100%。Validates FR-25, FR-26.
- **SM-7**: Task 状态机可靠性 — Task 状态转换全部符合状态机定义的比例 = 100%。Validates FR-29.
- **SM-8**: 流程干预响应时间 — 用户执行审批/驳回操作后 Task 恢复执行的时间 ≤ 2 秒。Validates FR-31.

**Counter-metrics (do not optimize)**
- **SM-C1**: Agent 推理成本 — 不应为了提高 SM-2 而在每次 Job 前都做复杂分类推理，需控制分类步骤的 Token 消耗。平衡点：Job 评估应在单次 LLM 调用中完成，不额外增加独立分类步骤。Counterbalances SM-2.
- **SM-C2**: Workflow 执行速度 — 不应为了提高执行速度而跳过日志记录和变量传递。Counterbalances SM-3, SM-6.

## 9. Open Questions

1. 规划执行模式中，Agent 生成执行计划的格式和粒度如何定义？计划是结构化的步骤列表还是自然语言描述？
2. 验证阶段的失败处理策略：验证不通过时，Agent 重试的最大次数和回退策略是什么？
3. MCP 服务器认证方式有哪些？需要支持哪些认证协议（OAuth、API Key、无认证）？
4. 知识库的文档格式支持范围？MVP 是否需要支持 OCR（扫描件 PDF）？
5. API 认证方式：API Key 还是 OAuth Token？是否需要支持多种认证方式？
6. 对话历史的保留策略？是否有过期清理机制？
7. 并发控制策略：单用户同时可运行多少个 Agent 任务？全平台的并发上限是多少？

## 10. Assumptions Index

- `[ASSUMPTION: §4.1]` MVP 支持的 5-10 个 LLM 模型包括 OpenAI GPT 系列、Claude 系列和至少一个国产模型，具体列表待技术选型确定。
- `[ASSUMPTION: §4.1]` 模型动态路由规则由开发者在 Agent 配置时手动定义（如"工具调用类任务用模型A，纯推理类任务用模型B"），不做全自动路由。全自动路由待后续迭代。
- `[ASSUMPTION: §4.2]` Job 评估由模型自身完成，不需要额外的分类模型。MVP 阶段依赖 Agent 的系统提示词引导其正确判断 Job 大小。
- `[ASSUMPTION: §4.2]` 规划执行模式的"计划→执行→验证"三阶段在单次模型调用链内完成，不需要额外的编排引擎。
- `[ASSUMPTION: §4.3]` Workflow MVP 不包含 HTTP 请求节点和代码执行节点。MES 等外部服务的接入通过 MCP 和 Skill 扩展实现。
- `[ASSUMPTION: §4.3]` Workflow 模板装配由规则引擎执行（变量替换 + 条件节点渲染），LLM 仅参与参数推荐，不参与结构变更。确保 Workflow 确定性。
- `[ASSUMPTION: §4.3]` Workflow MVP 不包含 Timer 和 Event 节点，后续迭代引入。
- `[ASSUMPTION: §4.3A]` Task 状态机的状态转换规则在 FR-29 中明确列出，未列出的转换（如从 `failed` 回到 `running`）不允许。
- `[ASSUMPTION: §4.3A]` 前台 Task 30 秒未完成自动转后台，30 秒阈值可在架构阶段调整。
- `[ASSUMPTION: §4.3A]` Task 流程干预使用乐观锁，而非悲观锁，以避免长时间阻塞。
- `[ASSUMPTION: §4.3A]` Workflow Registry 支持拆分为"核心（高频）"和"扩展（低频）"两层，MVP 阶段先做单层，扩展后做 RAG 检索增强。
- `[ASSUMPTION: §4.4]` Skill 的 Markdown 格式遵循特定 schema（工具名、描述、参数、调用方式），需要定义标准模板。
- `[ASSUMPTION: §4.5]` MVP 阶段知识库使用向量检索（embedding + 相似度搜索），不涉及混合检索或重排序。
- `[ASSUMPTION: §4.8]` 创建 Task 时从 Session 上下文仅拷贝 `input_schema` 声明的字段（浅拷贝 + 类型转换），非全量深拷贝。
- `[ASSUMPTION: §4.8]` Task 完成后按 `output_schema` 映射结果回 Session 上下文，内部节点变量不同步。
- `[ASSUMPTION: §4.10]` MVP 的权限模型为四角色（管理员/开发者/操作员/只读），不做细粒度的资源级权限控制和部门级隔离。
- `[ASSUMPTION: §4.11]` Web 前端技术选型参考 LangFlow 的 React + React Flow 方案，后端采用成熟框架（具体待技术选型）。
