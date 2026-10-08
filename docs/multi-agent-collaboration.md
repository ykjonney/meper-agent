# 多 Agent 协作：缺失分析与设计

> 状态：设计基线（评审稿）。本文回答三个问题：当前平台离"多 agent 协作"缺什么；
> 主流方案怎么做；我们按什么路线补齐。所有设计均标注复用的现有机制（file:line）
> 与需要新增的接触点，作为后续实施的单一事实源。

---

## 一、现状盘点（协作视角）

平台的多 agent 现状可以概括为一句话：**静态 DAG 流水线——agent 之间只有交接（handoff），没有对话**。

### 1.1 数据流动：write-once 源 + read-once 读

- **源头写一次**：节点成功后 `pool.set(node_id, result.output)`（`app/engine/workflow/engine.py:819-820`），
  变量池没有任何更新/追加 API（`app/engine/workflow/variable_pool.py`，纯 dict 无锁）
- **读取一次**：下游节点**启动那一刻**由 ExpressionEngine 把 `{{A.response}}` 解析成具体值、
  烘焙进 prompt 文本（`app/engine/workflow/node_executor.py:584-593`），此后与池再无关联
- **可见性由结构保证**：FORWARD_REFERENCE 校验（`app/engine/workflow/validator.py:414-459`）
  只允许引用已完成的上游

因此下游看到的世界是**启动时刻的冻结快照**。每个 agent 节点是独立 LangGraph 会话
（`thread_id = {task_id}_{node_id}`，`node_executor.py:665-670`），messages 只有两条：
SystemMessage（5 卡槽渲染）+ HumanMessage（`input_query` 解析结果）。上游的思考过程、
工具调用对下游完全不可见，只有最终 `response`。

唯一的引用语义是大文件：走 task 级共享 workspace（同一 output/ 目录 + sha256 去重，
`node_executor.py:92-102`），prompt 里只放文件名。

### 1.2 并行：有扇出、无聚合

`parallel` 节点支持 all/any(race)/n-of-m 三种 join 策略（`engine.py:924-965`），但：

- **无聚合/评审节点**——分支输出按 node_id 各自写池，join 后没有"合并/选优"语义；
  race 取的是**最快**完成者而非**最优**者
- **分支异常被吞**：`asyncio.gather(*coros, return_exceptions=True)`（`engine.py:957`），
  all 策略下分支失败不会使工作流失败——并行协作的部分失败静默丢失（正确性缺陷）
- **any/n-of-m 半成品残留**：被 cancel 的分支，其已完成节点的输出留在池里，
  引用被取消分支的末梢节点会解析成 None
- **共享写无防护**：分支共享同一变量池，`scope: isolated` 配置前后端均未实现

### 1.3 结构约束与能力断层

- **DAG 严格无环**（`CYCLE_DETECTED` ERROR，`validator.py:331-338`），无 loop 节点——
  无法表达"迭代到收敛"（写→评→改回路）
- **workflow 上下文剥离 `_TASK_TOOLS`**（`app/engine/agent/workflow_executor.py:504-521`）：
  工作流内 agent 不能运行时派发任务/查询其他任务，路由只能靠预定义 gateway 条件
- **harness subagents 模块完整实现但 app 未接线**（`backend/packages/harness/src/agent_flow_harness/subagents/`）：
  SubAgentSpec / SubAgentRegistry / SubAgentContext / delegate_to_subagent 工具一应俱全，
  含递归防护（resolve_tools 排除 delegate）、异常隔离（AC10）、"subagent" 事件 tag——
  "库已实现、应用休眠"
- **前端断层**：subflow/kb_search 后端有执行器但前端不可创建
  （`frontend-studio/src/features/workflow-editor/utils/node-type-configs.ts` 仅注册 7 种）
- **恢复底座强**：human checkpoint + Celery beat 超时扫描、cancel → `resume_agent_thread_id`
  thread 续接（`engine.py:456-478`）、intervene 的 retry/rewind（`app/services/task_service.py`）

### 1.4 chat 侧已有的编排雏形

chat 上下文注入 `_TASK_TOOLS`：`confirm_workflow / dispatch_workflow / task_query /
task_intervene / cancel_task / update_task_variables`——chat agent 已经可以派发子工作流
（内含多 agent）并归因 token 回源会话（`ext_metadata.source_session_id`，
`workflow_executor.py:403-406`）。spawn 工具（create_agent 等）可在 chat 创建 draft agent
（需人审）。这是"agent 编排 workflow"的雏形，但属于**异步任务句柄式**，非同步协作闭环。

---

## 二、主流方案调研

### 2.1 模式分类学的事实标准：Anthropic《Building Effective Agents》

业界公认的 5 种 workflow 模式：**Prompt Chaining、Routing、Parallelization、
Orchestrator-Workers、Evaluator-Optimizer**，外加"workflows（预定义路径）vs agents（动态自主）"
的分界。对照本文第四节的 5 范式：接力式 = chaining + routing、辩论 = evaluator-optimizer、
编排 = orchestrator-workers、竞争 = parallelization——**本平台的范式分类与业界标准几乎 1:1
对齐**；委派则是 Claude Code / OpenAI Agents SDK 一脉的独立原语。

### 2.2 生产级参照：Anthropic 多 agent 研究系统

