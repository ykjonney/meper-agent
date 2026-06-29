---
title: 'agent-flow-harness 包重构'
type: 'refactor'
created: '2026-06-23'
status: 'approved'
baseline_commit: 'v0.0-baseline'
context:
  - docs/planning-artifacts/architecture.md
  - docs/planning-artifacts/epics.md
  - docs/planning-artifacts/prds/prd-agent-flow-2026-06-05/prd.md
---

# agent-flow-harness — 单一 PyPI 包的目录骨架

> **本文件是「包布局与导入路径」设计稿。** 详细动机、行为契约、API 参数等见 [`docs/harness/architecture.md`](./docs/harness/architecture.md)、[`docs/harness/api.md`](./docs/harness/api.md) 等。
>
> **当前状态**：v0.1 仅锁定 **核心 6 模块**（react 节点 + 护栏 + 中间件 + 适配器 + 工具 + Slot）。**§13 列出的 9 个增强模块**仅做目录占位，详细设计待后续 Story 收敛。

agent-flow-harness 是一个**通过 Git 直接依赖**安装的 Python 3.12+ 库，封装：

**核心 6 模块**（v0.1 锁定）：
- LangGraph `react` 节点的**单一执行器**（评估/直答/计划-执行-验证 全部下线）
- 围绕该执行器的**护栏/资源控制**（token 计费预算、调用频率、内容安全 —— 全部以 **LangGraph Node** 形式接入 StateGraph）
- `astream_events` → **应用层事件 schema** 的 Adapter（前端零改动）
- `Slot` 化的 system prompt 渲染（`role → task → constraints → context → output_format → tool_declaration`）
- **Session 留在应用层**；harness 只通过 `thread_id` 字符串与 Session 交互
- **Tool Registry + Community 工具**（统一工具接入协议）

**增强模块**（v0.2+ 占位，参考 DeerFlow 完整 harness）：
- sub-agent 委派 / Sandbox 抽象 / ACP 协议 / 多 Provider LLM（含 CLI/vLLM）
- Context Engineering 框架化 / Skills 目录式 / Lead-Sub Agent 嵌套 / 配置热重载
- IM 渠道（Telegram / Slack / 飞书 / 微信 / 企业微信 / 钉钉）

---

## Intent

### Problem

当前 `backend/app/engine/` 耦合了应用层基础设施（fastapi/motor/celery/redis），导致：
- 无法独立复用和测试执行引擎
- 难以接入新的执行场景（CLI/IM/API）
- 工具/护栏/中间件逻辑分散，缺乏统一抽象

### Approach

将 engine 层抽离为独立 `agent-flow-harness` Python 包，通过 Git 直接依赖安装。

**v0.1 锁定核心 6 模块：**
1. `engine/` — 单一 react 节点执行器
2. `guards/` — 4 类护栏（Token/Time/ToolRateLimit/Content）
3. `middleware/` — 中间件协议与链
4. `adapters/` — astream_events → 应用层事件适配器
5. `tools/` — ToolRegistry + 内置工具 + CommunityTool 协议
6. `slots/` — 6 段式 prompt 渲染

**v0.2+ 扩展增强模块：**
- subagents/ — sub-agent 委派
- sandbox/ — 沙箱抽象（Local/Docker/K8s）
- acp/ — ACP 协议（Codex/Claude Code CLI）
- providers/ — 多 Provider LLM（含 CLI/vLLM）
- context_engineering/ — Context 策略框架
- skills_fs/ — 目录式 Skills 热加载
- agent_hierarchy/ — Lead-Sub Agent 嵌套
- config_reload/ — 配置热重载
- channels/ — IM 渠道

---

## Boundaries & Constraints

### Always（必须遵守）

- harness **不可依赖** fastapi/uvicorn/starlette/motor/pymongo/celery/redis
- harness **仅允许依赖** langgraph>=1.0.8/langchain-core/pydantic>=2.0/structlog/typing-extensions
- 应用层通过 Git 直接依赖安装（`uv add git+https://.../agent-flow-harness.git@main`）
- Session/User/RBAC/MongoDB 客户端构造留在应用层
- 公开 API 一律走 `agent_flow_harness.xxx`，`__init__.py` 只做 re-export
- **工具哲学（三层工具模型）**：harness 提供前两层，第三层由宿主注入。调研 deer-flow 后确立（2026-06-25）：
  - **第一层 — 能力型内建工具**（harness 自带，非领域）：任何 agent 产品都需要、与具体业务无关的"交互/协作能力"。如 `delegate_to_subagent`（委派，已实现 v0.2-1）、`present_file`（展示结果）、`ask_clarification`（追问用户）、`tool_search`（工具延迟检索）。
  - **第二层 — 文件/shell 能力 + 环境抽象**（harness 提供抽象与工具，实现可插拔）：`Sandbox`（ABC）+ `SandboxProvider`（ABC）定义执行环境协议；`bash`/`read`/`write`/`glob`/`grep` 工具委托 Sandbox 方法（工具代码零 I/O）。`LocalSandbox` 是 harness 默认实现；具体实现（Docker/E2B/远程）通过 `config.use` 字符串注入。**这是"环境抽象"，不是领域工具。**
  - **第三层 — 用户/应用领域工具**（harness 不持有）：查 MES / 发邮件 / 业务 API / MCP / Skill 工具等，通过 `ToolRegistry` + `use` 字符串注入。
  - **核心约束**：第一、二层必须通过抽象/注入，不绑定任何具体实现。bash 委托 `Sandbox.execute_command()`，Sandbox 是 ABC，Local/Docker/E2B 都实现它——harness 提供能力，具体执行由宿主决定。

