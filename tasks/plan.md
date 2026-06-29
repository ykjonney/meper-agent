# 实施计划：v0.1 收尾 + v0.2 规划

> 计划创建：2026-06-24
> 范围：harness 重构专项（agent-flow-harness PyPI 包）
> 关联文档：[SPEC.md](../SPEC.md) / [v0.1 Story 索引](../docs/implementation-artifacts/)
> 粒度：粗粒度（按 Story 拆任务，不按 AC 拆）

> 📌 **进度结论（2026-06-25 核对）**：Phase A（v0.1 实施）+ Phase B（v0.2 规划文档）**全部完成**。CP-A2/A3 实测通过（harness 246 passed / backend 814 passed）。下一步 = Phase C（v0.2 实施），需另开 plan。

---

## 1. 现状盘点

### 1.1 v0.1 Story 完成度

| Story | 主题 | 文档 | 实施 | 状态 |
|---|---|---|---|---|
| v0.1-1 | Harness 包骨架 | ✅ | ✅ `b9d0a41` | done |
| v0.1-2 | 单一 react 节点 | ✅ | ✅ `01462c0`（已删 react_executor 等 dead code） | done |
| v0.1-3 | astream_events 适配器 | ✅ | ✅ `7bc4d2f` | done |
| v0.1-4 | 4 类 Guard | ✅ | ✅ `ae68a73` | done |
| v0.1-5 | Middleware 链 | ✅ | ✅ `23ebdf5` | done |
| v0.1-6 | Slot 渲染 | ✅ | ✅ `8edcb04` | done |
| v0.1-7 | ToolRegistry + 内置工具 | ✅ | ✅ `8a6f42a` | done |
| v0.1-8 | LLM 工厂迁移 | ✅ | ✅ `cf77567` | done |
| 额外 | thread 历史重建（messages_to_app_events + get_thread_messages） | ✅ | ✅ `73fe14c` | done |
| 额外 | backend harness_integration adapter 骨架（接线模式文档） | ✅ | ✅ `549092d` | done |

> ✅ **更新（2026-06-25 核对）**：v0.1 全部 8 Story 已实施并提交。`backend/app/engine/` 旧执行器（evaluator/direct_executor/planner_executor/react_executor）已在 v0.1-2 删除。CP-A2/CP-A3 实测通过：harness `246 passed`、backend `814 passed` 无回归。LLM 工厂最终 API 命名为 `build_client_from_doc` / `build_client_from_env`（非早期文档中的 `get_llm_client`）。

### 1.2 v0.2 路线图（SPEC.md §13）

| 模块 | 版本 | 优先级 | 与长任务 | 与可插拔 |
|---|---|---|---|---|
| subagents | v0.2 | 🔴 P0 | ✅ | ✅ |
| sandbox | v0.2 | 🔴 P0 | ✅ | ⚠️ |
| acp | v0.2 | 🟡 P1 | ⚠️ | ✅ |
| providers | v0.2 | 🟡 P1 | ⚠️ | ✅ |
| context_engineering | v0.2 | 🟡 P1 | ✅ | ⚠️ |

> v0.3 占位（4 个 P2 模块）暂不规划。

---

## 2. 依赖图

### 2.1 v0.1 全部 8 Story 依赖图

```
v0.1-1 (skeleton)            ← 必须先做（创建 packages/ 目录结构）
  ↓
v0.1-2 (react node)          ← 必须先做（v0.1-7/8 强依赖 react_node）
  ├─→ v0.1-3 (adapters)      ← 流式事件，必备
  │     ↓
  │   v0.1-4 (guards)
  │     ↓
  │   v0.1-5 (middleware)
  │     ↓
  │   v0.1-6 (slots)
  │
  ├─→ v0.1-7 (tools)         ← [可与 v0.1-8 并行]
  │     depends: v0.1-2
  │
  └─→ v0.1-8 (llm factory)   ← [可与 v0.1-7 并行]
        depends: v0.1-2
```

### 2.2 v0.2 五模块依赖推测（基于 SPEC.md §13 + §12.5）

```
v0.1 全部完成
  ↓
v0.2-1 subagents (P0)        ← 调度多 Agent 协作，依赖 v0.1 全部
  ↓
v0.2-2 sandbox (P0)          ← 沙箱执行，依赖 v0.1-7 (bash 工具需要)
  ↓
  [P1 三模块可并行]
  ├─ v0.2-3 acp              ← Agent Communication Protocol（外部接口）
  ├─ v0.2-4 providers        ← 扩展 LLM 工厂（v0.1-8 已锁 openai/anthropic/azure）
  └─ v0.2-5 context_engineering ← context 压缩/总结/检索
```

