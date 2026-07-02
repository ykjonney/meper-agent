# v0.3.0 — 应用层 Agent 引擎全量迁移到 harness

> **目标**：应用层 agent 相关功能最终全部用 `agent_flow_harness` 接管。应用层代码可以变，但对外接口（HTTP/WS/SSE + 事件格式）与功能不可变。难对齐的点用 `[GAP]` 标记。
>
> **现状**：harness 引擎已完整实现（state/slots/llm/checkpointer/guards/middleware/context-engineering/subagents/sandbox），但应用层生产路径仍走老引擎 `app/engine/agent/`；唯一接入点 `harness_integration/stream.py` 已写好但无调用方，开关 `USE_HARNESS_ENGINE=False`。

---

## 一、范围界定（替换 / 保留 / 丢弃）

### 1.1 替换 — 老引擎被 harness 等价物接管

| 老引擎文件 | 职责 | harness 对应 | 对齐度 |
|---|---|---|---|
| `app/engine/agent/react_executor.py` | REACT 循环（run / run_streaming） | `agent_flow_harness.engine.react.react_node` + `graph/runner.run_agent_streaming` | ✅ 等价，harness 把 workspace/压缩外置到装配层 |
| `app/engine/agent/builder.py`（图/streaming 装配部分） | build_agent_graph / run_agent_streaming / `_resolve_execution_context` | `graph.builder.build_agent_graph` + `graph.runner.build_config` + 新 Adapter 层 `resolve_*` | ✅ 等价（装配逻辑下沉到 harness_integration） |
| `app/engine/agent/slot_renderer.py` | 5 段 prompt 渲染 | `agent_flow_harness.slots.renderer.render_system_prompt_full` | ✅ byte-identical，harness 解耦了 expression_resolver / tool_declaration |
| `app/engine/agent/context.py` | token 估算 / 压缩 / context_window 表 | `agent_flow_harness.engine.context` + `context_engineering/`（可插拔策略） | ✅ 超集 |
| `app/engine/agent/depth_guard.py` | 深度 + 环检测 | `agent_flow_harness.engine.depth_guard` | ✅ 逐字等价 |
| `app/engine/agent/evaluator.py` | 输入评估（恒返回 react） | harness graph 入口节点 | ✅ 极薄，可由 harness 吸收 |
| `app/engine/checkpointer.py` | MongoDBSaver 单例 | `agent_flow_harness.checkpointer`（build_mongo_saver + configure 单例） | ✅ 等价，构造从硬编码改注入 |
| `app/engine/state.py` | AgentState TypedDict | `agent_flow_harness.state.AgentState` | ✅ 超集（harness 多 5 个 guard 字段，向后兼容） |
| `app/engine/llm_factory.py`（纯构建部分） | build_client_from_doc / build_client_from_env / auth / thinking | `agent_flow_harness.llm`（逐字移植） | ✅ 等价 |

### 1.2 保留 — app 层独有，harness 故意不实现

这些**不在替换范围**，继续留在 `app/`，但 import 来源可能从 `app.engine.*` 改成更合适的归属：

| 文件 | 为什么保留 |
|---|---|
| `app/engine/agent/workflow_executor.py`（7 个 task 工具 + propose/dispatch） | 业务工具，调 TaskService，harness 无工作流概念 |
| `app/engine/agent/builder.py` 的 `build_tool_declaration` / `build_skill_declaration` | 重型函数，查 Skill/MCP/Workflow/builtin/task 五类；harness renderer 只接 callable |
| `app/engine/llm_factory.py` 的 `get_llm_client` 编排 | model-table 查找 + API key 解密，DB/crypto 耦合 |
| `app/engine/tool/workspace.py`（WorkspaceManager） | 被 8+ 处调用，文件隔离语义 |
| `app/engine/tool/sandbox.py`（SandboxExecutor）的 admin 部分 | 与 harness DockerSandbox 并存（harness 走 provider/context） |
| `app/engine/tool/mcp_client.py`（test_connection / discover_tools）+ `mcp_tool_cache.py` | admin 功能 + 进程级缓存，harness 只有运行时加载 |
| `app/engine/tool/skill_fs.py` + `skill_parser.py` | 磁盘物化 + 解析入库，harness SkillManager 假设已物化 |
| `app/engine/events/`（EventBus） | 进程内事件总线，harness 不碰业务事件 |
| **整个 `app/engine/workflow/` 子包** | DAG 引擎、节点执行器、human resume、变量池、表达式、校验 — harness 完全无此概念 |

### 1.3 丢弃 — 死代码 / 遗留