### Ask First（变更前需确认）

- 变更 ToolRegistry 的单例模式
- 修改 Guard vs Middleware 的边界定义
- 新增核心模块（影响公开 API）
- 修改应用层事件 schema（影响前端）

### Never（绝不）

- 在 harness 内实现 Web/REST 路由
- 在 harness 内实现 Agent 文档的 MongoDB 读写
- 在 harness 内实现 User/Role/RBAC
- 在 harness 内实现 Session 模型（只通过 thread_id 字符串交互）
- 在 harness 内直接依赖 Anthropic/OpenAI Provider 类（用 langchain_* 库替代）

---

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| 单 react 节点执行 | agent_doc + input_state | output_state with messages | depth_limit_exceeded → state["error"] |
| Guard block | guard check_in/check_out fails | state["error"] = reason, 短路返回 | 推 error 事件到前端 |
| Guard warn | guard check returns Warn | state["warnings"].append(reason), 继续执行 | 记录日志 |
| Middleware 改写 | before_llm/after_llm hook | modified state/response | 异常捕获，记录日志，不阻断 |
| 流式输出 | run_agent_streaming | 7 种应用层事件 SSE | on_error 推 error 事件 |
| 工具执行失败 | tool raises exception | ToolMessage(content="Error: ...") | 继续循环，让 LLM 看到错误 |
| Context 压缩 | messages 超 context_window 70% | compress_messages 保留最近 10 条 | 压缩失败走 fallback（截断） |
| Token 超限 | TokenBudgetGuard 累计超阈值 | Block(reason="token budget exceeded") | 短路返回，推 error 事件 |
| 循环检测 | 同一 tool 同一 args 调用 3 次 | Block(reason="circular tool call detected") | 短路返回 |

---

## Code Map

### 核心目录结构

```text
packages/harness/
├── pyproject.toml             # uv-build; name=agent-flow-harness; Python>=3.12
├── README.md
├── LICENSE
├── uv.lock                    # 必须提交
├── src/
│   └── agent_flow_harness/
│       ├── __init__.py        # 公开 API 聚合（只 re-export）
│       ├── py.typed
│       ├── engine/            # 核心: 单一 react 节点
│       │   ├── __init__.py
│       │   ├── react.py       # react_node(state, config) -> dict
│       │   ├── context.py     # compress_messages / should_compress / extract_model_name
│       │   ├── depth_guard.py # check_depth(state) -> DepthResult
│       │   └── prompts/
│       │       ├── __init__.py
│       │       ├── react.py   # REACT 系统 prompt 模板
│       │       └── slots.py   # SlotSchema 定义
│       ├── graph/             # 核心: StateGraph 构造 + runner
│       │   ├── __init__.py
│       │   ├── builder.py     # build_agent_graph(agent_doc, ...) -> CompiledStateGraph
│       │   ├── runner.py      # run_agent / run_agent_streaming
│       │   └── nodes/
│       │       ├── __init__.py
│       │       ├── react.py   # _make_react_node(agent_doc, ctx) -> Callable
│       │       └── guard_nodes.py  # make_guard_in_node / make_guard_out_node
│       ├── adapters/          # 核心: astream_events → 7 种应用层事件
│       │   ├── __init__.py
│       │   ├── stream_events.py    # stream_events_to_app_events
│       │   ├── app_event.py        # 7 种事件 Pydantic schema
│       │   └── content_blocks.py   # AIMessage -> UI blocks
│       ├── guards/            # 核心: 4 类 Guard (Node 形式)
│       │   ├── __init__.py
│       │   ├── base.py        # Guard Protocol + GuardResult
│       │   ├── token_budget.py
│       │   ├── time_budget.py
│       │   ├── tool_rate_limit.py
│       │   ├── content.py
│       │   └── nodes.py       # guard -> LangGraph Node 适配器
│       ├── tools/             # 核心: ToolRegistry + builtin/community
│       │   ├── __init__.py
│       │   ├── registry.py    # ToolRegistry (单例)
│       │   ├── builtin.py     # bash / read / write / write_to_output
│       │   ├── community.py   # CommunityTool 协议
│       │   ├── mcp.py         # MCP 工具适配
│       │   ├── skill.py       # Skill 工具适配
│       │   └── task.py        # 任务管理工具
│       ├── slots/             # 核心: 6 段式 prompt 渲染
│       │   ├── __init__.py
│       │   ├── schema.py      # SlotSchema 定义
│       │   ├── renderer.py    # render_system_prompt
│       │   └── expression.py  # Jinja2 表达式引擎
│       ├── llm/               # 核心: get_llm_client 工厂
│       │   ├── __init__.py
│       │   ├── factory.py     # get_llm_client(agent, *, enable_thinking)
│       │   ├── providers/
│       │   │   ├── __init__.py
│       │   │   └── openai_compat.py  # OpenAI 兼容 (含 Anthropic)
│       │   └── thinking.py    # thinking mode 适配
│       ├── middleware/        # 核心: Middleware 协议 + chain
│       │   ├── __init__.py
│       │   ├── base.py        # Middleware Protocol
│       │   ├── chain.py       # MiddlewareChain 执行器
│       │   └── builtin/
│       │       ├── __init__.py
│       │       ├── audit.py
│       │       ├── prompt_injection.py
│       │       └── trace.py
│       ├── state.py           # 核心: AgentState TypedDict
│       └── checkpointer.py    # 核心: get_checkpointer() -> BaseCheckpointSaver
├── tests/                     # 与 src/ 镜像
│   ├── conftest.py
│   ├── engine/
│   ├── graph/
│   ├── adapters/
│   ├── guards/
│   ├── tools/
│   ├── slots/
│   ├── middleware/
│   └── integration/
└── docs/
    ├── architecture.md
    ├── api.md
    ├── session-integration.md
    └── migration-from-app-engine.md
```

