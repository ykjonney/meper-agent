# 任务清单：v0.1 收尾 + v0.2 规划

> 创建：2026-06-24
> 配套文档：[plan.md](./plan.md)
> 粒度：**粗粒度（按 Story 拆）**
> 规模标识：S = 0.5d, M = 1-2d, L = 3-5d, XL = 1w+（不出现，拆解后已避免）

---

## Phase A：v0.1 收尾（实施 v0.1-1/2/7/8）

> ⚠️ **依赖声明**：v0.1-7 / v0.1-8 强依赖 v0.1-2（react_node），v0.1-2 强依赖 v0.1-1（包骨架）。所以 Phase A 必须按 A.1 → A.2 → [A.3 ∥ A.4] 顺序。

### A.1 [M] 实施 v0.1-1：Harness 包骨架

| 字段 | 内容 |
|---|---|
| **AC** | 1. `packages/harness/pyproject.toml` 创建 2. 6 个核心模块目录 + `__init__.py` 3. `state.py` / `checkpointer.py` / `build_agent_graph` 实现 4. `packages/harness/README.md` 写完 5. `uv sync` 安装成功 |
| **依赖** | 无 |
| **验证** | `uv run python -c "from agent_flow_harness import build_agent_graph"` 成功 |
| **文件变更** | `+packages/harness/pyproject.toml` `+packages/harness/README.md` `+packages/harness/src/agent_flow_harness/{__init__,state,checkpointer}.py` `+packages/harness/src/agent_flow_harness/{engine,adapters,guards,middleware,slots,tools,llm}/{__init__,...}.py`（占位 7 个空目录 + 7 个 __init__） |
| **参考** | [v0-1-1-harness-package-skeleton.md](../docs/implementation-artifacts/v0-1-1-harness-package-skeleton.md) |
| **CP-A1 节点** | ✅ 通过此任务后 v0.1-2/7/8 才能开 |

### A.2 [M] 实施 v0.1-2：单一 react 节点

| 字段 | 内容 |
|---|---|
| **AC** | 1. `packages/harness/src/agent_flow_harness/engine/react.py` 实现 `react_node(state, llm, tools, ctx)` 2. 合并原 `react_executor.run` + `_run_react_inner` 为单函数 3. 删除 `backend/app/engine/agent/evaluator.py` / `direct_executor.py` / `planner_executor.py` / `react_executor.py` 4. 应用层调用点改为 `from agent_flow_harness.engine import react_node` 5. 15+ 单元测试通过 |
| **依赖** | A.1 |
| **验证** | `uv run pytest packages/harness/tests/engine/test_react.py -v` 全绿 + `uv run pytest backend/tests/` 无回归 |
| **文件变更** | `+packages/harness/src/agent_flow_harness/engine/react.py` `+packages/harness/tests/engine/test_react.py` `-backend/app/engine/agent/evaluator.py` `-backend/app/engine/agent/direct_executor.py` `-backend/app/engine/agent/planner_executor.py` `-backend/app/engine/agent/react_executor.py` `~backend/app/engine/agent/builder.py`（改 import） |
| **参考** | [v0-1-2-single-react-node-and-merge.md](../docs/implementation-artifacts/v0-1-2-single-react-node-and-merge.md) |
| **CP-A1 节点** | ✅ 通过此任务后 v0.1-7/8 才能开 |

### A.3 [M] 实施 v0.1-7：ToolRegistry + 4 内置工具（**可与 A.4 并行**）