| 文件 | 理由 |
|---|---|
| `app/engine/context.py`（顶层占位） | 只有 logger.warning，真正压缩在 `agent/context.py` |
| `app/engine/agent/planner_executor.py` | 未被 builder 引用（execution_path 恒为 react） |
| `app/engine/agent/direct_executor.py` | 同上 |

### 1.4 调用点清单（迁移时必须逐个改）

**直接调 agent 执行的入口（3 处，全在 `agents.py`）**：

| 入口 | 位置 | 当前调用 | 迁移后 |
|---|---|---|---|
| `POST /{agent_id}/stream` | `agents.py:683,811` | `run_agent_streaming` | harness `run_agent_streaming` 等价（经 Adapter） |
| `POST /{agent_id}/invoke` | `agents.py:551,593` | `build_agent_graph` → `graph.ainvoke` | harness `build_agent_graph` + `run_agent` |
| `POST /{agent_id}/preview` | `agents.py:499` | `preview_agent`（不调 LLM） | 保留 app 层（只是组装 prompt+工具声明） |

**间接触发（workflow → agent 节点，1 处耦合点）**：

| 位置 | 当前 | 迁移后 |
|---|---|---|
| `workflow/node_executor.py:AgentNodeExecutor`（`251-404`） | `build_agent_graph` + `graph.ainvoke`（非流式 StateGraph） | harness `build_agent_graph` + `build_config` + `run_agent`（非流式） |

**其他 `from app.engine` import（不改执行逻辑，仅改 import 归属）**：
- `sessions.py:11,283...` — WorkspaceManager（保留，归属不变）
- `tools.py:10,47,126` — skill_fs / builtin_tools 元信息 / skill_parser（保留）
- `workflows.py:209,243` — WorkflowValidator（保留）
- `task_service.py:142` — WorkflowEngine（保留）
- `task_recovery.py:152` — get_human_timeout_monitor（保留）
- `notification_service.py:7` / `task_service.py:13` — EventBus（保留）
- `model_service.py:360` — build_client_from_doc（改 import 到 harness 或保留 backend 包装）
- `session_service.py` / `file_storage.py` / `maintenance.py` — WorkspaceManager（保留）

---

## 二、目标架构

### 2.1 三层结构（不变，强化）

```
① API 层 (FastAPI)         app/api/v1/*          只懂 HTTP + 业务语义
② Integration Adapter 层   app/engine/harness_*  应用层世界 ↔ harness（装配 + 调用）
③ harness                  agent_flow_harness    纯净 runtime（不认 app.*）
```

迁移完成后，**所有"应用层调 agent 执行"的路径都必须经过 ② Adapter 层**，不允许 API 层直接 import harness 的图构建函数。这样 harness 升级、工具策略调整都收敛在一处。

### 2.2 Adapter 层职责（`harness_integration/__init__.py` 要填实的函数）

```
装配（应用层对象 → harness 注入物）：
  resolve_llm(agent) → BaseChatModel       # 查 model 表 + 解密 + delegate 到 harness.build_client_from_doc
  resolve_tools(agent, workspace) → list    # backend 工具 + harness 工具 + SkillManager + MCP 的合并
  resolve_guards(agent_doc) → list          # harness resolve_guards（agent 文档可选配置）
  resolve_middleware(agent_doc) → list      # harness resolve_middleware（默认 UsageMiddleware）
  get_checkpointer() → MongoDBSaver         # harness build_mongo_saver(client, db) + configure 单例
  build_agent_doc(agent) → dict             # 提取 harness 需要的配置子集 + tool 声明 callable

执行（调用 harness）：
  run_chat(agent, session, input) → AppEvent 流    # 实时聊天路径（替换 stream 端点执行）
  run_agent_node(agent, node_overrides, variables) → 结果  # 工作流 agent 节点路径（新增，替换 AgentNodeExecutor 内部）
  get_history(session_id) → AppEvent 列表           # 历史（可选：从 harness thread 读；或保留 MessageService）

输出转换：
  app_event_to_timeline_entry(AppEvent) → dict       # AppEvent → 前端 timeline_entries
  app_events_to_message(events) → MessageRecord      # AppEvent 列表 → 持久化消息
```

### 2.3 工具策略（三层模型，已在 stream.py 验证）