### 关键文件

- `packages/harness/src/agent_flow_harness/__init__.py` — 公开 API 聚合
- `packages/harness/src/agent_flow_harness/state.py` — AgentState TypedDict
- `packages/harness/src/agent_flow_harness/checkpointer.py` — MongoDBSaver 注入
- `packages/harness/src/agent_flow_harness/engine/react.py` — 单一 react 节点
- `packages/harness/src/agent_flow_harness/graph/builder.py` — StateGraph 构造
- `packages/harness/src/agent_flow_harness/graph/runner.py` — run_agent / run_agent_streaming
- `packages/harness/src/agent_flow_harness/adapters/stream_events.py` — 事件适配器
- `packages/harness/src/agent_flow_harness/guards/base.py` — Guard Protocol
- `packages/harness/src/agent_flow_harness/tools/registry.py` — ToolRegistry
- `packages/harness/src/agent_flow_harness/llm/factory.py` — get_llm_client
- `packages/harness/src/agent_flow_harness/middleware/base.py` — Middleware Protocol
- `packages/harness/src/agent_flow_harness/slots/renderer.py` — render_system_prompt

---

## Tasks & Acceptance

### Phase 1: Package Skeleton (v0.1-1)

**目标：** 创建 `packages/harness/` 目录结构，建立 src 布局与公开 API 骨架

**关键交付：**
- [ ] `packages/harness/pyproject.toml` — 声明 name/version/dependencies/wheel 配置
- [ ] `packages/harness/src/agent_flow_harness/` — 6 个核心模块空壳（含 `__init__.py`）
- [ ] `state.py` — AgentState TypedDict（与现状字段一致）
- [ ] `checkpointer.py` — get_checkpointer() 函数签名（依赖注入）
- [ ] `graph/builder.py` — build_agent_graph() 最小实现（react -> END）
- [ ] 10 个测试覆盖导入路径、build_agent_graph 返回值、checkpointer 注入

**验收标准：**
- AC1: 仓库根目录新增 `packages/harness/` 目录，使用 `src/` 布局
- AC2: pyproject.toml 声明依赖 langgraph>=1.0.8/langchain-core/pydantic>=2.0/structlog
- AC3: pyproject.toml **不可**依赖 fastapi/motor/celery/redis
- AC4: `__init__.py` 只做 re-export
- AC5: 6 个核心模块空壳存在（engine/graph/adapters/guards/tools/slots/llm/middleware）
- AC6: state.py + checkpointer.py 函数签名存在
- AC7: build_agent_graph 返回 react -> END 单节点图
- AC8: 应用层通过 Git 依赖引用 harness
- AC9: 10 个测试通过

**Story 文件：** `docs/implementation-artifacts/v0-1-1-harness-package-skeleton.md`

---

### Phase 2: React Node (v0.1-2)

**目标：** 把现有 react_executor.run + run_streaming 合并为单一 react_node LangGraph Node

**关键交付：**
- [ ] 提取 `context.py`（compress_messages / should_compress / extract_model_name）
- [ ] 提取 `depth_guard.py`（check_depth）
- [ ] 实现 `react_node(state, config) -> dict` LangGraph Node
- [ ] 删除 evaluator/direct_executor/planner_executor 三个未使用文件
- [ ] 更新 build_agent_graph 移除 evaluator 节点
- [ ] 15+ 单元测试覆盖 REACT 循环各分支

**验收标准：**
- AC1: react_node 实现完整 REACT 循环（bind_tools → LLM call → tool_calls → 循环）
- AC2: 最大 25 轮迭代（与现状一致）
- AC3: 工具执行前设置 workspace context，执行后清理
- AC4: 每次 LLM 调用前调用 check_depth，超限短路返回
- AC5: Context 压缩：超阈值时 compress_messages（保留原 70% 阈值 / 4K 预留 / 10 条尾巴）
- AC6: 工具执行结果回填到 state["messages"]，step_count 每次 LLM 调用 +1
- AC7-AC9: 删除 evaluator/direct_executor/planner_executor
- AC10-AC11: 提取 context/depth_guard 到 harness
- AC12: 保留 streaming 事件 schema（由 v0.1-3 Adapter 通过 astream_events 触发）
- AC13: 15+ 单元测试通过

**Story 文件：** `docs/implementation-artifacts/v0-1-2-single-react-node-and-merge.md`

---

### Phase 3: Adapters (v0.1-3)

**目标：** 实现 stream_events_to_app_events Adapter，把 astream_events 原生事件转换为 7 种应用层事件

**关键交付：**
- [ ] 定义 7 种应用层事件 Pydantic schema（app_event.py）
- [ ] 实现 stream_events_to_app_events 异步函数
- [ ] 实现 _StreamingAccumulator 类（text/thinking/tool_call chunks 累积）
- [ ] 处理 on_chat_model_stream / on_chat_model_end / on_tool_start / on_tool_end
- [ ] 实现中间文本持久（AIMessage 同时含 content + tool_calls 时推 final_answer）
- [ ] 实现 enable_thinking 开关
- [ ] 20+ 单元测试 + 1 个端到端集成测试