| 字段 | 内容 |
|---|---|
| **AC** | 1. `packages/harness/src/agent_flow_harness/tools/registry.py` 实现 `ToolRegistry`（register/resolve/list_community_tools） 2. `CommunityTool` Protocol 定义 3. 4 个内置工具（bash/read/write/write_to_output）迁移 4. `engine/react.py` 改用 `registry.resolve(agent_doc)` 5. 删除 `backend/app/engine/tools/` 6. 20+ 单元测试通过 |
| **依赖** | A.2 |
| **验证** | `uv run pytest packages/harness/tests/tools/ -v` 全绿 + 应用层集成测试通过 |
| **文件变更** | `+packages/harness/src/agent_flow_harness/tools/{__init__,registry,builtin,community}.py` `+packages/harness/tests/tools/{test_registry,test_builtin,test_community}.py` `-backend/app/engine/tools/*.py` `~packages/harness/src/agent_flow_harness/engine/react.py` |
| **参考** | [v0-1-7-tool-registry-and-builtin-tools.md](../docs/implementation-artifacts/v0-1-7-tool-registry-and-builtin-tools.md) |
| **并行建议** | A.3 与 A.4 在 worktree 中并行实施（互不依赖） |

### A.4 [M] 实施 v0.1-8：LLM 工厂迁移（**可与 A.3 并行**）

| 字段 | 内容 |
|---|---|
| **AC** | 1. `packages/harness/src/agent_flow_harness/llm/factory.py` 实现 `get_llm_client(agent, *, enable_thinking)` 2. `llm/providers/openai_compat.py` 实现 3. `llm/thinking.py` 实现 `apply_thinking_mode` 4. `engine/react.py` 改用 `get_llm_client(agent_doc, enable_thinking=...)` 5. 删除 `backend/app/engine/llm_factory.py` 6. 15+ 单元测试通过 |
| **依赖** | A.2 |
| **验证** | `uv run pytest packages/harness/tests/llm/ -v` 全绿 + 应用层集成测试通过 |
| **文件变更** | `+packages/harness/src/agent_flow_harness/llm/{__init__,factory,thinking}.py` `+packages/harness/src/agent_flow_harness/llm/providers/{__init__,openai_compat}.py` `+packages/harness/tests/llm/test_factory.py` `-backend/app/engine/llm_factory.py` `~packages/harness/src/agent_flow_harness/engine/react.py` `~packages/harness/src/agent_flow_harness/__init__.py`（暴露 get_llm_client） |
| **参考** | [v0-1-8-llm-factory-migration.md](../docs/implementation-artifacts/v0-1-8-llm-factory-migration.md) |
| **并行建议** | A.3 与 A.4 在 worktree 中并行实施 |

### A.5 [S] Phase A 检查点验证

| 字段 | 内容 |
|---|---|
| **AC** | 1. CP-A2：`uv run pytest packages/harness/tests/` 全绿（实测 246 passed） 2. CP-A3：`uv run pytest backend/tests/` 无回归（实测 814 passed） 3. `from agent_flow_harness import build_agent_graph, build_client_from_doc, build_client_from_env, ToolRegistry` 全部成功（注：LLM 工厂最终命名为 `build_client_from_doc/env`，非早期文档中的 `get_llm_client`） |
| **依赖** | A.3 + A.4 |
| **验证** | `uv run pytest packages/harness/ backend/ --tb=short` 0 failed |
| **CP** | 阻断裂点 — 不通过不能进 Phase B |

---

## Phase B：v0.2 规划（写 5 个 Story 文档）

> 范围：5 个 Story 文档的撰写（**只写文档，不实施**）

### B.1 [M] 写 v0.2-1 subagents Story 文档

| 字段 | 内容 |
|---|---|
| **AC** | 1. 文档结构与 v0.1-1 同构（Story/AC/Tasks/Dev Notes/File List） 2. 5-10 条 AC 3. 至少 1 个代码示例 + 1 个 ASCII 流程图 4. 依赖声明：`depends on: v0.1-1 ~ v0.1-8` |
| **依赖** | 无（可与 B.2-B.5 并行） |
| **验证** | 文件存在 + 章节齐全 + AC 可勾选 |
| **文件变更** | `+docs/implementation-artifacts/v0-2-1-subagents.md` |
| **参考** | SPEC.md §12.5 subagents 节（主人决策） |

### B.2 [M] 写 v0.2-2 sandbox Story 文档