---

## 3. 阶段划分与检查点

### Phase A：v0.1 收尾（实施 v0.1-1/2/7/8）

**目标**：把 harness 包从"文档规划"推进到"代码就绪"

| 检查点 | 验收 | 阻塞处理 |
|---|---|---|
| **CP-A1**：v0.1-1/2 完成 | ✅ `packages/harness/` 存在 + `react_node` 可调用 + backend 旧代码删除（`b9d0a41`+`01462c0`） | 已通过 |
| **CP-A2**：v0.1-7/8 全部 25+ 测试通过 | ✅ `uv run pytest packages/harness/tests/` → 246 passed（0.41s） | 已通过 |
| **CP-A3**：应用层 169+ 测试无回归 | ✅ `uv run pytest backend/tests/` → 814 passed（无回归） | 已通过 |

### Phase B：v0.2 规划（写 5 个 Story 文档）

**目标**：把 v0.2 路线图细化为可执行 Story

| 检查点 | 验收 |
|---|---|
| **CP-B1**：5 个 Story 文档结构与 v0.1 同构 | ✅ Story/AC/Tasks/Dev Notes/File List 五段齐全 |
| **CP-B2**：依赖关系自洽 | ✅ 文档内 `depends on` 字段引用前序 Story ID 正确 |

### Phase C：v0.2 实施（不在本计划内，CP-B2 通过后另开计划）

---

## 4. 风险与开放问题

### 4.1 风险矩阵

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| v0.1-1 目录结构被 backend 现状反复打破 | 高 | 中 | 用 `mkdir -p` + `touch __init__.py` 一次性建好；用 git 跟踪 |
| v0.1-7 4 个内置工具迁移时发现 backend 现有实现有 bug | 中 | 中 | 浮浮酱在 v0.1-7 实施时**先读 backend 现有代码**，不一致处先反馈主人 |
| v0.1-8 thinking mode 适配 langchain 版本不一致 | 中 | 中 | 浮浮酱用 `uv add` 锁定 langchain-openai / langchain-anthropic 版本 |
| 应用层 169+ 测试大量失败（v0.1 迁移破坏现状） | 中 | 高 | 每次迁移跑一遍 `pytest backend/tests/`；失败立即回滚 |
| v0.2 Story 文档与 SPEC.md §12.5 详细设计冲突 | 中 | 中 | 以 SPEC.md §12.5 为权威，浮浮酱发现冲突时立即反馈主人 |
| 沙箱（sandbox）需要 Docker / E2B 等外部依赖，v0.2-2 实施门槛高 | 高 | 高 | 主人先决策 sandbox backend 选型（Docker 本地 / E2B 云端 / 进程级） |

### 4.2 开放问题（需要主人决策）

1. **v0.1 实施节奏**：
   - 选项 A：把 v0.1-1/2/7/8 一次性串行做完（4-5 个 Story 串跑，1-2 周）
   - 选项 B：v0.1-1 + v0.1-2 串行做，v0.1-7/8 拆为两个并行 worktree
   - 选项 C：主人按需触发，不做整体规划

2. **sandbox backend 选型（v0.2-2 前置）**：
   - Docker 本地沙箱
   - E2B / Fly.io 云沙箱
   - 进程级 subprocess + seccomp 轻量沙箱
   - 暂不实现，v0.2-2 推到 v0.3

3. **v0.2 Story 文档产出形式**：
   - 单个 .md 文档（与 v0.1 同构）
   - 5 个 Story 合成一个 v0-2-roadmap.md
   - 仅写 §AC 段，详细 Dev Notes 留到实施时写

---

## 5. 验证标准

- ✅ `tasks/plan.md`（本文档）已通过主人审阅
- ✅ `tasks/todo.md` 已生成，结构对齐本文档 §3 阶段
- ✅ 5 个 v0.2 Story 文档已写到 `docs/implementation-artifacts/`
- ✅ 所有 v0.2 Story 文档内 `Depends on` 字段引用前序 Story ID 正确
- ✅ v0.1 实施节奏已确定并执行：v0.1-1~8 全部串行实施完成（对应 4.2 开放问题 #1 的选项 A）

---

## 6. References

- [SPEC.md](../SPEC.md) — 单一权威规格
- [v0.1-1](../docs/implementation-artifacts/v0-1-1-harness-package-skeleton.md) ~ [v0.1-8](../docs/implementation-artifacts/v0-1-8-llm-factory-migration.md) — 8 个 Story
- [MEMORY.md](../CLAUDE.md#memory) — 后端用 uv 工具链
- [docs/planning-artifacts/architecture.md](../docs/planning-artifacts/architecture.md) — 架构决策