**验收标准：**
- AC1: stream_events_to_app_events 函数签名正确
- AC2: 7 种事件类型全部定义（thinking_delta/thinking/final_answer_delta/final_answer/tool_call_start/tool_call/tool_result）
- AC3: LangGraph 原生事件 → 应用层事件映射规则正确
- AC4: 两个并行累积（streaming_text_parts / streaming_thinking_parts）
- AC5: 中间文本持久化逻辑保留
- AC6: tool_call_chunks 跨多个 chunk 累积成完整 tool_call
- AC7: on_tool_start 推 tool_call_start 占位事件
- AC8-AC9: enable_thinking 开关控制 thinking_delta/thinking 事件
- AC10: on_llm_error / on_tool_error 推 error 事件
- AC11: 20+ 单元测试通过
- AC12: 1 个端到端集成测试与现状输出逐事件对比一致

**Story 文件：** `docs/implementation-artifacts/v0-1-3-astream-events-adapter.md`

---

### Phase 4: Guards (v0.1-4)

**目标：** 实现 4 类内置 Guard 作为 LangGraph Node，通过 build_agent_graph(agent_doc, guards=[...]) 自动插入拓扑

**关键交付：**
- [ ] 定义 Guard Protocol + GuardResult 判别联合（Allow/Block/Warn）
- [ ] 实现 4 类 Guard（TokenBudget/TimeBudget/ToolRateLimit/Content）
- [ ] 实现 make_guard_in_node / make_guard_out_node 节点工厂
- [ ] build_agent_graph 接收 guards: list[Guard] | None 参数
- [ ] 解析 agent_doc["guards"] 配置 → 实例化 Guard
- [ ] 20+ 单元测试 + 1 个集成测试

**验收标准：**
- AC1: Guard Protocol + GuardResult 定义正确
- AC2: 4 类 Guard 全部实现
- AC3: 4 类 Guard 支持 check_in / check_out 异步方法
- AC4: make_guard_in_node / make_guard_out_node 工厂函数存在
- AC5: build_agent_graph 拓扑扩展：guards=None → react -> END；guards=[...] → [guard_in?] -> react -> [guard_out?] -> END
- AC6: agent_doc["guards"] 配置字段声明启用列表
- AC7: build_agent_graph 按 name 字段实例化 Guard（注册表机制）
- AC8: Block 结果时短路返回，state["error"] = reason
- AC9: Warn 结果时记录到 state["warnings"] 但不阻断
- AC10: 4 类 Guard 通过 __all__ 导出，应用层可继承扩展
- AC11-AC12: 20+ 单元测试 + 1 个集成测试通过

**Story 文件：** `docs/implementation-artifacts/v0-1-4-four-guards-as-nodes.md`

---

### Phase 5: Middleware (v0.1-5)

**目标：** 实现 Middleware Protocol + MiddlewareChain，在 react_node 内部环绕 LLM/Tool 调用

**关键交付：**
- [ ] 定义 Middleware Protocol（before_llm/after_llm/before_tool/after_tool）
- [ ] 实现 MiddlewareChain 执行器（按 order 排序、统一异常处理）
- [ ] 实现 3 个内置中间件（audit/prompt_injection/trace）
- [ ] build_agent_graph 接收 middleware: MiddlewareChain | None 参数
- [ ] react_node 内部通过 MiddlewareChain 环绕调用
- [ ] 15+ 单元测试

**验收标准：**
- AC1: Middleware Protocol 定义正确（name/order/before_llm/after_llm/before_tool/after_tool）
- AC2: MiddlewareChain 按 order 升序执行
- AC3: MiddlewareChain 统一异常处理（中间件抛异常不阻断流程）
- AC4: 3 个内置中间件实现（audit/prompt_injection/trace）
- AC5: build_agent_graph 接收 middleware 参数
- AC6: react_node 内部通过 chain.before_llm / chain.after_llm 环绕 LLM 调用
- AC7: react_node 内部通过 chain.before_tool / chain.after_tool 环绕 Tool 调用
- AC8: agent_doc["middleware"] 配置字段声明启用列表
- AC9: Middleware 不阻断流程（与 Guard 分工明确）
- AC10: 15+ 单元测试通过

**Story 文件：** `docs/implementation-artifacts/v0-1-5-middleware-chain.md`

---

### Phase 6: Slots (v0.1-6)

**目标：** 把 slot_renderer 迁移到 harness，保持 6 段式 system prompt 渲染

**关键交付：**
- [ ] 定义 SlotSchema（6 段式：role/task/constraints/context/output_format/tool_declaration）
- [ ] 实现 render_system_prompt(agent_doc, *, overrides, variable_pool, strict=True)
- [ ] 提取 expression.py（Jinja2 表达式引擎）
- [ ] 与现状 slot_renderer.render_system_prompt_full 输出对比测试
- [ ] 10+ 单元测试

**验收标准：**
- AC1: SlotSchema 定义 6 段式（role/task/constraints/context/output_format/tool_declaration）
- AC2: render_system_prompt 函数签名与现状完全一致
- AC3: tool_declaration slot 自动注入（从 ToolRegistry.resolve 获取）
- AC4: expression.py 提取 Jinja2 表达式引擎
- AC5: 与现状输出逐字符对比一致（前端零改动）
- AC6: 10+ 单元测试通过

**Story 文件：** `docs/implementation-artifacts/v0-1-6-slot-renderer-and-schema.md`

---

### Phase 7: ToolRegistry (v0.1-7) 🔴 当前缺失

**目标：** 实现 ToolRegistry 统一工具接入协议 + 4 个内置工具

