# ADR：loop 节点（迭代/辩论范式，M3）

> 状态：**待评审**。本文定案两个开放设计（body 表示法、loop×rewind 轮次语义），
> 并给出数据模型、执行语义、校验、恢复与前端的第一期实施边界。
> 评审通过后按 §8 实施清单开发；相关背景见 `multi-agent-collaboration.md` 第五/七章。

---

## 0. 背景与目标

DAG 严格无环（`CYCLE_DETECTED` ERROR）使平台无法表达"迭代到收敛"——
辩论（writer→critic→writer）、迭代改进、批量映射三类范式都以受控循环为地基。
loop 节点 = **给无环 DAG 开一个受控的循环洞**，同时不破坏现有四项不变量：

1. 全局无环（除 loop 驱动的循环外，无自由回边）
2. FORWARD_REFERENCE（引用只能来自上游）
3. checkpoint 恢复语义（human 暂停 / cancel 续接 / rewind）
4. completed_nodes 防重入（节点不重复执行）

**非目标**（M3 明确不做）：嵌套 loop、循环内 human 之外的新暂停点、
轮次粒度的前端 rewind 交互（后端键已支持，UI 列 M3.1）。

---

## 1. 决策点一：body 表示法

### 选项 A：自由回边（体尾节点连回 loop 节点）

环检测对"指向 loop 的边"放行，其余环照拒。

- ✅ 数据结构零新增（就是普通边）
- ❌ 回边语义模糊：收敛判定挂在哪条边上？条件回边需要新表达式字段
- ❌ **摧毁 FORWARD_REFERENCE**：回边使拓扑序不存在，"上游"无法定义，
  体首节点引用循环前变量、体尾引用体首都需要特判
- ❌ 引擎 `completed_nodes` 防重入与多轮执行直接冲突，改动深且易错
- ❌ 画布回边视觉混乱，用户难理解"哪些节点在循环里"

### 选项 B：闭包子图（loop 节点持有 body 成员）★ **推荐**

loop 节点显式声明循环体成员；体内部路由用现有 `next_nodes`（可含
gateway 分支，甚至嵌套 parallel）；**封闭性由校验保证**（体节点的下游
必须在体内，出口由 loop 节点接管）。

- ✅ 与 parallel 的 `branches[].start_node` 同构——**代码库已有先例**，
  validator/引擎/前端的处理模式可平移
- ✅ 环检测不需要"放行"逻辑：body 内部照常检测，有环报专属码
  `LOOP_BODY_CYCLE`（体本身是 DAG，循环由 loop 驱动而非回边表达）
- ✅ FORWARD_REFERENCE 保得住：体节点引用 loop 之前的上游天然合法
  （拓扑上体在 loop 之后）
- ✅ `completed_nodes` 防重入保留：用轮次限定键（§2）而非破坏语义
- ❌ 需要"body 成员"的新校验（封闭性/入口存在性）
- ❌ 前端需要一个 loop 配置面板 + 成员标记（无交互容器，见 §6）

### 选项 C：React Flow 交互容器（group/parentId 包裹）

- ✅ 视觉直觉最好（拖进循环区域即成员）
- ❌ 编辑器交互改动大（拖入/拖出/误拖），M3 排期不可承受
- 定位：**B 的视觉增强项，M3.1+**

### 决策：**选项 B**。C 作为后续视觉增强。

---

## 2. 决策点二：loop × rewind 轮次语义

### 现状约束

- `completed_nodes`：`set[node_id]`，rewind = 裁剪回目标节点（`task_service.py:1478-1491`）
- checkpoint：`{paused_at_node, completed_nodes, variable_snapshot, human_context...}`
- agent thread：`{task_id}_{node_id}`，跨轮是否同 thread 由会话延续策略决定
- 变量池 write-once（节点成功后 set）

### 选项 A：轮次限定键 + 裸键最新值 ★ **推荐**

**completed/checkpoint 键**：`f"{node_id}#r{N}"`（`writer#r1`、`critic#r2`）。
恢复/rewind 以 (node_id, round) 为粒度。

**变量池双地址**：
- **裸键 = 最新轮**：体节点输出每轮正常写裸键（`{{writer.response}}`
  永远指最新轮）——体外下游引用与现有直觉零差异
- **`loop.rounds[N].<node_id>` = 不可变历史**：每轮开始前把上一轮的体节点
  输出快照进 `loop.rounds[N-1]`；需要回看历史（"针对第 1 稿的批评"）用
  `{{loop.rounds.1.writer.response}}`
- loop 节点自身输出：`{{loop.iterations}}`（实际轮数）、`{{loop.converged}}`
  （bool）、`{{loop.rounds}}`（全历史）——下游条件边可按 converged 路由
  （收敛走 A、达上限走 B），**复用现有条件边表达式，不加新出口机制**

