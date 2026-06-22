# 多 Agent 对话与 Loop 节点设计

> 日期：2026-06-22
> 状态：草案

## 1. 背景与目标

### 1.1 问题

当前 Workflow 中 Agent 节点是**单轮无状态**的——每次执行创建全新 `thread_id`，不保留历史。多个 Agent 之间无法进行迭代式对话（如需求互审、代码评审、红蓝对抗等需要反复沟通直到达成共识的场景）。

### 1.2 目标

在不引入专用节点类型的前提下，通过**增强基础编排能力**，让现有的基础节点（Start / End / Agent / Tool / Gateway / Parallel）能够组合出任意多 Agent 对话模式。

### 1.3 设计原则

- **基础节点优先**：只在基础节点确实不够用时才扩展，优先扩展引擎能力而非新增节点类型
- **通用性**：改动应覆盖所有需要循环的场景，而非仅为多 Agent 对话设计专用节点
- **Agent 零改动**：多 Agent 对话的上下文管理由 Loop 节点 + 变量池负责，Agent 节点本身不修改

---

## 2. 现状分析

### 2.1 基础节点清单

| 节点类型 | 类别 | 作用 |
|---|---|---|
| `start` | 编排 | 初始化变量池，映射输入参数 |
| `end` | 编排 | 汇总输出，标记工作流完成 |
| `gateway` | 编排 | 条件分支，选择一条路径 |
| `parallel` | 编排 | 并行执行多条分支 |
| `agent` | 业务 | 调用 Agent 进行推理/行动 |
| `tool` | 业务 | 调用工具或 Skill |
| `human` | 业务 | 等待人工审批 |
| `subflow` | 业务 | 调用子工作流 |

编排节点覆盖了三种基本流程控制中的两种：**分支**（Gateway）和 **并行**（Parallel），但缺少第三种：**循环**。

### 2.2 Agent 节点上下文管理

Agent 节点的上下文管理分三层：

#### Workflow 层：变量池传递

```
VariablePool:
  "input"    → { requirement_doc: "..." }     ← Start 写入
  "agent_a"  → { response: "分析结果..." }     ← Agent_A 执行后写入
  "agent_b"  → { response: "审阅意见..." }     ← Agent_B 执行后写入
```

下游 Agent 通过 `{{ node_id.field }}` 表达式引用上游输出。变量池是只读快照，节点执行后输出写回。

#### 节点配置层：两条上下文通道

```
Agent Node Config:
  ├── input_query: "{{ agent_a.response }}\n请审阅"
  │     → 解析后成为 user message
  │
  └── input_prompt: "背景：{{ start.requirement_doc }}"
        → 解析后注入系统提示的 context 卡槽（不是 user message）
```

#### 系统提示层：结构化卡槽组装

系统提示按固定 SLOT_SCHEMA 组装：

```
SLOT_SCHEMA:
  role           (必填) → 【角色定义】
  task           (必填) → 【任务描述】
  constraints    (可选) → 【约束规则】
  context        (可选) → 【上下文信息】  ← input_prompt 覆盖
  output_format  (可选) → 【输出格式】
  tool_declaration       → 自动追加

优先级: node input_prompt > agent prompt_slots
```

#### Agent 内部层：LangGraph 执行

```
初始消息:
  SystemMessage(system_text)         ← slot_renderer 输出
  UserMessage(resolved_query)        ← input_query 解析

Agent LangGraph:
  [evaluate] → [react] → END

  evaluate: 设置 agent_id, execution_path, request_id 等
  react:    LLM + 工具循环，messages 通过 add_messages reducer 累积

输出: messages[-1].content → { response, agent_id }
```

### 2.3 关键约束

| 约束 | 说明 |
|---|---|
| 无跨执行记忆 | 每次 `thread_id = "{node_id}_{timestamp}"`，全新对话 |
| `_completed_nodes` 阻止重复执行 | 节点执行一次后标记完成，不会再次执行 |
| 变量池覆盖式存储 | `pool.set(node_id, output)` 覆盖旧值，不保留历史 |
| 只能覆盖 context 卡槽 | role/task/constraints/output_format 由 Agent 自身定义 |
| DAG 无环 | 工作流是有向无环图，不支持循环 |

---

## 3. 方案对比

### 3.1 候选方案