**关键交付：**
- [ ] 实现 ToolRegistry 类（register / resolve / list_community_tools）
- [ ] 实现 4 个内置工具（bash/read/write/write_to_output）
- [ ] 定义 CommunityTool 协议
- [ ] 从 backend/app/engine/tools/ 迁移内置工具代码
- [ ] engine/react.py 改为通过 ToolRegistry.resolve(agent_doc) 获取工具
- [ ] 15+ 单元测试

**验收标准：**
- AC1: ToolRegistry 类实现（register/resolve/list_community_tools）
- AC2: 4 个内置工具实现（bash/read/write/write_to_output）
- AC3: CommunityTool Protocol 定义（name/description/config_schema/build）
- AC4: 从 backend/app/engine/tools/ 迁移代码到 harness
- AC5: engine/react.py 改为 registry.resolve(agent_doc)
- AC6: agent_doc["tools"] 配置字段解析正确
- AC7: 15+ 单元测试通过

**Story 文件：** `docs/implementation-artifacts/v0-1-7-tool-registry-and-builtin-tools.md`（待创建）

---

### Phase 8: LLM Factory (v0.1-8) 🔴 当前缺失

**目标：** 把 llm_factory.py 迁移到 harness，支持 thinking mode 适配

**关键交付：**
- [ ] 实现 get_llm_client(agent, *, enable_thinking) -> BaseChatModel
- [ ] 迁移 providers/openai_compat.py
- [ ] 实现 thinking.py（thinking mode 适配）
- [ ] 从 backend/app/engine/llm_factory.py 迁移代码
- [ ] 10+ 单元测试

**验收标准：**
- AC1: get_llm_client 函数签名与现状完全一致
- AC2: providers/openai_compat.py 迁移 OpenAI 兼容逻辑
- AC3: thinking.py 实现 thinking mode 适配（Claude extended thinking / OpenAI reasoning_effort）
- AC4: 从 backend/app/engine/llm_factory.py 删除代码，改为 import harness
- AC5: 10+ 单元测试通过

**Story 文件：** `docs/implementation-artifacts/v0-1-8-llm-factory-migration.md`（待创建）

---

## Design Notes

### 核心模块详细设计

#### §1 顶层包 `agent_flow_harness/`

**公开 API（`__init__.py`）：**

```python
from agent_flow_harness.engine import build_react_agent
from agent_flow_harness.graph import build_agent_graph, run_agent, run_agent_streaming
from agent_flow_harness.adapters import stream_events_to_app_events
from agent_flow_harness.guards import (
    TokenBudgetGuard,
    TimeBudgetGuard,
    ToolRateLimitGuard,
    ContentGuard,
)
from agent_flow_harness.tools import ToolRegistry, CommunityTool
from agent_flow_harness.slots import render_system_prompt
from agent_flow_harness.llm import get_llm_client
from agent_flow_harness.state import AgentState
from agent_flow_harness.checkpointer import get_checkpointer
from agent_flow_harness.middleware import Middleware, MiddlewareChain
```

**state.py — 共享 State schema：**

把现在 `app/engine/state.py:AgentState` 抽出来，**字段保持不变**：

```python
class AgentState(TypedDict):
    messages: list[BaseMessage]
    agent_id: str
    session_id: str
    call_chain: list[str]
    step_count: int
    error: str | None
    warnings: list[str]
    # ... (与现状一致)
```

**checkpointer.py — get_checkpointer()：**

```python
def get_checkpointer(
    mongo_uri: str,
    db_name: str,
    *,
    client: AsyncIOMotorClient | None = None,
) -> BaseCheckpointSaver:
    """返回 MongoDBSaver 实例。client 为 None 时自行创建。"""
```

---

#### §2 引擎层 `engine/`

> 单一执行器。evaluator / direct / planner 全部下线。

**react.py — 单一入口：**

```python
async def react_node(state: AgentState, config: RunnableConfig) -> dict:
    """
    单一 REACT 入口（v0.1-2 锁定）。

    不写流式 — 由 graph.astream_events + v0.1-3 Adapter 提供。
    不写 SSE — 应用层在 on_event 回调中处理。
    """
    llm = config["configurable"]["llm"]
    tools = config["configurable"]["tools"]
    context_window = config["configurable"].get("context_window")

    ws_token = _setup_workspace_context(state)
    try:
        tool_map = tools
        llm_with_tools = llm.bind_tools(list(tool_map.values())) if tool_map else llm

        current_messages = list(state.get("messages", []))
        step_count = state.get("step_count", 0)
        model_name = extract_model_name(llm)

        for iteration in range(_MAX_ITERATIONS):  # 25
            depth_result = check_depth(state)
            if not depth_result.allowed:
                return {**state, "error": depth_result.reason, "step_count": step_count}

            if should_compress(current_messages, model_name, context_window=context_window):
                current_messages = compress_messages(
                    current_messages, model_name, context_window=context_window
                )

            response = await llm_with_tools.ainvoke(current_messages)
            current_messages.append(response)
            step_count += 1

            if response.tool_calls:
                for tool_call in response.tool_calls:
                    tool_name = tool_call["name"]
                    tool_args = tool_call["args"]
                    tool_id = tool_call["id"]

                    tool = tool_map.get(tool_name)
                    if tool is None:
                        tool_result_content = f"Error: tool '{tool_name}' not found."
                    else:
                        try:
                            tool_result_content = await tool.ainvoke(tool_args)
                        except Exception as e:
                            tool_result_content = f"Error: {e}"

                    tool_message = ToolMessage(
                        content=str(tool_result_content),
                        tool_call_id=tool_id,
                    )
                    current_messages.append(tool_message)
                continue

            break

        return {
            **state,
            "messages": current_messages,
            "step_count": step_count,
        }
    finally:
        if ws_token is not None:
            reset_workspace_context(ws_token)
```

