---
title: 'Human 审批节点：固定 approve/reject + comment 字段 + 看板审批入口'
type: 'feature'
created: '2026-06-23'
baseline_commit: '55b877bb12d0962291e6ed8186759cbbcf42ae5a'
status: 'in-review'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Human 节点当前 UI 永远渲染"批准/驳回"两枚按钮，与用户在 HumanNodeConfig 中配置的 `options` 完全脱节；用户配置的自定义 options 既不进入 UI，也不进入 variables。同时审批人无法留下指导意见，approval 数据未结构化回流到 variables，下游节点无法消费。看板卡片（TaskBoardCard）在 waiting_human 状态下没有任何审批入口，必须点开详情抽屉才能操作，工作流不顺畅。

**Approach:** 取消用户可配置 `options` 字段，固定 `approve` / `reject` 两个系统 action + `comment` 字段（审批人留言，**可选**）。审批结果以 `{decision, comment, approver, decided_at}` 结构写入 `variables[human_decision_<node_id>]`，下游节点可通过 `${human_decision_node_X.comment}` 等表达式消费。看板卡片 waiting_human 状态新增"通过/驳回"快捷按钮 + comment 输入弹窗，免开抽屉即可处理。

## Boundaries & Constraints

**Always:**
- API 行为必须向后兼容：现有调用方不传 `comment` 仍能正常工作（视为空字符串）
- 状态机不变：`approve` → `RUNNING`，`reject` → `FAILED`
- `comment` 字段值必须出现在 `variables` 写入的字典中（哪怕为空字符串）
- 看板审批入口复用现有 `interveneMutation` 与 `tasks-api.intervene` 调用，不引入新的 mutation
- 前端 i18n 文案统一从现有常量中复用，不新增硬编码字符串
- KISS：不做超时前自动通知、不做审批人分配（assignee 字段在 human.py 已存在但前端未实现，本次不纳入）

**Ask First:**
- 节点 ID 含特殊字符（如 `.` `-`）时，变量 key 的安全字符集规则？（默认：仅保留 `[a-zA-Z0-9_]`，其他替换为 `_`）

**Never:**
- 不引入工作流编辑器外的新增审批配置面板
- 不修改 `approve`/`reject` 在后端的状态机转移逻辑
- 不修改后端 `reason` 字段为必填（保持 Optional）
- 不改 LangGraph 引擎、超时守护、checkpoint 序列化逻辑
- 不动 Gateway 节点、LLM 节点等其他节点类型

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| HAPPY_APPROVE_WITH_COMMENT | Task waiting_human, POST intervene `{action: "approve", comment: "数据已确认", version: N}` | 状态 → RUNNING, variables 写入 `{human_decision_node_X: {decision: "approve", comment: "数据已确认", approver: "user_1", decided_at: "2026-06-23T..."}}` | N/A |
| HAPPY_APPROVE_NO_COMMENT | Task waiting_human, POST intervene `{action: "approve", version: N}` (无 comment) | 状态 → RUNNING, variables 写入 `comment: ""` | N/A |
| REJECT_WITH_COMMENT | Task waiting_human, POST intervene `{action: "reject", comment: "质检不通过", version: N}` | 状态 → FAILED, variables 写入同 approve 形式, decision="reject" | N/A |
| REJECT_NO_COMMENT | Task waiting_human, POST intervene `{action: "reject", version: N}` | 状态 → FAILED, variables 写入 `comment: ""` | 前端弹窗中 reject 时给 placeholder 提示"建议填写驳回原因" |
| INVALID_VERSION | version 不匹配 | 409 Conflict | 后端已有逻辑,前端 toast 提示 |
| NODE_ID_WITH_SPECIAL_CHARS | 节点 ID = "审批-质检" | variables key = `human_decision_审批_质检` (特殊字符替换为 `_`) | sanitize 函数处理 |
| BOARD_CARD_QUICK_APPROVE | 用户在看板卡片点"通过"按钮 | 弹出 Modal 输入 comment (可选) → 提交 | 弹窗可关闭、loading 状态正确 |
| BOARD_CARD_QUICK_REJECT | 用户在看板卡片点"驳回"按钮 | 弹出 Modal 输入 comment (强烈建议) → 提交 | comment 为空时显示警告但不阻断 |

## Code Map

- `backend/app/schemas/task.py:22-27` -- `TaskIntervene` Pydantic schema,需把 `reason` 重命名为 `comment`(或新增字段并保留 reason 兼容)
- `backend/app/api/v1/tasks.py:163-278` -- `intervene_task` 路由, approve/reject 分支需更新变量写入 key 格式
- `backend/app/services/task_service.py` -- `update_variables` 方法需在 approve/reject 路径下被复用(已存在)
- `backend/app/engine/workflow/nodes/human.py:37-71` -- `HumanNodeExecutor.execute`, `options` 字段保留但标注 deprecated(后端兼容)
- `frontend/src/features/workflow-editor/node-config-panels/HumanNodeConfig.tsx` -- **删除** options 添加/编辑 UI, 保留 title/description/timeout_ms/timeout_action/assignee
- `frontend/src/pages/tasks-page.tsx:774-819` -- 详情抽屉审批按钮区, 简化为固定两按钮 + comment 输入
- `frontend/src/components/task-board-card.tsx` -- **新增** waiting_human 状态底部审批入口 + Modal
- `frontend/src/services/tasks-api.ts:175-178` -- `TaskIntervenePayload` interface, 把 `reason` 改为 `comment`
- `frontend/src/components/task-board-card.tsx` props 扩展 -- `onApprove` / `onReject` / `onIntervene` callback