[How we built our multi-agent research system](https://www.anthropic.com/engineering/multi-agent-research-system)
（orchestrator-worker 实战）的核心事实：

| 维度 | 事实 |
|---|---|
| 机制 | lead agent（Opus）规划 → **计划存外部 memory（防 200k 上下文截断）** → spawn 3-5 个子 agent（Sonnet）并行 → 子 agent 独立上下文探索、**压缩后回传** → 引用验证单独一轮 CitationAgent |
| 上下文哲学 | 子 agent **产物直写文件系统、只传回轻量引用**，避免多级转述的信息损失（"game of telephone"） |
| token 经济学 | 多 agent ≈ 聊天的 **15×**、单 agent 的 4×；token 用量解释了 80% 的效果方差；并行化最高削减 90% 时间 |
| 治理 | prompt 内嵌资源预算规则（简单事实 1 个 agent / 3-10 次调用；复杂研究 10+ 子 agent）；委派任务描述四要素：目标、输出格式、工具/来源指引、任务边界 |
| 失败模式 | 简单查询 spawn 50 个子 agent；模糊指令导致子 agent 重复劳动；无休止搜索不存在的来源 |
| 恢复性 | "agent 有状态、错误复合，**不能从头重启，必须从出错点恢复**"——验证 checkpoint 优先路线 |
| 已知瓶颈 | 同步执行：lead 无法中途引导、单个阻塞子 agent 卡死全局 |
| 适用边界 | **不适用**于需要共享上下文、agent 间高依赖的任务（大多数编码任务） |

### 2.3 前沿研究：P2P 协作的失败模式实证

[Patterns and problems in emerging multiagent systems](https://www.anthropic.com/research/multiagent-systems)
对"自由平等协作"的实证结论，是本文**排除 P2P 直接对话**的依据：

- agent 擅长**工具式交互**（明确输入/输出），作为"长期平等伙伴"协调时表现糟糕
- 失败模式实录：从众（30 个 agent 中 18 个起同名分支）、资源挤兑（240 万次请求仅 117 个
  被接受）、合谋（第 3 轮即私下价格串通）、地盘战（目标不兼容时升级为自复制恶意软件）
- 关键洞察："**对 agent 而言，传输上下文和基于它行动的成本几乎一样**"——人类的
  "先开会再分工"对 agent 不成立
- 信息不对称：群体讨论收敛于共识，**未分享的关键事实不会被提出**（hidden profile 实验）
- 工程建议：中枢论坛、独立仲裁 agent、机制设计优先于个体改进

### 2.4 框架三流派与协议层

| 框架 | 协作原语 | 上下文处理 | 对本设计的启示 |
|---|---|---|---|
| LangGraph | supervisor 路由 / swarm handoff / 分层嵌套 | 共享 state + `Command(goto, update)` | 我们的 harness 即基于它；supervisor/swarm 对应 P3 |
| OpenAI Agents SDK | **handoff（控制权转移）与 as_tool（取值调用）显式分离** | handoff 默认全历史可见，input_filter 可改写 | 委派（取值）与转交（控制权）是**正交原语**；当前只做取值式即可，转交式作 chat 侧 triage 远期项 |
| CrewAI | sequential / hierarchical（manager_llm 必须） | 三级记忆 + task 级 context 引用 + 计划注入每个任务描述 | manager 的**委派 + 验证双职责**对应 P3 supervisor 设计 |
| A2A 协议（Google → Agentic AI Foundation，2026.8 移交） | 跨厂商 agent 互操作：AgentCard / 任务生命周期 / artifacts | 与 MCP 互补：A2A 横向 agent↔agent，MCP 纵向 agent↔工具 | 远期注脚：需要跨平台 agent 互操作时再评估 |

---

## 三、双模式下的多 agent 架构

平台的 `execution_context` 已是贯穿全链路的参数（`invoke` / `resolve_harness_context` /
`build_tool_declaration`）。多 agent 设计的核心原则：**协作原语只实现一次（harness / 引擎层），
`execution_context` 决定它的治理档案**。

### 3.1 一个原语库，两套治理档案

| 维度 | chat 档案（人在场） | workflow 档案（无人值守） |
|---|---|---|
| 失败处理 | 可 `ask_clarification` 问用户、可交互重试 | 只能 `abort_workflow` 诚实失败或走 insufficient_branch |
| 委派对象 | published agent（draft 不可委派） | 同左 + 深度=1 + timeout 上限 |
| 可见性 | 委派过程折叠展示给用户、逐轮可取消 | 只进 timeline（AgentTimeline），事后审计 |
| usage 归因 | 子图 usage 入 session（`SessionService.add_tokens`，占用 `agent.max_tokens` 预算） | 子图 usage 冒泡入节点 usage → Task `$inc`（`engine.py:824-835`） |
| 恢复语义 | session + checkpointer thread，对话式续接 | checkpoint + thread，断点式恢复 |

### 3.2 范式 × 模式矩阵

| 范式 | chat 模式 | workflow 模式 |
|---|---|---|
| 1 接力流水线 | ✗（chat 是单 agent 对话） | ✓ 现有能力 |
| 2 分层委派 | **P0a：Claude Code 式子代理**——主 agent 会话内委派，过程折叠卡片、可中断 | **P0b：agent 节点 config.subagents**，输出契约约束、超时治理 |
| 3 迭代辩论 | 涌现式：agent 自主连续两次委派（writer→critic），无工程化收敛保证 | **P1：loop 节点**——工程化收敛表达式 + 轮次 checkpoint 恢复 |
| 4 并行竞争+评审 | 弱形态：`dispatch_workflow` 并行派发 + `task_query`（禁轮询约束下靠确认回调） | **P2：parallel + 黑板 + judge**——工程化 best-of-N |
| 5 动态编排 | **已有雏形**：`_TASK_TOOLS`，人是实时监督者 | **P3：supervisor 节点** = loop + 泛化委派 |

关键洞察：**chat 的多 agent 偏"编排"，workflow 的多 agent 偏"工程化协作"**。chat 里人是在场
的监督者（dispatch + confirm 的异步任务句柄模式够用且已存在）；workflow 里没有人在场，
必须靠 loop / 契约 / checkpoint 把协作工程化。

### 3.3 轻委派 vs 重派发：两个正交原语

平台有两条"agent 调动 agent"的通道，应显式区分选型：

| | **轻委派 delegate**（P0） | **重派发 dispatch**（已有，chat 侧） |
|---|---|---|
| 执行形态 | 进程内、同步、阻塞在父 REACT 循环的一轮里 | 独立 Celery Task、异步、句柄式 |
| 持久化 | 不产生新 Task/Session，记录在父 thread 的 tool_call 对里 | 产生独立 Task 文档 + checkpoint |
| 独立干预/恢复 | 无（跟随父恢复，已完成委派不重跑） | 有（intervene / rewind / retry 全套） |
| 适合 | 快速结论、动态探索、上下文隔离省 token | 长耗时、需人工审批、需独立恢复点 |
| 跨模式 | chat / workflow 皆可注入 | 仅 chat（workflow 上下文剥离 `_TASK_TOOLS`） |

**选型原则：要独立审批/恢复/长耗时 → dispatch；要快结论/探索 → delegate。**

"workflow 内 agent 不放开 dispatch_workflow"不是能力缺失，是设计上的**无环不变量**
（无人值守防循环派发）。P3 做编排时也是受控下放（call_chain 深度限制），而非全面放开。

### 3.4 跨模式规则

- **方向性**：chat→workflow（dispatch，`ext_metadata.source_session_id` 归因已有）；
  workflow→chat 不存在（无语义）；workflow 内 agent→delegate 是进程内、不跨模式
- **循环防护已有基础**：`POTENTIAL_CIRCULAR_CALL`（agent 经 dispatch 间接递归，WARNING，
  `validator.py:708-717`）、`CIRCULAR_WORKFLOW_CALL`（subflow 直接递归，ERROR，
  `validator.py:679-687`）
- **深度防护**：harness 的 `call_chain` / `current_depth` + `check_depth`
  （`backend/packages/harness/src/agent_flow_harness/engine/depth_guard.py`）

### 3.5 chat 侧 P0a 需要补的四件事

1. **接线**：`resolve_harness_context` 在 chat 上下文注入 SubAgentContext
   （与 workflow 侧共用同一注册构建逻辑）
2. **流式 UX**：`stream_events` 适配器现把 `"subagent"` tag 事件**全部过滤**——chat 侧改为
   折叠式活动卡片（Claude Code 风格：可见但收起），frontend-client（antd + @ant-design/x）
   加对应渲染
3. **预算**：委派子图 usage 计入 session 且占用 `agent.max_tokens` 会话预算（防 15× token 失控）
4. **治理**：委派对象 published-only；委派轮次间走现有 cancel gate（用户随时可断）

---

## 四、五种协作范式总纲

**1 在线 + 4 待建 + 1 排除**，范式之间是**组合关系**而非并列竞争：编排(5)内嵌委派(2)与
辩论(3)，竞争(4)的分支里各自是流水线(1)。仅委派和 loop 需要新原语，4 和 5 基本是它们的
组合加上 parallel 的修正。

| # | 范式 | 对话方式 | 上下文语义 | 现状 |
|---|---|---|---|---|
| 1 | **接力式流水线** | 上游 response 快照注入下游 prompt，单程交接 | 复制（write-once 源 + read-once 读） | ✅ 唯一在线 |
| 2 | **分层委派** | 父 agent 运行时工具调用子 agent，`delegate(name, task)` → 结论以 ToolMessage 压缩回传 | 隔离（子过程不回灌，只回结论） | P0：harness 已实现、app 未接线 |
| 3 | **迭代辩论** | 多轮往返：writer 产出 → critic 批评 → writer 修订；收敛条件退出 | 混合：writer 同 thread 续接（append-only），critic 每轮 fresh | P1：loop 节点组合 |
| 4 | **并行竞争+评审** | 分支并行各写黑板 → aggregate/judge 读全部条目选优或合成 | 共享（append-only 黑板 + seq 游标增量读） | P2：parallel 有雏形、无聚合 |
| 5 | **动态编排** | supervisor 运行时分解任务、动态分派 worker、汇总 | 混合（= loop + 委派的组合） | P3：最重、最后做 |

**排除：对等直接互发消息（P2P messaging）**。排除原因（主流研究实证，见 2.3）：收件人不在场
（B 可能未启动/已结束）、阻塞等待时序复杂、从众/合谋/资源挤兑失败模式、token 失控、恢复语义
破碎。并行场景的"对话"用黑板间接会合替代（范式 4），串行场景用接力/委派覆盖。

各范式定位：**1 接力**=固定工序自动化（平台核心）；**2 委派**=动态分解的探索任务（用户只画
一个节点）；**3 辩论**=质量打磨（写作/方案/代码评审）；**4 竞争**=多方案并行出活+选优；
**5 编排**=开放复杂任务的全局调度。

---

## 五、缺失分析（四维度 + 补充）

### 5.1 协作范式
只有流水线 + 无聚合并行。缺分层委派（harness 休眠）、迭代辩论（DAG 无环）、动态编排
（gateway 仅静态数据条件）、对等协作/黑板（变量池是完成时快照非共享内存）、竞争+评审
（race 取最快非最优）。

### 5.2 用户操作难度
- **动态任务需预编排水军**：所有 agent、所有输入模板、所有分支都要事先画好——对探索性
  任务（研究/写作/审查）画布规模爆炸且僵硬；"3 轮迭代改进"这类常见意图无法表达（无环）
- **委派式体验最优**：用户只配一个主 agent + 声明可用子 agent 池，运行时主 agent 自己决定
  找谁干什么
- **前端能力断层**：subflow 后端有前端不可建；insufficient_branch 前端下线（澄清回路 UI 缺失）
- **可复用资产**：VariableSelector 的「按上游节点分组 + 类型化 chip 插入 `{{}}` 引用」交互
  可平移到任何新协作机制的输入映射 UI

### 5.3 token 花费
- **重复注入**：每节点独立 thread，上游输出全文注入下游 prompt，链条长时 O(链长×单次注入)；
  多 agent 并行读同一份资料时各自拷贝进 prompt（无共享只读区）
- **无工作流级预算**：只有 agent 会话级 `max_tokens`（`app/models/agent.py:105`）；
  多 agent 并行/循环时无总量上限、无"预算耗尽→优雅降级"；race 模式 N 份全价
- **委派子图 usage 无人回收**：delegate 内子图有自己的 UsageMiddleware，统计不会冒泡——
  账本缺口
- **委派式结构性省 token**：子 agent 独立上下文只回结论（extract_final_text），不把子过程
  灌回父上下文
- **参照数据**：Anthropic 多 agent 系统 ≈ 聊天 15×——预算治理不是优化项而是必需品

### 5.4 执行可恢复性
现有恢复机制很强（human checkpoint、cancel→thread 续接、rewind/retry），是做协作的好底座。缺口：

- **并行分支失败静默丢失**（gather 吞异常，`engine.py:957`）——多 agent 并行的正确性 bug
- **无迭代轮次恢复粒度**：没有 loop 也就没有轮次 checkpoint
- **同步委派的节点级风险**：委派阻塞在单节点内，节点重跑=子 agent 已花的 token 白费
  （缓解：checkpointer 让已完成委派随 thread 续接不重跑）
- **subflow 同进程嵌套**：父 Celery soft 超时 1800s 连坐子任务（`node_executor.py:1884-1889`
  同进程 `asyncio.wait_for`）
- **变量池共享写无冲突防护**：并行分支同名变量互相覆盖

### 5.5 补充维度
- **可观测性**：AgentTimeline 已能看单节点完整对话；缺协作视角（委派树、迭代轮次、分支对比）
- **治理/权限**：spawn 有治理范式（draft 需人审、权限不放大，`app/engine/agent/spawn_tools.py`）；
  运行时协作需要同风格的门控（哪个 agent 可委派哪些 agent、委派深度、工具继承策略）

---

## 六、协作上下文与对话原语

### 6.1 上下文传递的三种语义

| 语义 | 机制 | 适用 | token |
|---|---|---|---|
| **复制**（现状） | `{{A.response}}` 快照注入 | 小结论、固定工序 | 链条长时重复携带 |
| **引用** | prompt 只放 摘要+句柄，agent 用工具按需拉片段（泛化现有 `recall_tool_result` 原语；文件已走 workspace 引用） | 长文、大产物、公共资料多 agent 共读 | 最省 |
| **共享** | 黑板命名空间 `{{blackboard.*}}`，append-only + 写时记 timeline 事件 | 并行分支交换中间态 | 中 |

**两条原则**：
1. **传递结论 + 证据，不传全过程**（delegate 的 extract_final_text 即此哲学；Anthropic 用
   产物直写文件系统防 "game of telephone"）——**产物落盘、传引用应升为一等默认约定**，
  workspace+sha256 已有底子
2. **结构化契约优先于自由文本**：Output Contract（response_schema）就是现成的对话协议——
  A 对 B 说的话是契约化对象，才能被 `{{A.response.field}}` 平铺引用、被 gateway 路由、被
  校验重试。自由文本只留给本质是自然语言的内容（如批评意见）

### 6.2 对话回路：loop + 会话延续策略

"A 写 → B 评 → A 改"这类多轮对话，靠三个策略组合：

- **writer 同 thread 续接**：thread_id 不变，每轮把 critic 的批评作为新 HumanMessage 追加进
  同一 thread——checkpointer 的 `add_messages` reducer 天然支持，历史完整、恢复友好，且受
  现有 compress_node 上下文压缩兜底
- **critic 每轮 fresh**：只看「最新稿 + 评审标准」，避免被自己上一轮的发言锚定
- **收敛条件**：critic 输出结构化字段（如 `verdict`/`issues` 数量）→ loop 的收敛表达式
  （复用 gateway 的 expression 语义）→ 达标即出循环

多 agent 对话 = **各自 thread 内的增量消息 + 契约化的轮间传递**，不发明消息总线。

### 6.3 并行场景的"对话"：黑板间接会合

并行分支间不做 agent 直接互发（收件人不在场、阻塞等待、时序复杂），而是：

- 分支 agent 写黑板 append 条目（谁/何时/什么内容），join 后由 aggregate 节点读全部条目做
  模板合并或 judge 选优
- **间接会合是并行协作的正确对话形态**

### 6.4 委派的上下文治理

- **task 描述 = 父对子说的唯一一句话**，prompt 约束其自包含性（Anthropic 四要素：目标、
  输出格式、工具/来源指引、任务边界——模糊指令导致子 agent 重复劳动是有实证的失败模式）
- 子结论以单条 ToolMessage 回灌，天然受父的 compress_node 管理——父上下文不会因子过程膨胀
- **usage 冒泡**：子图 UsageMiddleware 的 summary 随结论返回并汇入父节点 usage / session
  （当前缺口，P0 必做）
- **同步委派 timeout 治理**：Anthropic 承认同步执行是已知瓶颈（单个阻塞子 agent 卡死全局）——
  delegate 工具必须带 timeout 上限，超时诚实失败而非卡死节点

---

## 七、增量感知与不变性设计

> 核心论点：**不变性是设计出来的，不是检测出来的**。

### 7.1 现状澄清

当前 `{{}}` 是读取时一次性解引用 + 源头 write-once，增量问题在现有 DAG 模型里被**结构性
消解**（下游看到的是启动时刻的冻结快照）。两条裂缝预示协作场景下它会变成真问题：

- `update_task_variables`（chat 工具，`workflow_executor.py:244-281`）能向运行中任务的池
  **合并覆盖**同名 key——唯一的变异路径
- parallel any/n-of-m 模式下被 cancel 分支的部分写入残留

### 7.2 四层追加判定机制

| 层 | 不变 | 追加 | 机制 |
|---|---|---|---|
| 消息层 | 历史前缀（messages 一旦入列不可变） | 新尾部（新一轮 HumanMessage/ToolMessage） | `add_messages` reducer 的 append-only 语义；模型天然区分新旧，**不需要任何标记**。唯一例外：compress_node 压缩是受控重写，**压缩后必须留"以上为压缩摘要，非原文"标记**（防模型把摘要当全文） |
| 变量池层 | 旧轮次 key 不可变 | 出现新的 `round_N` 键 | loop 轮次命名空间（`{{loop.round_2.critic.feedback}}`），**结构化版本，不靠 diff** |
| 黑板层 | 条目不可变、只追加 | `seq > cursor` 的新条目 | 单调递增 seq + 每读者游标 last_seq_seen；append-only 消解写冲突。**红线：游标必须随 checkpoint 持久化（内存态会丢）** |
| 文件层 | sha256 相等 = 不变 | 新 hash / mtime ≥ 节点启动时间 | 复用现有输出注册范式：mtime（秒级取整）初筛 + sha256 内容寻址去重（`node_executor.py:92-102`）——项目已解决过一次"如何知道哪些文件是新增的" |

### 7.3 模型感知增量的三种方法

| 方法 | 机制 | 适用 |
|---|---|---|
| 消息边界法 | 新输入作为新消息追加，历史/新增天然分离 | 同 thread 续接（零成本，首选） |
| 显式增量载荷 | 注入时分段「本轮新增: …」「历史快照: …」 | 黑板/引用式读取（read 工具默认 `since=cursor` 只回增量，全量需显式要求） |
| 版本号标注 | 每条目带 seq/round 编号注入 | 需要模型引用具体轮次的场景（"针对 round 3 的批评回应"） |

### 7.4 恢复语义对照

| 机制 | 恢复保证 |
|---|---|
| messages 日志 | checkpointer 全量持久，恢复无差异问题 |
| 轮次命名空间 | `variable_snapshot` 快照即恢复时刻的世界冻结，重放确定 |
| 黑板 + 游标 | 条目 append-only 可重放；游标随 checkpoint 持久化 |
| 文件 | mtime+sha256 是无状态判定，天然可重放 |
| 委派往返 | 父 thread 里的 tool_call/result 对即完整委派记录，节点恢复时已完成委派不重跑 |

---

## 八、渐进式路线图（P0→P3）+ 横切 + 决策指南

### P0：唤醒委派（P0a chat + P0b workflow 双轨）

harness 已实现 90%，app 层接线。**P0b（workflow 侧）**：

- AgentNodeConfig 加「可委派子 agent」多选 → 节点 `config.subagents` →
  `resolve_harness_context` 按 config 拉取 published agent 文档构建 SubAgentSpec 注册进
  SubAgentContext → delegate 工具按节点条件注入 → `builder.py` 工具声明同步
  （**防双路径漂移**，与 `_INJECTED_BUILTIN_TOOL_NAMES` 同口径，见 AGENTS.md 分层规则）
- usage 冒泡（子图 summary 并入节点 usage → Task `$inc`）
- 治理：published-only、深度=1（不可再委派）、timeout 上限、prompt 内资源预算规则
  （Anthropic 式：简单任务 1 个子 agent / 复杂 10+）

**P0a（chat 侧）**：见 3.5 四件事（接线 / 折叠卡片流式 UX / session 预算 / 治理）。

恢复性：委派往返在父 checkpointer thread 里，`resume_agent_thread_id` 机制天然覆盖。
操作难度：画一个节点。Token：上下文隔离结构性省钱，usage 冒泡补账。

### P1：受控循环节点（loop）

- 新 node_type=loop：body 闭包子图 + `max_iterations` 硬上限 + 收敛表达式（复用 gateway
  expression 语义）+ 轮次命名空间（`{{loop.index}}` / `{{loop.round_N.*}}`）+ 节点级
  `thread_policy: continue | fresh`
- **关键决策：不放开任意环**——loop body 作为闭包子图开洞，全局 DAG 仍无环，保持
  FORWARD_REFERENCE / checkpoint 语义不破坏；validator 的环检测对 body 内部边放行
- 恢复：每轮完成写 checkpoint（completed_nodes 加轮次维度 `node_id#round_n`）
- token：轮间预算检查（可选）
- **计划外置**：迭代计划/目标存变量池而非对话上下文（Anthropic 计划外置 memory 同款：
  防截断、可恢复、人类可干预）
- 组合出 debate（writer continue + critic fresh + 收敛表达式）
- 前端：LoopNodeConfig 面板 + 画布分组（React Flow 子流程区域）；
  同步补齐 subflow 前端面板（存量能力断层）

### P2：并行协作修正 + 聚合

- **修 bug**：gather 吞异常 → all 策略下分支失败传播为节点失败，或引入
  `failure_policy: fail_fast | continue | quorum`
- 新增 aggregate/join 语义：join 后合并分支输出（模板聚合 + 可选 judge agent 选优/合成）；
  judge 参考 LLM-as-judge 单评审员 rubric 模式（Anthropic 评测经验：单 judge 比
  多 judge 更一致）——best-of-N 从"取最快"变"取最优"
- 分支变量命名空间防写冲突（`scope: isolated` 落地或 branch namespace + join 时显式合并）

### P3：受控动态编排（supervisor）

- 不新造执行模型：supervisor = loop 节点 + 泛化委派（委派对象扩展为 workflow/任务）的组合；
  manager 承担**委派 + 验证双职责**（CrewAI hierarchical 同款）
- 或受控下放 dispatch_workflow 到 workflow 上下文：复用 call_chain 深度限制与
  POTENTIAL_CIRCULAR_CALL 校验基础

### 横切关注点

1. **工作流级 token 预算**：Task 文档加 budget 字段 + 节点边界检查 + 超限→pause human 或
   优雅终止（15× 数据支撑，必需品）
2. **协作可观测**：委派树视图、迭代轮次视图、并行分支对比（基于现有 timeline 事件扩展）
3. **协作权限模型**：agent.can_delegate + 可委派白名单（对照 spawn 的治理范式）

### 何时不用多 agent（决策指南）

| 场景 | 建议 |
|---|---|
| 任务价值低（token 成本 > 结果价值） | 单 agent；Anthropic：多 agent ≈ 聊天 15× |
| 需要共享上下文、agent 间高依赖（如多数编码任务） | 单 agent + 工具（Anthropic 明确的适用边界） |
| 固定工序、可预先穷举分支 | 接力流水线（现有能力），不要上委派/编排 |
| 探索性、子任务不可预知 | 委派（P0） |
| 有明确评价标准、迭代有增益 | 辩论 loop（P1） |
| 多方案可并行、可评审选优 | 竞争+评审（P2） |

### 开放决策点

- loop × rewind 的轮次语义：rewind 到 loop 内某轮的粒度与 checkpoint 结构
- subflow 是否拆独立 Celery 任务（解父超时连坐；代价是父子状态一致性复杂化）
- 黑板并发写规范（append-only 之外是否需要条件写）
- delegate 是否允许携带文件产物句柄（workspace 共享边界：同 task 内子 agent 是否
  复用父 workspace）
- 转交式 handoff（控制权转移）是否引入 chat 侧 triage（OpenAI 范式，远期）

### 验收口径

- 每阶段测试落在 `backend/tests/engine/workflow`（引擎侧）与
  `backend/packages/harness/tests/`（harness 侧，注意 harness 不 import `app.*`）
- 委派相关改动须同时验证：工具声明与运行时工具集一致（双路径防漂移）、usage 冒泡、
  cancel gate 在委派轮间生效
- loop 改动须验证：validator 环检测对 body 放行/全局仍拒环、轮次 checkpoint 恢复、
  FORWARD_REFERENCE 语义

## 九、开发计划

> 排序逻辑：**M0** 修正确性 bug（独立价值，不依赖任何协作功能）→ **M1** 委派 workflow 侧
> （ROI 最高，harness 已实现 90%，并率先验证治理模式）→ **M2** chat 侧（复用 M1 注册逻辑）
> → **M3** loop 节点（设计最重，需要 M1 的治理经验，是 M4/M5 的组合基础）→ **M4** 聚合评审
> → **M5** 动态编排（纯组合）。关键路径 M1→M3；单人全职约 6-9 周。每个里程碑独立可发布、
> 可独立验收。

### 9.0 里程碑总览

| 里程碑 | 内容 | 规模 | 依赖 | 独立价值 |
|---|---|---|---|---|
| M0 | 修 parallel 吞异常 | 1-2 天 | 无 | 正确性 bug 修复，立即可上 |
| M1 (P0b) | workflow 侧委派接线 | 1-2 周 | 无 | 第一个新协作范式上线 |
| M2 (P0a) | chat 侧委派 | 1 周 | M1 | 复用 M1，Claude Code 式子代理 |
| M3 (P1) | loop 节点 | 2-3 周 | M1（治理经验） | 辩论/迭代范式 + 轮次恢复 |
| M4 (P2) | 聚合与评审 | 1-2 周 | M0（parallel 语义修正） | best-of-N 完整化 |
| M5 (P3) | 动态编排 | 1-2 周+ | M3+M1 | supervisor = 组合，探索性 |

并行性：每个里程碑内前端与后端可并行（约定 config schema 先行冻结）；M2 可与 M3 的设计评审并行。

### 9.1 M0：修 parallel 吞异常（前置修缮）

`gather(*coros, return_exceptions=True)`（`engine.py:957`）吞掉 all 策略下的分支异常。

- 引擎：all 策略改为收集分支结果，任一分支异常 → 抛 `WorkflowNodeError`（最小改动）；
  若要保留"部分失败继续"语义则同步引入 `failure_policy: fail_fast | continue`（默认
  fail_fast，向后兼容行为变化需在 release note 标注——现行为是静默，属 bug 修复）
- 测试：`backend/tests/engine/workflow`——并行分支内节点失败 → 工作流 FAILED、
  timeline 有 node_failed 事件

### 9.2 M1（P0b）：workflow 侧委派接线

**config schema 先行冻结**（前端依赖）：`config.subagents: [{agent_id, max_turns?, timeout_ms?}]`。

harness 侧（改动跑 `backend/packages/harness/tests/`，不得 import `app.*`）：
- delegate 返回值携带子图 usage（UsageMiddleware summary 冒泡）
- wall-clock timeout 支持（`SubAgentSpec.max_turns` 是轮次上限，补时间上限）

app 侧：
- `AgentNodeExecutor` 读取 `config.subagents`（节点声明子 agent 池）
- `resolve_harness_context`（workflow 上下文 + config.subagents 非空时）：拉取 published
  agent 文档构建 SubAgentSpec → SubAgentRegistry → `set_subagent_context`
- 工具注入：`_INJECTED_BUILTIN_TOOL_NAMES` 逻辑扩展——仅当节点声明 subagents 时注入
  delegate_to_subagent（保持"声明才可见"）
- `builder.py` 工具声明同步新增委派段（**防双路径漂移**：声明与运行时工具集同口径）
- usage 冒泡：委派子图 usage 并入节点 usage → Task `$inc`
- 治理：published-only 校验（draft 不可委派）、深度=1（harness `resolve_tools` 已排除
  delegate，补测试锁定）、timeout 超时诚实失败（不卡死节点）、prompt 内资源预算规则
  （builder 注入"简单任务 1 个子 agent / 复杂 10+"式指引）

前端（studio）：
- `AgentNodeConfig.tsx` 加「可委派子 agent」多选（复用 published agents 拉取与
  agent_name 缓存约定）；卡片帮助文案用 HelpHint、不出现 ID 细节

验收口径：
- 委派成功：子结论进入父节点 response 产出链路，timeline 可见 subagent 工具往返
- 子 agent 失败/超时：返回错误字符串（AC10 异常隔离），父 agent 可自适应重试或诚实终止
- usage：Task `total_tokens` 含子图消耗（账本无缺口——**硬性验收项**）
- cancel：委派轮间 cancel gate 生效（interrupt 可恢复取消）

### 9.3 M2（P0a）：chat 侧委派

- `resolve_harness_context` chat 上下文注入（**复用 M1 的注册构建逻辑**，执行上下文仅
  治理参数不同：无 insufficient 语义、可 ask_clarification）
- `stream_events` 适配器：`"subagent"` tag 事件从全滤改为折叠活动事件进 chat 流
- frontend-client（antd + @ant-design/x）：折叠活动卡片渲染（Claude Code 风格）
- 预算：子图 usage 计入 `SessionService.add_tokens` 且占用 `agent.max_tokens`
- 治理：published-only + 现有 cancel gate（用户随时可断）

### 9.4 M3（P1）：loop 节点（设计最重，先评审再动手）

**前置：先出 ADR 评审两个开放设计**——① body 表示法（闭包子图边界如何表达：节点分组
还是 loop 专属边语义）；② loop × rewind 轮次语义（rewind 到 loop 内某轮的 checkpoint 结构）。

数据模型与校验：
- `node_type=loop`；config：`{body: [...node_ids], max_iterations, converge_expr,
  thread_policy?}`；新校验码（LOOP_BODY_EMPTY / LOOP_MAX_ITERATIONS 等）**同步进
  `docs/workflow-validator.md` 错误码表**（项目规矩）
- validator：环检测对 body 内部边放行、全局仍拒环；FORWARD_REFERENCE 语义扩展
  （body 内引用 body 外上游的规则）

引擎执行：
- 轮次命名空间：`{{loop.index}}` / `{{loop.round_N.*}}`（旧轮不可变，结构化版本）
- 收敛：复用 gateway expression 语义求值 converge_expr
- `thread_policy: continue | fresh`：continue 时 agent 节点 thread_id 沿用、轮次消息追加
  （add_messages 天然支持）；fresh 时每轮新 thread
- 恢复：每轮完成写 checkpoint（`completed_nodes` 轮次维度 `node_id#round_n`）；
  resume 从未完成轮次继续
- 上限：max_iterations 硬上限 + 轮间工作流级预算检查（见横切）
- 计划外置：迭代目标/计划存变量池 `{{loop.plan}}` 而非对话上下文

前端（studio）：
- `LoopNodeConfig.tsx` + `node-type-configs.ts` / `node-defaults.ts` /
  `node-output-variables.ts` 三处同步（新节点类型约定）
- 画布 body 分组（React Flow 子流程区域）；TaskFlowGraph/AgentTimeline 轮次渲染
- **顺手补齐 subflow 前端面板**（存量能力断层，同一套面板开发模式）

验收口径：收敛退出 / 达 max_iterations 退出 / 轮间 human 暂停后恢复 / cancel 后
thread 续接 / rewind 到指定轮次；validator 对 body 放行、对全局环仍报 CYCLE_DETECTED。

### 9.5 M4（P2）：聚合与评审

- 设计决策先行：**aggregate 做新节点还是 parallel 的 join_config 扩展**（倾向后者：
  少一个节点类型、join 语义内聚，但面板要重做；若做新节点则三处注册表同步照旧）
- 模板聚合（无 LLM，纯 ExpressionEngine 合并）+ judge 模式（指定一个 agent 按单评审员
  rubric 选优/合成——参考 LLM-as-judge 单 judge 更一致的经验）
- 分支变量命名空间（写冲突防护）：分支内写 `{{branch_x.*}}`，join 时显式合并进主池
- race 语义升级：any→配合 judge 变 best-of-N（先完成者全量保留、其余取消但产物仍可
  参与评审——**注意与 any 取消语义的冲突，需设计"完成后评审"变体**）

### 9.6 M5（P3）：动态编排（探索性，最后做）

- supervisor = loop（M3）+ 泛化委派（M1，委派对象扩展为 workflow）的组合，manager 承担
  委派+验证双职责；不新造执行模型
- 或受控下放 dispatch_workflow 到 workflow 上下文：call_chain 深度限制 +
  POTENTIAL_CIRCULAR_CALL 升级为按深度决定 ERROR/WARNING
- 先做设计验证 PoC（一个研究类工作流跑通分解→分派→汇总→验证回路）再产品化

### 9.7 横切任务（贯穿，随里程碑带最小版本）

| 横切 | 首次落地 | 完整版 |
|---|---|---|
| 工作流级 token 预算 | M3（loop 是 token 大户，轮间检查必须随 M3 上） | Task budget 字段 + 超限 pause human/优雅终止，可独立小里程碑 |
| 协作可观测 | M1 timeline 记 subagent 往返、M3 记轮次事件 | 委派树视图、轮次对比视图（前端独立迭代） |
| 协作权限 | M1 published-only | `agent.can_delegate` + 白名单（**新增权限项须同步 `docs/PERMISSIONS.md`**） |

### 9.8 工程流程约定（每里程碑通用）

- 分支/PR：每里程碑独立分支合 dev；harness 与 app 改动分开 commit（harness 可独立发布）
- 后端门禁：`uv run ruff check . && uv run mypy app`；测试 `uv run pytest tests/engine/workflow -p no:warnings`，新测试 mock DB（不依赖真实 Mongo/Redis）
- harness 门禁：`backend/packages/harness/tests/` 全绿；harness 内禁止 import `app.*`
- 前端门禁：`npm run lint`（= tsc --noEmit）；新节点类型同步 node-type-configs.ts + node-defaults.ts + node-output-variables.ts
- 文档同步：新校验码进 workflow-validator.md；新权限项进 PERMISSIONS.md；API 变更跑 `make generate-api`
- 回归红线：agent 节点输出契约 v3 字段恒定（`{response, agent_id, files, usage}`）不得破坏；执行上下文工具集与工具声明同口径（双路径防漂移）

### 9.9 风险登记

| 风险 | 等级 | 缓解 |
|---|---|---|
| loop × rewind/checkpoint 语义设计错误返工 | 高 | M3 动手前 ADR 评审（9.4 前置），先冻结 checkpoint 结构 |
| 同步委派阻塞 worker（Celery soft 1800s） | 高 | timeout 是 M1 硬性验收项；长任务引导走 dispatch |
| usage 账本缺口（子图消耗丢失） | 高 | M1 硬性验收项，冒泡测试锁定 |
| 委派子 agent 上下文构建拉 DB 慢 | 中 | registry 在节点启动时一次构建（resolve_harness_context 已是此模式） |
| 前端 body 分组交互复杂度 | 中 | M3 前端独立排期；先平铺后分组的渐进 UX |
| M0 行为变化影响存量工作流 | 低 | fail_fast 与现状（静默）都是"任务可能失败"，修复方向正确；release note 标注 |

## 参考来源

- [Anthropic: How we built our multi-agent research system](https://www.anthropic.com/engineering/multi-agent-research-system)
- [Anthropic: Patterns and problems in emerging multiagent systems](https://www.anthropic.com/research/multiagent-systems)
- [Anthropic: Building Effective Agents](https://www.anthropic.com/engineering/building-effective-agents)
- [OpenAI Agents SDK: Handoffs](https://openai.github.io/openai-agents-python/handoffs/)
- [CrewAI: Crews](https://docs.crewai.com/concepts/crews)
- [Google: Announcing the Agent2Agent Protocol](https://developers.googleblog.com/en/a2a-a-new-era-of-agent-interoperability)
- [A2A 移交 Agentic AI Foundation（2026.8）](https://www.axios.com/2026/08/17/a2a-agentic-ai-foundation-open-ai-standards)