**关键设计点：**
- 不在这里面写 REACT 循环 — 循环由 StateGraph 边驱动
- 不在这里面 astream() — 流式由 graph.astream_events() 提供
- 不在这里面推 SSE 事件 — 由 adapters/stream_events.py 在外层转换
- 工具执行时仍需 workspace context / circuit breaker — 通过 config 注入

---

#### §3 图层 `graph/`

**builder.py — build_agent_graph：**

```python
def build_agent_graph(
    agent_doc: dict,
    *,
    checkpointer: BaseCheckpointSaver | None = None,
    guards: list[Guard] | None = None,
    middleware: MiddlewareChain | None = None,
) -> CompiledStateGraph:
    """
    构造 StateGraph：
        [guard_in]? -> [react] -> [guard_out]? -> END

    guards 为空时：仅 [react] -> END
    checkpointer 缺省时：使用 get_checkpointer()
    """
    builder = StateGraph(AgentState)

    # 添加 react 节点
    builder.add_node("react", react_node)

    # 添加 guard 节点（如果配置了）
    if guards:
        for guard in guards:
            guard_in_node = make_guard_in_node(guard)
            guard_out_node = make_guard_out_node(guard)
            builder.add_node(f"{guard.name}_in", guard_in_node)
            builder.add_node(f"{guard.name}_out", guard_out_node)

        # 拓扑：[guard_in]* -> react -> [guard_out]*
        for guard in guards:
            builder.add_edge(f"{guard.name}_in", "react")
            builder.add_edge("react", f"{guard.name}_out")

        builder.set_entry_point(f"{guards[0].name}_in")
        builder.set_finish_point(f"{guards[-1].name}_out")
    else:
        builder.set_entry_point("react")
        builder.add_edge("react", END)

    return builder.compile(checkpointer=checkpointer)
```

**runner.py — run_agent / run_agent_streaming：**

```python
async def run_agent(
    agent_doc: dict,
    input_state: AgentState,
    *,
    config: RunnableConfig | None = None,
) -> dict:
    """非流式入口 — 走 graph.ainvoke"""
    graph = build_agent_graph(agent_doc)
    return await graph.ainvoke(input_state, config=config)

async def run_agent_streaming(
    agent_doc: dict,
    input_state: AgentState,
    *,
    on_event: Callable[[dict], Awaitable[None]],
    config: RunnableConfig | None = None,
) -> dict:
    """
    流式入口 — 走 graph.astream_events(version="v2")
    on_event 收到的是【应用层事件 schema】(已转换)
    """
    graph = build_agent_graph(agent_doc)
    astream_iter = graph.astream_events(input_state, version="v2", config=config)
    await stream_events_to_app_events(astream_iter, on_event)
```

---

#### §4 适配器层 `adapters/`

**stream_events.py — stream_events_to_app_events：**

```python
async def stream_events_to_app_events(
    astream_iter: AsyncIterator[StreamEvent],
    on_event: Callable[[dict], Awaitable[None]],
    *,
    enable_thinking: bool = False,
) -> None:
    """
    订阅 LangGraph 原生事件，按规则触发 on_event 推送应用层事件。
    """
    accumulator = _StreamingAccumulator()

    async for event in astream_iter:
        if event["event"] == "on_chat_model_stream":
            chunk = event["data"]["chunk"]
            if chunk.content:
                await on_event(FinalAnswerDeltaEvent(content=chunk.content).dict())
            if enable_thinking and chunk.additional_kwargs.get("reasoning"):
                await on_event(ThinkingDeltaEvent(content=chunk.additional_kwargs["reasoning"]).dict())
            if chunk.tool_call_chunks:
                accumulator.accumulate_tool_calls(chunk.tool_call_chunks)

        elif event["event"] == "on_chat_model_end":
            output = event["data"]["output"]
            if output.content:
                await on_event(FinalAnswerEvent(content=output.content).dict())
            if output.tool_calls:
                for tool_call in output.tool_calls:
                    await on_event(ToolCallEvent(
                        tool_name=tool_call["name"],
                        args=tool_call["args"],
                        id=tool_call["id"],
                    ).dict())
            if enable_thinking and output.reasoning_content:
                await on_event(ThinkingEvent(content=output.reasoning_content).dict())

        elif event["event"] == "on_tool_start":
            await on_event(ToolCallStartEvent().dict())

        elif event["event"] == "on_tool_end":
            output = event["data"]["output"]
            await on_event(ToolResultEvent(
                tool_name=event["name"],
                content=str(output),
            ).dict())

        elif event["event"] in ("on_llm_error", "on_tool_error"):
            await on_event(ErrorEvent(
                message=str(event["data"]["error"]),
                source="llm" if "llm" in event["event"] else "tool",
            ).dict())
```

**应用层事件 schema（7 种）：**

```python
class ThinkingDeltaEvent(BaseModel):
    type: Literal["thinking_delta"] = "thinking_delta"
    content: str

class ThinkingEvent(BaseModel):
    type: Literal["thinking"] = "thinking"
    content: str

class FinalAnswerDeltaEvent(BaseModel):
    type: Literal["final_answer_delta"] = "final_answer_delta"
    content: str

class FinalAnswerEvent(BaseModel):
    type: Literal["final_answer"] = "final_answer"
    content: str

class ToolCallStartEvent(BaseModel):
    type: Literal["tool_call_start"] = "tool_call_start"

class ToolCallEvent(BaseModel):
    type: Literal["tool_call"] = "tool_call"
    tool_name: str
    args: dict
    id: str

class ToolResultEvent(BaseModel):
    type: Literal["tool_result"] = "tool_result"
    tool_name: str
    content: str

class ErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    message: str
    source: Literal["llm", "tool"]
```