| 字段 | 内容 |
|---|---|
| **AC** | 1. 同 B.1 结构 2. **必须**有"sandbox backend 选型"小节（Docker / E2B / subprocess+seccomp） 3. 至少 3 个安全维度约束（资源/网络/文件系统） 4. 依赖声明：`depends on: v0.1-7`（bash 工具需要） |
| **依赖** | 主人决策 sandbox 选型（plan.md §4.2 开放问题 #2） |
| **验证** | 文件存在 + 选型明确 + 安全约束可执行 |
| **文件变更** | `+docs/implementation-artifacts/v0-2-2-sandbox.md` |

### B.3 [M] 写 v0.2-3 acp Story 文档

| 字段 | 内容 |
|---|---|
| **AC** | 1. 同 B.1 结构 2. 定义 acp 协议最小集（握手/调用/响应/错误） 3. 依赖声明：`depends on: v0.1-5`（middleware） |
| **依赖** | 可与 B.4/B.5 并行 |
| **文件变更** | `+docs/implementation-artifacts/v0-2-3-acp.md` |

### B.4 [M] 写 v0.2-4 providers Story 文档

| 字段 | 内容 |
|---|---|
| **AC** | 1. 同 B.1 结构 2. 列出 v0.1-8 未覆盖的 provider（azure / bedrock / vertex / ollama）3. 依赖声明：`depends on: v0.1-8` |
| **依赖** | 可与 B.3/B.5 并行 |
| **文件变更** | `+docs/implementation-artifacts/v0-2-4-providers.md` |

### B.5 [M] 写 v0.2-5 context_engineering Story 文档

| 字段 | 内容 |
|---|---|
| **AC** | 1. 同 B.1 结构 2. 至少覆盖 3 种策略：压缩/总结/检索 3. 依赖声明：`depends on: v0.1-2`（react_node 内做） |
| **依赖** | 可与 B.3/B.4 并行 |
| **文件变更** | `+docs/implementation-artifacts/v0-2-5-context-engineering.md` |

### B.6 [S] Phase B 检查点验证

| 字段 | 内容 |
|---|---|
| **AC** | 1. 5 个 v0.2 Story 文档已写入 `docs/implementation-artifacts/` 2. 所有 `Depends on` 字段引用前序 Story ID 正确 3. CP-B1（结构同构）+ CP-B2（依赖自洽）全部满足 |
| **依赖** | B.1 ~ B.5 |
| **验证** | `ls docs/implementation-artifacts/v0-2-*.md \| wc -l` 输出 5 |
| **CP** | 阻断裂点 — 不通过不算 Phase B 完成 |

---

## Phase C：v0.2 实施（**不在本计划范围**）

> CP-B2 通过后，另开 plan 详细规划实施任务。

---

## 总览进度

| 阶段 | 任务数 | 状态 |
|---|---|---|
| 阶段 | 任务数 | 状态 |
|---|---|---|
| Phase A | 5 个 (A.1, A.2, A.3∥A.4, A.5) | ✅ 全部完成（v0.1-1~8 全部实施，814+246 测试绿） |
| Phase B | 6 个 (B.1~B.5∥, B.6) | ✅ 全部完成（5 个 v0.2 Story 文档已写入，依赖自洽） |
| Phase C | TBD | 🔒 待规划（v0.2 实施，另开 plan） |

**实际完成记录**（2026-06-25 核对）：
- Phase A：v0.1-1~v0.1-8 全部落地并提交（见 git log `b9d0a41`~`8edcb04`），另含 thread 历史重建（`73fe14c`）与 backend `harness_integration` adapter 骨架（`549092d`）。
- Phase B：5 个 v0.2 Story 文档均写入 `docs/implementation-artifacts/`，结构同构、`Depends on` 自洽，全部 `Status: backlog`（未实施）。

---

## 跟踪工具说明

- 浮浮酱每次开工前用 `TaskList` 工具建立详细子任务（细到 AC 级）
- 每个 Phase 完成后勾选对应任务
- 实施时用 `superpowers:executing-plans` 风格逐项核对
- 验证失败立即标记 + 反馈主人

---

**Last Updated**: 2026-06-25（Phase A+B 全部完成，核对后状态对齐）