| 工具类别 | 来源 | 说明 |
|---|---|---|
| 文件/shell（bash/read/write/glob/grep） | harness BUILTIN_TOOLS | 委托 Sandbox，替换 backend 同名工具 |
| Skill（load_skill） | harness SkillManager.make_load_tool | 替换 backend 的 skill loader |
| MCP（mcp__*） | harness McpToolLoader.load_tools | 替换 backend 的 mcp_tool_cache（运行时；admin 缓存保留 backend） |
| Task/工作流（propose/dispatch/task_*，7 个） | backend workflow_executor | **[保留]** harness 无业务工具，作为 backend-only tools 混入 |
| `write_to_output` | **[GAP]** 见下方 | harness 无等价 |

---

## 三、分阶段迁移计划

> 原则：**每阶段独立可交付、可回退、可验证**。开关 `USE_HARNESS_ENGINE` 作为前两阶段的灰度阀。

### 阶段 0 — 准备：填 Adapter 骨架（无行为变化）

**目标**：把 `harness_integration/__init__.py` 的 10 个 `NotImplementedError` 按 docstring 填实，建立正式装配契约。**此时不改任何调用点**，仅让 Adapter 可用。

**改动**：
- `resolve_llm`：调 `app.engine.llm_factory.get_llm_client`（保留编排），内部已 delegate 到 harness 构建函数。
- `resolve_tools`：实现"三层合并"（backend task 工具 + harness 文件工具 + Skill/MCP），逻辑参考 `stream.py:73-127`，但**收敛成一个函数**（stream.py 内联的逻辑提取出来）。
- `resolve_guards` / `resolve_middleware`：`harness.resolve_guards(agent_doc.get("guards"))` / `resolve_middleware(...)`；默认 middleware = `[UsageMiddleware()]`。
- `get_checkpointer`：`harness.build_mongo_saver(get_mongodb_client().delegate, settings.MONGODB_DB_NAME)` + `configure_checkpointer`。
- `build_agent_doc`：提取 `{_id, name, prompt_slots, guards, middleware, tools}` + 附带一个 `tool_declaration_callable`（包装 backend 的 `build_tool_declaration`）。
- `app_event_to_timeline_entry` / `app_events_to_message`：按 docstring 实现映射（8 种 AppEvent → timeline dict）。

**验证**：单元测试每个 resolve_* 返回正确类型；不改端点行为。

---

### 阶段 1 — 打通 stream 开关（灰度可切换）

**目标**：`POST /{agent_id}/stream` 端点能按 `USE_HARNESS_ENGINE` 在老引擎/harness 间切换，事件格式对前端零差异。

**改动**：
- `agents.py:_run_agent()`（约 811 行）加分支：
  ```python
  if settings.USE_HARNESS_ENGINE:
      from app.engine.harness_integration import run_chat  # 或直接用 stream.run_agent_streaming_harness
      result = await run_agent_streaming_harness(exec_doc, initial_state, on_event=_on_event, ...)
  else:
      result = await run_agent_streaming(exec_doc, initial_state, on_event=_on_event, ...)
  ```
- 端点内联逻辑（system prompt / 历史 / 文件 / 持久化 / 事件队列）**原样不动**——两条路径的 `state` 和 `on_event` 契约一致。
- `stream.py` 的 `run_agent_streaming_harness` 改为**调用阶段 0 的 Adapter resolve_* 函数**（消除内联装配重复）。

**验证**：
- 开关 False 时行为与迁移前完全一致（回归）。
- 开关 True 时：前端 SSE 事件流正常显示（token 流、工具调用、思考、最终答案）；消息持久化 timeline 正常。
- `[GAP-事件]` 核对：harness 的 `tool_call` 事件带 `id` 字段，老引擎 streaming 版不带——确认前端无硬依赖（前端若用 tool_name 索引则无影响）。
- `[GAP-error事件]` harness 产出结构化 `error` 事件（source=llm/tool），老引擎把 tool 异常塞进 `tool_result.content`——确认前端 error 渲染兼容两种。

---

### 阶段 2 — 切换 invoke 端点（非流式）

**目标**：`POST /{agent_id}/invoke` 也走 harness。

**改动**：
- `agents.py:invoke_agent`（593 行）：`build_agent_graph` → `graph.ainvoke` 改为调 Adapter 的 harness 装配 + `harness.run_agent`（非流式）。
- invoke 的返回值结构需保持不变（提取最终 AIMessage 文本）。

**验证**：开关 True/False 双路径返回一致；工具调用结果一致。

---

### 阶段 3 — 切换 workflow 的 AgentNodeExecutor

**目标**：工作流里的 agent 节点用 harness 执行。