- ✅ rewind 粒度到轮：rewind 到 `writer#r2` = 清除 r2 起所有键，从该轮重跑
- ✅ 体外引用零学习成本（裸名即最新）
- ✅ 历史可回看且不可变（第七章增量感知设计落地：轮次=结构化版本）
- ❌ 双地址有轻微心智负担（裸名会"变"）——用文档与输出变量表说明

### 选项 B：每轮全量池快照隔离

每轮复制变量池，轮末合并。内存 O(轮×池)、合并冲突语义复杂——否。

### 会话延续（thread_policy）

**节点级**字段 `loop_thread_policy: continue | fresh`（默认 `continue`，
仅在 loop 体内生效，体外静默忽略）——节点级才有辩论场景的表达力
（writer=continue 记得上一稿与批评；critic=fresh 不被自己上轮发言锚定）：

- `continue`：thread_id 维持 `{task_id}_{node_id}`，每轮消息追加
  （checkpointer `add_messages` 天然支持，compress 兜底膨胀）
- `fresh`：thread_id = `{task_id}_{node_id}_r{N}`，每轮全新会话

### 恢复语义

- checkpoint 新增 `loop_state: {loop_node_id, round}`——暂停/取消发生在
  体内时记录当前轮；恢复时从 (paused_node, round) 续跑该轮
- 体内 human 节点：`paused_at_node` 带 `#rN` 后缀，resume 走既有
  human_context 路径 + loop_state 续轮
- 体内 agent 节点被 cancel：`agent_thread_id` 机制不变（continue 策略下
  续接的 thread 天然含前轮历史）
- **rewind 分两档**：rewind 到 loop 外节点 = 整个循环从 r1 重跑（清全部
  轮次键）；rewind 到体节点 = 轮次粒度（后端键已支持，前端 UI M3.1 再做，
  第一期 API 层面直接可用）

### 决策：**选项 A**。

---

## 3. 数据模型

```python
# loop 节点 config（node.type == "loop"）
{
    "body": ["writer", "critic"],            # 体成员（node_id 列表，无序）
    "body_entry": "writer",                   # 体入口（显式，避免无入边启发式歧义）
    "max_iterations": 5,                      # 防呆上限 1..100，必填（默认 5）
    "converge_expr": "{{critic.verdict}} == 'approve'",  # 可选；None=跑满轮数
}
# 体成员的 config.next_nodes：内部路由照常（可含 gateway/parallel）；
# 所有体节点的下游必须仍在 body 内（封闭性，校验码见 §4）。
# loop 节点自身的 next_nodes：循环结束后的出口（可条件路由，条件里可用
# {{loop.converged}} / {{loop.iterations}}）。
```

**body 成员类型约束**（writer/critic 仅为辩论示例，非固定）：

| 类型 | 可入 body | 说明 |
|---|---|---|
| `agent` | ✅ | 主力：辩论/迭代改进（thread_policy 差异化续接/隔离） |
| `tool` / `kb_search` | ✅ | 每轮加工/检索（映射式场景） |
| `gateway` | ✅ | 体内条件路由（如按上轮结果走不同加工分支） |
| `parallel` | ✅ | 体内并行（ADR §7.3 需测试确认收敛表达式取值） |
| `human` | ✅ | 每轮人工审核（恢复语义已设计：`paused_at_node#rN` + loop_state） |
| `subflow` | ✅ | 每轮调用一次子工作流（每轮独立 Task/超时，语义自洽） |
| `loop` | ❌ | 嵌套循环（`LOOP_NESTED_NOT_SUPPORTED`，M3 禁） |
| `start` / `end` | ❌ | 结构性节点：start 全局唯一入口；end 在体内会提前终止工作流，语义混乱，禁 |

典型组合示例：辩论 `agent→agent`；迭代加工 `agent→tool→agent`；
带人审的迭代 `agent→human`；批量映射 `agent`（converge_expr=None 跑满轮数，
每轮输入由表达式从外部数据源按 `{{loop.iterations}}` 取不同项）。

**输出**（写入变量池 `loop` 键）：
`{iterations: int, converged: bool, rounds: {N: {<node_id>: <output>}}}`

---

## 4. 校验（新增错误码，同步 `docs/workflow-validator.md`）

| 码 | 级别 | 条件 |
|---|---|---|
| `LOOP_BODY_EMPTY` | ERROR | body 为空或含非 exist 节点 |
| `LOOP_ENTRY_NOT_IN_BODY` | ERROR | body_entry ∉ body |
| `LOOP_MAX_ITERATIONS_RANGE` | ERROR | max_iterations ∉ [1, 100] |
| `LOOP_BODY_NOT_CLOSED` | ERROR | 体节点的 next 指向 body 外（出口由 loop 接管，不允许旁路） |
| `LOOP_BODY_CYCLE` | ERROR | body 内部存在环（体是 DAG，循环由 loop 驱动） |
| `LOOP_NESTED_NOT_SUPPORTED` | ERROR | body 内含 loop 节点（M3 禁嵌套） |
| `LOOP_CONVERGE_REF_INVALID` | ERROR | converge_expr 引用了不存在的源 |