---

#### §5 护栏层 `guards/`

**Guard 协议：**

```python
class Guard(Protocol):
    """护栏统一接口。粗粒度，作为 LangGraph Node。"""
    name: str

    async def check_in(self, state: AgentState) -> GuardResult:
        """react node 之前调用 — 决定是否放行 react"""

    async def check_out(self, state: AgentState, output: dict) -> GuardResult:
        """react node 之后调用 — 决定是否接受 react 输出"""

class GuardResult(BaseModel):
    decision: Literal["allow", "block", "warn"]
    reason: str = ""
```

**内置 4 类 Guard：**

| Guard | 行为 | 配置字段 |
|-------|------|---------|
| TokenBudgetGuard | 累计 token，超阈值 block | max_total_tokens: int |
| TimeBudgetGuard | wall-clock 计时，超时 block | max_wall_seconds: int |
| ToolRateLimitGuard | 同 tool N 次 / 同一 args 重复 → block | max_calls_per_tool, max_repeat_args |
| ContentGuard | tool input/output 黑名单匹配 | deny_patterns, redact_pii |

**nodes.py — guard -> LangGraph Node：**

```python
def make_guard_in_node(guard: Guard) -> Callable[[AgentState], dict]:
    """guard_in: 在 react 之前拦截"""
    async def guard_in_node(state: AgentState) -> dict:
        result = await guard.check_in(state)
        if result.decision == "block":
            return {**state, "error": result.reason}
        elif result.decision == "warn":
            return {**state, "warnings": state.get("warnings", []) + [result.reason]}
        return state
    return guard_in_node
```

---

#### §6 工具层 `tools/`

**ToolRegistry：**

```python
class ToolRegistry:
    """
    工具的全局注册中心。
    应用层启动时：registry.register(MyTool())
    Agent 执行时：ctx = registry.resolve(agent_doc)
    """
    def __init__(self):
        self._tools: dict[str, BaseTool] = {}
        self._community_tools: dict[str, CommunityTool] = {}

    def register(self, tool: BaseTool | CommunityTool) -> None:
        if isinstance(tool, CommunityTool):
            self._community_tools[tool.name] = tool
        else:
            self._tools[tool.name] = tool

    def resolve(self, agent_doc: dict) -> list[BaseTool]:
        """按 agent_doc["tools"] 字段过滤"""
        tool_configs = agent_doc.get("tools", [])
        result = []
        for tool_config in tool_configs:
            if not tool_config.get("enabled", True):
                continue
            name = tool_config["name"]
            if name in self._tools:
                result.append(self._tools[name])
            elif name in self._community_tools:
                community_tool = self._community_tools[name]
                config = community_tool.config_schema(**tool_config.get("config", {}))
                result.append(community_tool.build(config))
        return result

    def list_community_tools(self) -> list[CommunityTool]:
        return list(self._community_tools.values())
```

**CommunityTool 协议：**

```python
class CommunityTool(Protocol):
    """第三方可实现的工具协议。"""
    name: str
    description: str
    config_schema: type[BaseModel]
    enabled_by_default: bool = False

    def build(self, config: BaseModel) -> BaseTool: ...
```

**Agent 工具配置：**

```python
agent_doc["tools"] = [
    {"name": "bash", "enabled": True},
    {"name": "tavily_search", "enabled": True, "config": {"api_key_env": "TAVILY_API_KEY"}},
    {"name": "skill:code-review", "enabled": True},
    {"name": "mcp:github", "enabled": False},
]
```

---

#### §7 Slot 模板层 `slots/`

**SlotSchema：**

```python
SLOT_SCHEMA = [
    SlotDef(name="role",         label="角色",     required=True),
    SlotDef(name="task",         label="任务",     required=True),
    SlotDef(name="constraints",  label="约束",     required=False),
    SlotDef(name="context",      label="上下文",   required=False),
    SlotDef(name="output_format",label="输出格式", required=False),
    SlotDef(name="tool_declaration", label="工具声明", required=False),
]
```

**render_system_prompt：**

```python
def render_system_prompt(
    agent_doc: dict,
    *,
    overrides: dict[str, str] | None = None,
    variable_pool: dict[str, Any] | None = None,
    strict: bool = True,
) -> str:
    """
    函数签名与现在 slot_renderer.render_system_prompt_full 完全一致。
    前端零改动。
    """
```

---

#### §8 LLM 工厂 `llm/`

**get_llm_client：**

```python
def get_llm_client(
    agent: dict,
    *,
    enable_thinking: bool = False,
) -> BaseChatModel:
    """
    函数签名与现在 app.engine.llm_factory.get_llm_client 完全一致。
    """
```

**thinking mode 适配：**

```python
# thinking.py
def apply_thinking_mode(
    llm: BaseChatModel,
    *,
    enable_thinking: bool,
    model_name: str,
) -> BaseChatModel:
    """
    Claude: thinking={"type": "enabled", "budget_tokens": 5000}
    OpenAI o-series: reasoning_effort="high"
    其他: 静默忽略
    """
```

---

#### §9 中间件层 `middleware/`

**Middleware 协议：**

```python
class Middleware(Protocol):
    name: str
    order: int = 100  # 升序执行

    async def before_llm(self, state: AgentState) -> AgentState: ...
    async def after_llm(self, state: AgentState, response: AIMessage) -> AgentState: ...

    async def before_tool(self, state: AgentState, tool_call: dict) -> dict: ...
    async def after_tool(self, state: AgentState, tool_call: dict, result: str) -> AgentState: ...
```