## Tasks & Acceptance

**Execution:**
- [x] `backend/app/schemas/task.py` -- `TaskIntervene` 新增 `comment: str | None = None` 字段,保留 `reason` 字段(标 deprecated) -- 兼容性
- [x] `backend/app/api/v1/tasks.py` -- intervene_task 函数内: approve/reject 分支写入 variables 时,key 改为 `human_decision_<sanitized_node_id>`,value 结构改为 `{decision, comment, approver, decided_at}` -- 主需求
- [x] `backend/app/api/v1/tasks.py` -- 新增 `_sanitize_node_id` 静态方法,过滤特殊字符为 `_` -- I/O 矩阵覆盖
- [x] `frontend/src/services/tasks-api.ts` -- `TaskIntervenePayload` 新增 `comment?: string`,保留 `reason?` -- 兼容性
- [x] `frontend/src/features/workflow-editor/node-config-panels/HumanNodeConfig.tsx` -- 删除 options 添加/编辑 UI(保留 state 引用以避免 break), 在文件顶部注释说明"options 已废弃,系统固定 approve/reject" -- 简化配置
- [x] `frontend/src/pages/tasks-page.tsx` -- 详情抽屉审批区: 删除 `humanOptions` 动态判断分支,固定渲染两按钮 + comment TextArea,reject 时 placeholder 提示必填原因 -- 简化 UI
- [x] `frontend/src/components/task-board-card.tsx` -- waiting_human 状态: 底部新增"通过/驳回"按钮, 点击触发 `onApprove`/`onReject` callback,Props 扩展支持 `interveneLoading` -- 看板入口
- [x] `frontend/src/components/task-board-card.tsx` -- 新增 `ApprovalModal` 子组件: comment TextArea + 确认/取消, 提交时调 `onIntervene` -- 弹窗交互
- [x] `frontend/src/pages/tasks-page.tsx` -- 看板列 `TaskBoardColumn` props 透传 `handleApprove` / `handleReject`, 与现有 `interveneMutation` 联动 -- 串联数据流

**Acceptance Criteria:**
- Given 用户在 HumanNodeConfig 中配置任意 `options`(如 `["通过", "驳回", "补充"]`), when 保存并部署 workflow, then 任务进入 waiting_human 状态时,前端 UI **不**显示用户配置的 options 文本,固定显示"通过"/"驳回"两枚按钮。
- Given Task 处于 waiting_human, when 用户在详情抽屉或看板弹窗中输入 comment 文本并点击"通过", then 任务状态变为 RUNNING, `variables["human_decision_<node_id>"].comment` 等于用户输入的文本(空时为 `""`), `decision === "approve"`, `approver === current_user.id`。
- Given 用户在弹窗中**不**填 comment 直接提交"驳回", then 提交成功,`comment === ""`,前端不阻断流程(仅 placeholder 提示)。
- Given Task 处于 waiting_human, when 用户在看板卡片底部点"通过"/"驳回", then 弹出 Modal 输入 comment → 提交后看板卡片自动从 waiting_human 列移除,无需打开详情抽屉。
- Given 节点 ID 含特殊字符(如"审批-质检"或"node.5"), when 审批完成, then `variables` 中对应 key 全部为安全字符(字母数字下划线)。

## Verification

**Commands:**
- `cd /Users/huyuekai/company/agent-flow && uv run pytest backend/tests/api/test_task_intervention.py -v` -- 现有测试通过,新增 comment 字段的回归测试
- `cd /Users/huyuekai/company/agent-flow && uv run mypy backend/app/schemas/task.py backend/app/api/v1/tasks.py` -- 期望: Success, no errors
- `cd /Users/huyuekai/company/agent-flow/frontend && pnpm tsc --noEmit && pnpm lint` -- 期望: Success
- `cd /Users/huyuekai/company/agent-flow/frontend && pnpm test -- HumanNodeConfig task-board-card` -- 单元测试

**Manual checks (if no CLI):**
- 启动前后端,创建带 Human 节点的 workflow,执行到 waiting_human → 看板卡片应显示两枚按钮
- 点"通过" → 弹窗输入 comment → 提交 → 卡片消失,任务变 RUNNING
- 打开 MongoDB 检查 task 文档 variables 字段,key 形如 `human_decision_node_xxx`,value 含 `decision/comment/approver/decided_at`
- 在 HumanNodeConfig 配置 options 字段 → 保存 → 再次进入 waiting_human → 确认 UI 仍只显示"通过/驳回"

## Design Notes

**变量命名约定选择**：`human_decision_<node_id>` 而非裸 `<node_id>`，原因：
1. 命名空间清晰：避免与上游节点写出的同名变量冲突
2. 表达语义：Gateway 用 `${human_decision_node_X.decision}` 一眼就知道是人类决策
3. 调试友好：MongoDB 查 variables 时能用 `human_decision_*` 前缀过滤

**comment 字段保留为可选**：KISS 原则。审批摩擦最小化，业务上 comment 主要是上下文附加，不应成为流程阻断点。前端 reject 时给 placeholder "建议填写驳回原因" 软引导。

**前后端双重 sanitize**：node_id 在 workflow 编辑阶段就保证安全（langgraph 不允许特殊字符），但 API 层仍做一次防御性过滤。
</frozen-after-approval>