| 方案 | 思路 | 改动 | 通用性 |
|---|---|---|---|
| A. DAG 展开 | 把 N 轮对话硬编码展开为 N 组 Agent 节点 | 零改动 | 固定轮数，节点爆炸 |
| B. Loop 节点 | 新增 `loop` 编排节点，支持循环执行循环体 | Engine + 新节点类型 | 任意循环场景 |
| C. 引擎回边 | 修改 Engine 支持回边，任意节点可被重新执行 | Engine 改动 | 最灵活，但风险大 |
| D. Subflow + loop | 给 Subflow 加循环能力 | Subflow executor 改动 | 受限于子工作流 |
| E. 专用 debate 节点 | 为多 Agent 辩论新建节点 | 新节点类型 | 仅限辩论场景 |

### 3.2 选择：方案 B — Loop 节点

理由：
- 与 Gateway（分支）、Parallel（并行）同级的**编排型基础节点**，设计哲学一致
- 改动集中，不侵入 Engine 核心执行逻辑
- Agent / Tool 等业务节点零改动
- 覆盖所有需要循环的场景

---

## 4. Loop 节点设计

### 4.1 定位

```
编排型基础节点:
  Gateway  → 选一条路走（条件分支）
  Parallel → 多条路同时走（并行分叉）
  Loop     → 一段路反复走（循环）
```

Loop 节点自身不执行业务逻辑，只负责：
1. 将执行引入循环体入口
2. 每轮结束后判断退出条件
3. 管理循环状态（轮次、共享变量）

### 4.2 节点配置

```json
{
  "node_id": "review_loop",
  "type": "loop",
  "config": {
    "body_entry": "agent_a",
    "max_iterations": 10,
    "condition": "{{ review_loop.consensus }} == true",
    "shared_variables": {
      "conversation": {
        "type": "list",
        "append_from": ["agent_a", "agent_b", "merge"]
      }
    }
  }
}
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `body_entry` | string | 是 | 循环体第一个节点的 ID |
| `max_iterations` | number | 否 | 最大循环次数，默认 10 |
| `condition` | string | 否 | 退出条件表达式，每轮末尾求值。为空则始终循环到 max_iterations |
| `shared_variables` | object | 否 | 循环期间累积的共享变量定义 |
| `shared_variables.*.type` | string | 是 | 变量类型，当前支持 `"list"` |
| `shared_variables.*.append_from` | string[] | 是 | 每轮结束后，从这些节点的输出中累积 |

### 4.3 工作流拓扑

```
[Start] → [Loop Node] ──→ [Agent_A] → [Agent_B] → [Merge] ──→ [End]
                ↑                                              │
                └──────────── 条件不满足，继续循环 ──────────────┘
```

循环体边界：从 `body_entry` 出发，沿 next_nodes/edges 遍历，直到回到 Loop 节点。

### 4.4 前端节点类型配置

在 `NODE_TYPE_CONFIGS` 中新增：

```typescript
loop: {
  label: '循环',
  color: '#EC4899',
  bg: '#FCE7F3',
  icon: React.createElement(RetweetOutlined),  // @ant-design/icons
  description: '重复执行循环体，直到满足退出条件',
}
```

---

## 5. 对话历史管理

### 5.1 核心问题

当前变量池 `pool.set(node_id, output)` 是覆盖式的。当 Loop 中节点重新执行时，旧输出被覆盖，对话历史丢失。

### 5.2 解决方案：双轨存储

Loop 节点维护两种存储模式并存：

| 存储模式 | 示例 | 行为 | 用途 |
|---|---|---|---|
| 覆盖式 | `agent_a.response` | 每轮覆盖，保留最新值 | 快速引用最新输出 |
| 累积式 | `review_loop.conversation` | 每轮追加，保留全部历史 | 完整对话上下文 |

### 5.3 变量池中的数据结构

```json
{
  "start": { "requirement_doc": "原始需求文档..." },

  "agent_a": { "response": "第2轮A的新输出（覆盖式）" },
  "agent_b": { "response": "第2轮B的新输出（覆盖式）" },
  "merge":   { "response": "CONSENSUS: true（覆盖式）" },

  "review_loop": {
    "iteration": 2,
    "consensus": true,
    "conversation": [
      { "role": "功能分析师", "content": "第1轮分析...", "round": 1 },
      { "role": "安全审查员", "content": "第1轮审阅...", "round": 1 },
      { "role": "仲裁员",     "content": "CONSENSUS: false...", "round": 1 },
      { "role": "功能分析师", "content": "第2轮调整...", "round": 2 },
      { "role": "安全审查员", "content": "第2轮确认...", "round": 2 },
      { "role": "仲裁员",     "content": "CONSENSUS: true\n最终报告...", "round": 2 }
    ]
  }
}
```

### 5.4 累积逻辑

Loop 节点每轮执行结束后：

```python
# 伪代码
for var_name, var_def in shared_variables.items():
    if var_def["type"] == "list":
        conversation = loop_state.setdefault(var_name, [])
        for node_id in var_def["append_from"]:
            if node_id in just_executed_nodes:
                node_output = pool.get(node_id)
                conversation.append({
                    "role": get_role_label(node_id),
                    "content": node_output.get("response", ""),
                    "round": current_iteration,
                })