**MiddlewareChain：**

```python
class MiddlewareChain:
    def __init__(self, middlewares: list[Middleware]):
        self._middlewares = sorted(middlewares, key=lambda m: m.order)

    async def run_before_llm(self, state: AgentState) -> AgentState:
        for mw in self._middlewares:
            try:
                state = await mw.before_llm(state)
            except Exception as e:
                logger.error(f"Middleware {mw.name} before_llm failed: {e}")
        return state

    async def run_after_llm(self, state: AgentState, response: AIMessage) -> AgentState:
        for mw in self._middlewares:
            try:
                state = await mw.after_llm(state, response)
            except Exception as e:
                logger.error(f"Middleware {mw.name} after_llm failed: {e}")
        return state

    # run_before_tool / run_after_tool 类似
```

**Guard vs Middleware 对照：**

| 维度 | Guard | Middleware |
|------|-------|------------|
| 位置 | LangGraph **Node**（graph 拓扑上可见） | 环绕 LLM/Tool 调用的**钩子**（不出现在 graph） |
| 粒度 | 粗 — 每次 react 节点前/后 | 细 — 每次 LLM/Tool 调用前/后 |
| 决策 | block / allow（决定流程是否继续） | 改写 / 记录 / 透传（**不阻断**） |
| 作用对象 | 整段 react 节点 | 单次 LLM 调用、单次 Tool 调用 |
| 配置载体 | `agent_doc["guards"]` | `agent_doc["middleware"]` |
| 典型场景 | token 超限、wall-clock 超时、循环检测、危险命令拦截 | audit 日志、trace 推送、prompt 注入、PII 打码 |

**判断口诀：**
- "**要不要让这一步发生**" → Guard（门）
- "**这一步发生时要改/记什么**" → Middleware（滤网）

---

### 增强模块占位（v0.2 / v0.3）

> 详见 SPEC.md §12.5 原文。本节列出的 9 个模块仅做目录占位，详细设计在对应 Story 中收敛。

| 模块 | 版本 | 优先级 | 与"长任务"相关性 | 与"可插拔"相关性 |
|------|------|-------|----------------|----------------|
| subagents | v0.2 | 🔴 P0 | ✅ 直接相关 | ✅ |
| sandbox | v0.2 | 🔴 P0 | ✅ 直接相关 | ⚠️ |
| acp | v0.2 | 🟡 P1 | ⚠️ | ✅ |
| providers | v0.2 | 🟡 P1 | ⚠️ | ✅ |
| context_engineering | v0.2 | 🟡 P1 | ✅ | ⚠️ |
| skills_fs | v0.2 | 🟢 P2 | ⚠️ | ✅ |
| agent_hierarchy | v0.3 | 🟢 P2 | ✅ | ⚠️ |
| config_reload | v0.3 | 🟢 P2 | ❌ | ⚠️ |
| channels | v0.3 | 🟢 P2 | ⚠️ | ✅ |

---

### 公开 API 总览（一行清单）

```python
# ============ 核心 6 模块（v0.1 锁定）============

# 图与运行
agent_flow_harness.build_agent_graph(agent_doc, *, checkpointer, guards, middleware)
agent_flow_harness.run_agent(agent_doc, input_state, *, config)
agent_flow_harness.run_agent_streaming(agent_doc, input_state, *, on_event, config)

# 适配器
agent_flow_harness.stream_events_to_app_events(astream_iter, on_event, *, enable_thinking)
agent_flow_harness.message_to_blocks(message)

# 护栏
agent_flow_harness.TokenBudgetGuard
agent_flow_harness.TimeBudgetGuard
agent_flow_harness.ToolRateLimitGuard
agent_flow_harness.ContentGuard

# 工具
agent_flow_harness.ToolRegistry
agent_flow_harness.CommunityTool

# Slot
agent_flow_harness.render_system_prompt

# LLM
agent_flow_harness.get_llm_client

# State
agent_flow_harness.AgentState
agent_flow_harness.get_checkpointer

# Middleware
agent_flow_harness.Middleware
agent_flow_harness.MiddlewareChain

# ============ 增强模块（v0.2 / v0.3 占位）============
# (详见 SPEC.md §13 原文)
```

---

### 版本路线图

| 版本 | 范围 | 关键 Story |
|------|------|-----------|
| **v0.1** | 核心 6 模块 | v0.1-1 ~ v0.1-8（8 个 Story） |
| **v0.2** | P0 + P1 增强 | subagents + sandbox + acp + providers + context_engineering |
| **v0.3** | P2 增强 + IM | skills_fs + agent_hierarchy + config_reload + channels |

---

## Story 依赖图

```
v0.1-1 (skeleton)
  ↓
v0.1-2 (react node)
  ↓
v0.1-3 (adapters)
  ↓
v0.1-4 (guards)
  ↓
v0.1-5 (middleware)
  ↓
v0.1-6 (slots)

v0.1-2 → v0.1-7 (tools) [可并行]
v0.1-2 → v0.1-8 (llm factory) [可并行]
```

---

## References

- [Source: docs/planning-artifacts/architecture.md] — 架构决策与技术选型
- [Source: docs/planning-artifacts/epics.md] — Epic 定义与 Story 列表
- [Source: docs/planning-artifacts/prds/prd-agent-flow-2026-06-05/prd.md] — PRD 功能需求
- [Source: backend/app/engine/] — 当前实现代码（迁移源）
- [Source: MEMORY.md] — 后端必须使用 uv 工具链（项目核心约定）
