# Story 4.14: 多上游节点隐式并行 + Join 语义

**Epic:** Epic 4 — Workflow 执行引擎
**Status:** draft
**Story ID:** 4-14
**Story Key:** 4-14-multi-parent-implicit-parallel-join

> ⚠️ **本 Story 范围重大**：改动 workflow 引擎核心（`_execute_node` 调度逻辑），影响所有 workflow。需独立评审 + 数据迁移策略。

## Story

As a workflow 编辑者，
I want 拖线连接多个上游到同一节点时，引擎自动并行执行上游并 join 后再触发下游，
So that 工作流能真正利用 DAG 并行能力，而不是"看起来并行实际串行"。

> 🔧 **关键背景（owner: 主人 2026-06-23 决策）**：
> - **当前缺陷**：`engine.py:335-336` 用 `for next_node_id in downstream: await self._execute_node(...)` 串行执行
> - **多上游汇聚场景**：当前"自然满足"（因为是 await 串行），但**没有 join 语义**——上游本应并行的也被串行
> - **目标语义**：DAG 中 in-degree > 1 的节点 → 上游用 `asyncio.gather` 并行 → join 后触发下游
> - **不引入"Join 节点类型"**（owner 决策）：主流工作流引擎（Airflow/Prefect/Temporal/n8n）均采用隐式 join，加显式节点只会增加认知负担
> - **现有 Parallel 节点**（owner 决策）：保留作为"高级 fan-out 原语"，本 Story 不动

## Acceptance Criteria

### AC1: 引擎识别 in-degree > 1 的节点
**Given** workflow DAG 中某节点 `node_X` 有多个上游父节点（`len(_in_edges[node_X]) > 1`）
**When** 引擎准备执行 `node_X`
**Then** 检测到这是 join 节点
**And** 内部用 `asyncio.gather(*parent_coroutines, return_exceptions=True)` 并行执行所有尚未完成的父节点
**And** 等待所有父节点**成功完成**才执行 `node_X`
**And** 若任一父节点失败，按"任一失败即 join 失败"语义处理（不执行 `node_X`）

### AC2: in-degree == 1 节点保持串行
**Given** `node_Y` 只有一个上游父节点
**When** 引擎执行
**Then** 行为与当前一致：`await parent; await self._execute_node(node_Y)`
**And** 不引入并发开销（按 KISS 原则不必要时不并发）

### AC3: in-degree == 0 节点（Start 节点）正常执行
**Given** Start 节点没有父节点
**When** 引擎初始化
**Then** 行为与当前一致：直接 await 第一个 Start 节点
**And** 不影响后续 fan-out/join 逻辑

### AC4: 变量命名空间合并
**Given** `node_X` 有父节点 A 和 B，两者 output 已写入 `pool[A]` 和 `pool[B]`
**When** `node_X` 开始执行
**Then** 引擎把 `pool[A]` 和 `pool[B]` 合并到 `node_X` 可见的 `variables` 中
**And** 命名空间约定：父节点 A 的 output 在 `variables.parents.<A_id>.<field>` 下访问
**And** 节点自身仍可通过 `input_mapping` 显式配 `{{ parents.A.field }}` 表达式（不强制要求）
**And** 不破坏现有 `input_mapping` 行为（向后兼容）

### AC5: Join 失败语义
**Given** `node_X` 有父节点 A、B、C；A 失败，B、C 成功
**When** join 完成
**Then** `node_X` **不**执行
**And** workflow 标记为 FAILED
**And** 错误信息包含失败的父节点 ID + 错误原因
**And** audit log 记录 `join_failed` 事件，附 in-degree 数、失败父节点列表、已完成父节点列表

### AC6: Checkpoint 序列化支持 join 状态
**Given** workflow 执行到 join 节点，部分父节点已完成、部分未完成
**When** 服务重启 / 任务恢复
**Then** checkpoint 包含 `join_in_progress: list[str]` 字段
**And** 恢复时只重试**未完成**的父节点，已完成的从 checkpoint 恢复其 output
**And** 所有父节点都完成后正常 join 触发下游