```

### 5.5 Agent 引用对话历史

Agent 节点通过 `{{ }}` 表达式引用对话历史，无需任何配置改动：

```json
{
  "node_id": "agent_b",
  "type": "agent",
  "config": {
    "agent_id": "agent_security_reviewer",
    "input_query": "需求文档：\n{{ start.requirement_doc }}\n\n对话历史：\n{{ review_loop.conversation }}\n\n请继续审阅。"
  }
}
```

`ExpressionEngine` 解析列表类型时自动格式化：

```
对话历史：
[Round 1] 功能分析师: 权限模型不清晰，建议拆分为...
[Round 1] 安全审查员: 认证流程缺失，需要 OAuth2...
[Round 1] 仲裁员: CONSENSUS: false — 存在2个分歧点
[Round 2] 功能分析师: 接受审计日志需求，但权限模型建议...
```

---

## 6. Engine 改动

### 6.1 `_execute_node` 新增 Loop 处理

在现有 Gateway / Parallel 分支后增加：

```python
# engine.py — _execute_node
if node_type == "loop":
    body_entry = node_config["body_entry"]
    max_iter = node_config.get("max_iterations", 10)
    condition = node_config.get("condition", "")
    shared_vars_config = node_config.get("shared_variables", {})

    loop_state = {}  # 循环内部状态

    for iteration in range(1, max_iter + 1):
        loop_state["iteration"] = iteration

        # 1. 清除循环体的完成标记
        body_nodes = self._collect_body_nodes(node_id)
        self._completed_nodes -= body_nodes

        # 2. 执行循环体
        await self._execute_node(body_entry)

        # 3. 累积共享变量
        self._accumulate_shared_variables(
            loop_state, shared_vars_config, body_nodes
        )

        # 4. 写回变量池
        self._pool.set(node_id, loop_state)

        # 5. 求值退出条件
        if condition:
            variables = self._pool.get_all()
            expr_engine = ExpressionEngine(variables)
            if expr_engine.resolve_bool(condition):
                break

    return result  # 继续执行 next_nodes
```

### 6.2 辅助方法

```python
def _collect_body_nodes(self, loop_node_id: str) -> set[str]:
    """从 body_entry 出发，BFS 收集循环体内所有节点。"""
    body_entry = self._node_map[loop_node_id]["config"]["body_entry"]
    body_nodes = set()
    queue = [body_entry]
    while queue:
        nid = queue.pop(0)
        if nid == loop_node_id or nid in body_nodes:
            continue
        body_nodes.add(nid)
        for target in self._get_downstream(nid):
            queue.append(target)
    return body_nodes

def _accumulate_shared_variables(
    self, loop_state, config, body_nodes
):
    """将指定节点输出追加到共享变量列表。"""
    for var_name, var_def in config.items():
        if var_def.get("type") != "list":
            continue
        conversation = loop_state.setdefault(var_name, [])
        for nid in var_def.get("append_from", []):
            if nid in body_nodes and nid in self._completed_nodes:
                output = self._pool.get(nid)
                if output and output.get("response"):
                    conversation.append({
                        "role": self._get_role_label(nid),
                        "content": output["response"],
                        "round": loop_state.get("iteration", 0),
                    })