**改动**（`node_executor.py:251-404`，**唯一耦合点**）：
- 替换 `build_agent_graph` + `graph.ainvoke` 为 harness 装配 + `run_agent`（非流式）。
- **保留** AgentNodeExecutor 的所有后处理逻辑：
  - workspace 创建（`WorkspaceManager.create_task_workspace` + `set_workspace_context`）
  - context slot 覆盖（仅 `context` 卡槽）
  - 超时 + 重试
  - 文件提取（`_register_task_output_files` + `_extract_files_from_messages`）
- Adapter 新增 `run_agent_node(agent, node_overrides, variables)` 封装这条路径（含 workspace + thread_id = `{node_id}_{ts}`）。

**验证**：
- `[GAP-workspace]` 工作流 agent 节点的 workspace 语义（task 专属 output/）需确认 harness 工具经 Sandbox 能写入正确路径（harness DockerSandbox 的 mounts 需配置 output 目录）。
- `[GAP-write_to_output]` 若 agent 用了 `write_to_output` 工具，harness 无等价——见下方专项。

---

### 阶段 4 — 历史/checkpointer 收敛（可选，风险较高）

**目标**：统一数据源，消除"端点手动重建 messages"与"checkpointer thread"双轨。

**现状**：stream 端点每次从 `MessageService.list_messages` + `_history_to_langchain_messages` 重建历史，**不依赖** checkpointer。harness graph 虽接 checkpointer（用于 REACT 多步状态），但历史真相在 MessageRecord。

**改动**（可选）：
- 启用 Adapter 的 `get_history(session_id)`：从 harness thread 读 messages → `messages_to_app_events`。
- 或保留现状（MessageRecord 是单一真相，每次请求全量喂入）。

**建议**：**本阶段暂不做**。当前"每次请求全量重建"虽不优雅但可靠，且 timeline_entries 的历史回放已经工作。除非有明确的性能/一致性需求，否则保持。标记为 `[DEFERRED]`。

---

### 阶段 5 — 清理：删除老引擎、关开关

**前置条件**：阶段 1-3 全量切换并稳定运行一段时间。

**改动**：
- 删除 `app/engine/agent/react_executor.py`、`builder.py`（图/streaming 部分）、`slot_renderer.py`、`context.py`、`depth_guard.py`、`evaluator.py`、`planner_executor.py`、`direct_executor.py`、`app/engine/context.py`。
- `app/engine/state.py` → 改为从 harness re-export（或直接用 harness 的）。
- `app/engine/checkpointer.py` → 删除，全用 harness 的。
- `app/engine/llm_factory.py` → 仅保留 `get_llm_client` 编排（delegate 到 harness 构建）。
- 删除 `USE_HARNESS_ENGINE` 开关（永远 True）。
- `app/engine/agent/builder.py` 仅保留 `build_system_prompt` / `build_tool_declaration` / `preview_agent`（非执行逻辑），可改名为 `app/engine/prompt.py`。

**验证**：全量回归（stream / invoke / preview / workflow agent 节点 / human resume）。

---

## 四、`[GAP]` 难对齐点汇总（需专门处理）

### [GAP-1] `write_to_output` 工具
- **问题**：backend 有 `write_to_output`（写入 output/，用户可下载），harness 无等价。
- **影响**：stream + workflow agent 节点都可能用。
- **方案**：在 Adapter 层补一个 backend-only 工具（复用现有实现，注入 workspace），与 task 工具同策略混入 harness graph。**不删功能**。

### [GAP-2] workspace quota + bash circuit breaker
- **问题**：backend `write`/`write_to_output` 有 quota 检查，`bash` 有 circuit breaker；harness 工具委托 Sandbox，无这些应用层保障。
- **方案**：用 harness 的 middleware 体系补齐——`UsageMiddleware` 已有 token 统计，可加自定义 middleware 实现 quota/breaker；或在 Sandbox 配置层覆盖（mem/cpu/timeout 已有）。**短期**：依赖 Sandbox 配置；**长期**：补 middleware。

### [GAP-3] tool_call 事件 `id` 字段
- **问题**：harness `ToolCallEvent` 带 `id`，老引擎 streaming 版不带。
- **影响**：若前端按事件结构严格解析，多字段可能报错（但 AppEvent 是 `extra=forbid`，序列化成 dict 后前端 JSON 解析不受限）。
- **方案**：核对前端 `agent-api.ts` / timeline 渲染逻辑；大概率无影响（前端用 `tool_name`）。**需验证**。