### AC7: UI 提示并发执行
**Given** 用户在 WorkflowCanvas 拖线连接多上游到单节点
**When** 选中有 join 语义的节点
**Then** 节点可视化高亮（如边框颜色）提示"该节点等待 N 个上游 join"
**And** 鼠标悬停显示 tooltip："A、B 并行执行，全部完成后触发本节点"
**And** 单上游节点不显示该高亮

### AC8: 执行时长统计
**Given** 节点 X 有父 A、B 并行执行
**When** X 完成
**Then** timeline 事件中 `node_X.duration_ms` = X 实际执行时长
**And** `node_X.wait_for_parents_ms` = 从 A 启动到最后一个父完成的时间
**And** 总 wall time = wait_for_parents_ms + duration_ms

### AC9: 现有 Parallel 节点不受影响
**Given** 现有使用 Parallel 节点的工作流
**When** 本 Story 升级后
**Then** Parallel 节点的 fan-out + gather 行为**不变**
**And** Parallel 节点的下游 join 语义按 AC1-AC6 处理
**And** 现有 Parallel workflow 无需迁移

### AC10: 单元/集成测试
**Given** 新增 join 逻辑
**When** 跑测试套件
**Then** 至少包含以下测试用例：
- 多上游 join 成功路径（A、B 并行，C 触发）
- in-degree == 1 串行回归测试
- 任一父失败的 join 失败语义
- 4 个父节点 join（DAG 更复杂）
- checkpoint 恢复 join 状态
- 现有 Parallel 节点测试不破

## Out of Scope（不纳入本 Story）

- ❌ 不引入"Join 节点类型"（owner 决策）
- ❌ 不引入 join_strategy 配置（all/any/n-of-m）—— 默认 all
- ❌ 不改 Parallel 节点（保留原样）
- ❌ 不实现"部分父成功 + 部分失败继续"的复杂 join 策略
- ❌ 不改 input_mapping 语法（仅扩展 `parents.<id>` 命名空间约定）
- ❌ 不动 UI 大改（仅节点高亮 + tooltip）

## Files to Modify

| 文件 | 改动 |
|---|---|
| `backend/app/engine/workflow/engine.py` | `_execute_node` 重构：检测 in-degree，>1 用 gather；新增 `_join_parents` 方法 |
| `backend/app/engine/workflow/variable_pool.py` | 新增 `merge_parent` 方法：把 `pool[A]` 复制到 `variables.parents.A` 命名空间 |
| `backend/app/services/task_service.py` | checkpoint 序列化加 `join_in_progress` 字段 |
| `frontend/src/features/workflow-editor/WorkflowCanvas.tsx` | join 节点高亮 + tooltip |
| `backend/tests/engine/workflow/test_workflow_engine.py` | 新增 join 测试用例 |
| `docs/implementation-artifacts/sprint-status.yaml` | 加入 `4-14-multi-parent-implicit-parallel-join: ready-for-dev` |

## Risks

1. **现有 workflow 行为变化**：原本"伪串行"的多上游场景可能突然变快，可能暴露隐藏的 race condition
2. **checkpoint 兼容性**：旧 checkpoint 不含 `join_in_progress` 字段，需要 schema 迁移
3. **错误处理复杂度**：gather 中 `return_exceptions=True` 的语义需要统一约定
4. **测试覆盖**：DAG 复杂度提升，测试矩阵可能指数级增长

## Open Questions（待 owner 决策）

1. **并发粒度默认**：所有 in-degree > 1 节点**自动**并行，还是用户 opt-in？
   - 默认推荐：自动并行（符合 DAG 自然语义）
2. **失败回滚**：父节点 A 失败后，B、C 还要不要继续执行？
   - 推荐：失败立即 cancel 其他 gather 中的协程（resource friendly）
3. **变量命名空间冲突**：父节点 A 写 `result.x`，父节点 B 也写 `result.x`，join 后保留哪个？
   - 推荐：用 `parents.A.x` / `parents.B.x` 完全隔离（AC4 已采用）
4. **数据迁移策略**：现有"伪串行" workflow 是否需要标记为"需要重新测试"？
   - 推荐：sprint-status 加 `4-14` 后，由 QA 重点回归现有多上游 workflow