```

### 6.3 ExpressionEngine 列表格式化

当 `{{ }}` 引用的值为 list 类型时，自动格式化为可读文本：

```python
# expression.py — ExpressionEngine.resolve
def _format_value(self, value: Any) -> str:
    if isinstance(value, list):
        # 对话历史格式: [{role, content, round}, ...]
        lines = []
        for item in value:
            if isinstance(item, dict) and "role" in item:
                round_num = item.get("round", "?")
                lines.append(f"[Round {round_num}] {item['role']}: {item['content']}")
            else:
                lines.append(str(item))
        return "\n".join(lines)
    return str(value)
```

### 6.4 VariablePool 扩展

增加 `append` 方法（如果 Loop 节点直接操作 pool）：

```python
def append(self, path: str, item: Any) -> None:
    """Append an item to a list variable at the given path."""
    parts = path.split(".", 1)
    if len(parts) == 1:
        lst = self._store.setdefault(parts[0], [])
        if isinstance(lst, list):
            lst.append(item)
    else:
        parent = self._store.get(parts[0])
        if isinstance(parent, dict):
            lst = parent.setdefault(parts[1], [])
            if isinstance(lst, list):
                lst.append(item)
```

---

## 7. 完整示例：需求互审工作流

### 7.1 工作流 JSON

```json
{
  "name": "需求互审",
  "nodes": [
    {
      "node_id": "start",
      "type": "start",
      "config": {
        "output_variables": [
          {
            "name": "requirement_doc",
            "type": "text",
            "constraints": { "required": true }
          }
        ]
      }
    },
    {
      "node_id": "review_loop",
      "type": "loop",
      "config": {
        "body_entry": "agent_a",
        "max_iterations": 10,
        "condition": "{{ review_loop.consensus }} == true",
        "shared_variables": {
          "conversation": {
            "type": "list",
            "append_from": ["agent_a", "agent_b", "merge"]
          }
        }
      }
    },
    {
      "node_id": "agent_a",
      "type": "agent",
      "config": {
        "agent_id": "agent_functional_analyst",
        "input_query": "请分析以下需求文档：\n{{ start.requirement_doc }}\n\n{% if review_loop.conversation %}之前的讨论历史：\n{{ review_loop.conversation }}{% endif %}\n\n请给出你的分析，指出问题并提出建议。"
      }
    },
    {
      "node_id": "agent_b",
      "type": "agent",
      "config": {
        "agent_id": "agent_security_reviewer",
        "input_query": "需求文档：\n{{ start.requirement_doc }}\n\n对话历史：\n{{ review_loop.conversation }}\n\n请从安全角度审阅以上讨论，指出遗漏或问题。"
      }
    },
    {
      "node_id": "merge",
      "type": "agent",
      "config": {
        "agent_id": "agent_moderator",
        "input_query": "功能分析：{{ agent_a.response }}\n安全审阅：{{ agent_b.response }}\n\n请判断双方是否已达成共识。\n输出格式：\nCONSENSUS: true/false\nREPORT: 共识报告或分歧点列表",
        "output_field_mapping": {
          "consensus": "CONSENSUS: true"
        }
      }
    },
    {
      "node_id": "end",
      "type": "end",
      "config": {
        "output_mapping": {
          "final_report": "{{ review_loop.conversation }}",
          "total_rounds": "{{ review_loop.iteration }}"
        }
      }
    }
  ],
  "edges": [
    { "source": "start",        "target": "review_loop" },
    { "source": "review_loop",  "target": "agent_a" },
    { "source": "agent_a",      "target": "agent_b" },
    { "source": "agent_b",      "target": "merge" },
    { "source": "merge",        "target": "review_loop" },
    { "source": "review_loop",  "target": "end" }
  ]
}
```

### 7.2 执行流程

```
═══ 进入 Loop (iteration=1) ═══
  review_loop.conversation = []

  agent_a → "功能分析：1.权限模型不清晰 2.缺少审计日志"
  agent_b → "安全审阅：认证流程缺失，建议OAuth2"
  merge   → "CONSENSUS: false\n分歧：权限拆分方式"

  累积: conversation = [3条], iteration=1
  条件: consensus == true → false → 继续