### [GAP-4] error 事件语义
- **问题**：harness 产出结构化 `error` 事件（`{type:error, message, source}`），老引擎把 tool 异常塞进 `tool_result.content`。
- **方案**：端点的 `_on_event` 已对 `error` 类型有兜底（agents.py:829 推 SSE）。需确认前端 error 渲染走 `event["type"]=="error"` 分支。**需验证**。

**核对结论（阶段1）**：harness `ErrorEvent` 字段为 `{type, message, source}`，老引擎/前端契约（`chat-panel.tsx:591` 硬编码读 `event.content`）用的是 `{type, content}`。已在 `harness_integration/stream.py:_on_event_dict` 把 `message` 重映射为 `content`，使 harness 路径 error 事件与老引擎一致，前端零改动。`source` 字段保留供日志。两路径不冲突：执行器整体崩溃仍走端点 except 兜底推 `{type, content}`。

### [GAP-5] workflow agent 节点 workspace 写入路径
- **问题**：AgentNodeExecutor 依赖 task 专属 output/，harness 工具经 Sandbox 写入需正确 mount。
- **方案**：Adapter 的 `run_agent_node` 配置 DockerSandbox mounts 时，把 task workspace 的 input/output/tmp 都挂上（参考 stream.py:160-164 的 mounts 配置）。**配置层解决**。

### [GAP-6] MCP 工具缓存
- **问题**：backend 有 `mcp_tool_cache`（5min TTL，进程级），harness `McpToolLoader` 每次重新连接。
- **影响**：性能。MCP 连接建立开销大。
- **方案**：Adapter 的 `resolve_tools` 内部包一层缓存（复用 backend 的 cache key 策略），或在 harness McpToolLoader 加缓存。**短期**：Adapter 包缓存；**长期**：harness 内置。

### [GAP-7] content_blocks.py 空占位
- **问题**：harness `adapters/content_blocks.py` 是空文件（`message_to_blocks` 未实现）。
- **影响**：若历史重建用 `messages_to_blocks` 会失败。
- **方案**：当前迁移路径用 `messages_to_app_events`（已实现），不依赖 content_blocks。**暂不影响**。

---

## 五、不变量（迁移前后必须一致）

1. **HTTP 接口契约**：`POST /agents/{id}/stream|invoke|preview` 的请求/响应结构不变。
2. **SSE 事件格式**：8 种事件类型 + 字段，前端零改动（除 [GAP-3/4] 待核对）。
3. **消息持久化**：MessageRecord 结构 + timeline_entries 结构不变。
4. **历史回放**：前端从 timeline_entries 重建的消息展示不变。
5. **工具能力**：bash/read/write/glob/grep/skill/mcp/task 全可用，功能等价（write_to_output 见 [GAP-1]）。
6. **workflow 行为**：DAG 执行、human resume、变量传递、文件提取 — 完全不变（workflow 引擎本身不换，只换内部 agent 节点的执行器）。
7. **depth/cycle 保护**：嵌套调用深度 + 环检测行为不变（harness depth_guard 逐字等价）。

---

## 六、验证策略

每个阶段：
1. **开关 False 回归**：迁移代码不生效时，行为与迁移前字节级一致。
2. **开关 True 功能测试**：手测 stream（token 流 + 工具调用 + 思考 + 多轮）、invoke、preview、workflow 含 agent 节点 + human 审批。
3. **事件 diff**：同一 agent + 同一输入，对比老/harness 产出的事件序列（type/字段）。
4. **持久化 diff**：对比写入的 MessageRecord + timeline_entries。

---

## 七、风险与回退

- **回退机制**：阶段 1-3 期间，`USE_HARNESS_ENGINE=False` 立即回到老引擎（代码仍在）。阶段 5 删除老引擎后才不可回退，故阶段 5 须在前 3 阶段稳定后进行。
- **最大风险**：阶段 3（workflow agent 节点）——它是后台执行，错误不易即时发现；且涉及 workspace 文件提取。需重点验证。
- **并行风险**：harness 的 REACT 与老引擎在上下文压缩策略上可能细微差异（harness 有可插拔 ContextStrategy），默认行为需对齐（默认用 compress_messages 等价路径，不引入 SummarizationStrategy 除非显式配置）。

---

## 八、交付物

- 阶段 0：`harness_integration/__init__.py` 10 个函数实现 + 单测
- 阶段 1：`agents.py` stream 分支 + `stream.py` 重构用 Adapter
- 阶段 2：`agents.py` invoke 分支
- 阶段 3：Adapter `run_agent_node` + `node_executor.py` 切换
- 阶段 4：`[DEFERRED]`
- 阶段 5：删除老引擎文件 + 关开关 + 重命名