FORWARD_REFERENCE 对 body 成员的规则：可引用 loop 之前的上游 + 同轮体内
上游 + `loop.rounds.*`（历史）；引用 `loop.iterations/converged`（循环产物）
视为前向引用，拒。

---

## 5. 执行语义（引擎）

```
execute_node(loop):
  for round in 1..max_iterations:
      快照上一轮体输出 → loop.rounds[round-1]（不可变）
      round_start 事件（timeline：loop_round_start）
      从 body_entry 递归执行体（复用 _execute_node；
          completed 键 = node_id#r{round}；变量写裸键=最新轮）
      求值 converge_expr（resolve_bool，上下文含裸键+loop 变量）
      if converged: break
      轮间预算检查（节点边界 _check_cancelled 已天然覆盖，无额外逻辑）
  写 loop 键 {iterations, converged, rounds}
  loop_round_complete + node_complete 事件
  走 loop.next_nodes（条件边可引用 loop.converged 路由）
```

暂停/取消/预算超限在体内发生 → 沿用既有异常路径，checkpoint 携带
`loop_state`；轮次限定键保证重入安全。

**长程稳定性硬规范（不可妥协的实现要求）**：每轮完成即写 checkpoint
（更新 loop_state + 追加本轮轮次键与 rounds 快照）——轮是恢复的最小
持久单位，进程崩溃/重投递后从最后完成轮续跑，绝不从头重跑。这是对
控制流派（整跑重跑）与耐久派（deterministic replay，对 LLM 是伪需求——
重放=重花钱且结果不同）的路线回答：checkpoint + 轮粒度恢复 + rounds
审计快照，才是 LLM 工作流正确的恢复经济学。

---

## 6. 前端（M3 第一期边界）

- **LoopNodeConfig 面板**：body 成员多选（chips，同委派池交互）+
  body_entry 下拉（限成员）+ max_iterations + converge_expr
  （VariableSelector 辅助插入 `{{critic.verdict}}`）
- **画布**：body 成员加视觉标记（节点角标 🔁 + 同色描边/底色分组），**不做**
  交互容器（M3.1）；三处注册表同步（node-type-configs / node-defaults /
  node-output-variables：iterations/converged/rounds）
- **运行视图**：TaskFlowGraph 的 loop 阶段卡显示 `第 N/5 轮`；
  AgentTimeline 事件带轮次徽标
- **顺手项**：subflow 前端面板补齐（存量断层，同一套面板开发模式）

---

## 7. 开放问题（评审时定）

1. `max_iterations` 上限 20 是否合适？（辩论 3-5 轮常见；映射场景可能要更高——
   若要高上限，建议同时强制 converge_expr 或预算兜底）
2. converge_expr 求值失败（引用缺失/类型错）→ 视为未收敛继续，还是节点失败？
   （倾向：记 warning 视为未收敛，跑满上限诚实结束）
3. 体内 parallel 的 join 结果参与收敛判定的表达式形态（`{{parallel_x.…}}`
   裸键语义=最新轮，应天然可用，需测试确认）
4. 轮次徽标在 TaskFlowTimeline 的密度（20 轮 × 多事件会刷屏——考虑按轮折叠）

---

## 8. 实施清单（评审通过后）

1. validator：§4 校验码 + workflow-validator.md 文档 + 测试
2. 引擎：轮次循环执行 + 轮次键 + rounds 快照 + loop_state checkpoint + 测试
3. 恢复路径：体内 pause/cancel/预算超限的 resume 测试（含 thread_policy 两态）
4. 前端：面板 + 画布标记 + 运行视图轮次渲染 + 注册表三处同步
5. subflow 前端面板（顺手）
6. 端到端：debate 示例工作流（writer continue / critic fresh / converge 收敛）


## 2026-10 工作台退役（LoopWorkspace 移除）

多轮评审后的化繁为简结论：循环内数据流回归**纯变量引用**——
「前引后 = 取上一轮值」（变量池裸键=最新值的天然语义），跨轮记忆由
loop_thread_policy 承担，历史由 rounds 快照承担。

- 移除：LoopWorkspace（absorb 约定字段解析 / issue 状态机 / delta /
  view 注入 / workspace_goal 结构化语义）。
- 保留为极简机制：`note`（可选「循环说明」，每轮前置注入各体成员任务
  前，恒定文本；兼容旧键 workspace_goal）+ 值级 sha 空转检测（成员输出
  连续 2 轮不变 → stalled 提前结束，从变量池直接比对）。
- 语义全部归用户：输出结构（response_schema 自由）、收敛条件
  （converge_expr 自写）、数据流向（任务里 {{引用}} 自连）。