═══ iteration=2 ═══
  清除 agent_a/agent_b/merge 完成标记

  agent_a → "看到反馈，我调整权限模型为RBAC+ABAC混合..."
  agent_b → "接受混合方案，但ABAC部分需要..."
  merge   → "CONSENSUS: true\n最终报告：双方达成一致..."

  累积: conversation = [6条], iteration=2
  条件: consensus == true → true → 退出

═══ End ═══
  输出 final_report (完整6条对话历史)
  输出 total_rounds = 2
```

---

## 8. 不同场景的配置对比

全部使用基础节点，只改 JSON 配置：

```yaml
# 需求互审
Loop → [Agent_A(功能)] → [Agent_B(安全)] → [Agent_M(仲裁)] → back to Loop
condition: "{{ review_loop.consensus }} == true"

# 代码评审
Loop → [Agent(开发者修改)] → [Agent(Reviewer审查)] → back to Loop
condition: "{{ reviewer.approved }} == true"

# 翻译校对
Loop → [Agent(翻译)] → [Agent(校对)] → back to Loop
condition: "{{ proofread.issues_count }} == 0"

# 红蓝对抗（固定轮次）
Loop → [Agent(攻方)] → [Agent(防方)] → back to Loop
condition: "{{ _loop.iteration }} >= 5"

# 辩论赛
Loop → [Agent(正方)] → [Agent(反方)] → [Agent(裁判)] → back to Loop
condition: "{{ judge.decided }} == true"
```

---

## 9. 改动清单

### 9.1 后端

| 文件 | 改动 | 说明 |
|---|---|---|
| `node_executor.py` | 新增 `LoopNodeExecutor` | 循环执行逻辑 |
| `node_executor.py` | `_NODE_EXECUTOR_MAP` 注册 `"loop"` | 工厂注册 |
| `engine.py` | `_execute_node` 增加 loop 分支 | 循环调度 |
| `engine.py` | 新增 `_collect_body_nodes` | 收集循环体节点 |
| `variable_pool.py` | 新增 `append` 方法 | 列表变量追加 |
| `expression.py` | `_format_value` 处理 list 类型 | 对话历史格式化 |

### 9.2 前端

| 文件 | 改动 | 说明 |
|---|---|---|
| `node-type-configs.ts` | 新增 `loop` 配置 | 图标、颜色、描述 |
| `WorkflowCanvas.tsx` | 注册 loop 节点渲染 | 与 gateway/parallel 同级 |
| Loop 配置面板 | 新增 | body_entry、max_iterations、condition、shared_variables 配置 |
| `VariableSelector.tsx` | 支持引用 `loop_node.conversation` | 列表类型变量选择 |

### 9.3 测试

| 范围 | 说明 |
|---|---|
| `LoopNodeExecutor` 单元测试 | 循环执行、退出条件、共享变量累积 |
| `VariablePool.append` 测试 | 列表追加、路径解析 |
| `ExpressionEngine` 列表格式化测试 | 对话历史格式化输出 |
| Engine 集成测试 | 循环执行、完成标记清除、变量池状态 |
| 前端组件测试 | Loop 节点渲染、配置面板 |

---

## 10. 边界情况与防护

| 场景 | 处理方式 |
|---|---|
| 循环体为空 | 配置校验拦截，`body_entry` 必填且必须指向有效节点 |
| 无限循环 | `max_iterations` 硬上限，默认 10 |
| 循环体内有 Parallel 节点 | 正常支持，Parallel 在循环体内独立执行 |
| 循环体内有 Human 节点 | 支持，Human 暂停机制在循环内正常工作 |
| 循环体内有 Gateway 节点 | 支持，Gateway 条件分支在循环内正常工作 |
| `append_from` 中的节点未执行 | 跳过，不追加 |
| 对话历史过长 | 可在 Agent 的 `input_query` 中用表达式截断，或配置只保留最近 N 条 |
| 嵌套 Loop | 第一阶段不支持，后续可扩展 |

---

## 11. 未来扩展

- **嵌套循环**：Loop 内包含另一个 Loop，需要独立的循环状态栈
- **条件性追加**：`append_from` 支持条件过滤，只追加满足条件的输出
- **对话历史窗口**：`shared_variables` 增加 `window_size` 配置，只保留最近 N 条
- **循环体变量隔离**：`scope: "isolated"` 模式，循环体内变量不泄漏到外层
- **流式输出**：循环执行过程中实时推送每轮对话进展
