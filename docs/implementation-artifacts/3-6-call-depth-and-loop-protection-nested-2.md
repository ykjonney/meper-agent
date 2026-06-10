# Story 3.6: 调用深度与循环保护

**Epic:** Epic 3 — Agent 自主执行引擎
**Status:** ready-for-dev
**Story ID:** 3-6
**Story Key:** 3-6-call-depth-and-loop-protection-nested-2

## Story

As a 开发者，
I want 平台限制 Agent→Workflow→Agent 的嵌套调用深度并检测循环调用，
So that 系统不会因无限递归或过深嵌套导致资源耗尽或不可预测行为。

> ⚠️ **关键背景**：`depth_guard.py` 已存在骨架代码（`MAX_DEPTH=3` + `check_depth()`），但尚未集成到引擎。本 Story 需要将其**完善并接入**执行引擎。
>
> 🔧 **范围裁剪说明**：当前 Workflow 执行引擎（`engine/workflow/`）和 Task 管理器（`engine/task/`）尚未实现。`workflow_executor.py` 中的 `create_task` 仍是 mock stub。因此本 Story 的深度保护聚焦于：
> 1. **Agent → Agent 嵌套**：通过 Agent 工具调用链防止递归
> 2. **REACT 循环保护增强**：现有 25 次迭代上限是硬编码的粗粒度保护
> 3. **可扩展的深度追踪基础设施**：为后续 Workflow→Agent 嵌套预留接口

## Acceptance Criteria

### AC1: AgentState 包含调用链追踪字段
**Given** Agent 执行引擎的 `AgentState` TypedDict
**When** 检查其定义
**Then** 包含 `call_chain: list[str]` 字段（有序实体 ID 列表）
**And** 包含 `current_depth: int` 字段（当前嵌套深度，0-based）
**And** 初始调用时 `call_chain = [agent_id]`，`current_depth = 0`

### AC2: 深度检查函数完善
**Given** `depth_guard.py` 模块
**When** 审查其实现
**Then** 提供 `check_depth(state: AgentState) -> DepthCheckResult` 函数
**And** `DepthCheckResult` 包含 `allowed: bool`、`current_depth: int`、`max_depth: int`、`reason: str | None`
**And** 当 `current_depth >= MAX_DEPTH` 时 `allowed = False`
**And** 当 `call_chain` 中出现重复 `agent_id`（循环调用）时 `allowed = False`
**And** `MAX_DEPTH` 可通过环境变量 `AGENT_MAX_DEPTH` 配置，默认 3

### AC3: REACT 执行器集成深度保护
**Given** Agent 在 REACT 循环中执行工具调用
**When** 工具调用返回后准备下一轮推理
**Then** 每轮迭代开始前检查 `current_depth`
**And** 深度超限时立即终止 REACT 循环，返回明确的深度超限错误信息
**And** 错误信息包含：当前深度、最大允许深度、调用链路径（如 `Agent_A → Agent_B → Agent_C`）

### AC4: 循环调用检测
**Given** Agent 的调用链 `call_chain`
**When** 新一轮执行中检测到 `call_chain` 内的 `agent_id` 重复出现
**Then** 判定为循环调用，立即终止执行
**And** 返回错误信息包含：循环路径（如 `Agent_A → Agent_B → Agent_A`，检测到循环）

### AC5: 深度保护日志记录
**Given** 深度保护机制触发（超限或循环检测）
**When** 执行被终止
**Then** 记录 `depth_limit_exceeded` 或 `circular_call_detected` 日志事件
**And** 日志包含 `agent_id`、`current_depth`、`call_chain`、`reason`
**And** 执行结果中的 `error` 字段包含结构化错误信息

### AC6: invoke/stream 端点传递初始深度
**Given** 外部通过 API 调用 Agent（invoke 或 stream）
**When** 构建 `initial_state`
**Then** `call_chain = [agent_id]`，`current_depth = 0`
**And** 如果请求头或参数中携带 `X-Call-Chain`（未来嵌套场景），解析并追加到 `call_chain`

### AC7: 单元测试覆盖
**Given** 本 Story 的所有深度保护逻辑
**When** 运行测试套件
**Then** 覆盖以下场景：
- 深度 0 → 允许执行
- 深度达到 MAX_DEPTH → 拒绝执行
- 循环检测 → 拒绝执行
- 自定义 MAX_DEPTH（通过环境变量）
- call_chain 为空时的默认行为
- 错误信息格式验证

## Tasks / Subtasks

### 后端（Backend）

- [x] **T1: 扩展 AgentState 添加深度追踪字段** (AC: #1)
  - [x] 修改 `backend/app/engine/state.py`
  - [x] `AgentState` 添加 `call_chain: list[str]`（默认 `[]`）
  - [x] `AgentState` 添加 `current_depth: int`（默认 `0`）

- [x] **T2: 完善 depth_guard 模块** (AC: #2)
  - [x] 修改 `backend/app/engine/agent/depth_guard.py`
  - [x] 定义 `DepthCheckResult` dataclass（`allowed`, `current_depth`, `max_depth`, `reason`）
  - [x] 实现 `check_depth(state)` — 深度超限检查
  - [x] 实现 `detect_cycle(call_chain)` — 循环调用检测
  - [x] `MAX_DEPTH` 支持环境变量 `AGENT_MAX_DEPTH`，默认 3
  - [x] 实现 `format_call_chain(call_chain)` — 生成人类可读的调用链字符串

- [x] **T3: evaluator 集成初始深度** (AC: #1, #6)
  - [x] 修改 `backend/app/engine/agent/evaluator.py`
  - [x] `evaluate_input()` 返回结果中初始化 `call_chain` 和 `current_depth`
  - [ ] 支持 `X-Call-Chain` header 传入外部调用链

- [x] **T4: react_executor 集成深度保护** (AC: #3, #4, #5)
  - [x] 修改 `backend/app/engine/agent/react_executor.py`
  - [x] 每轮 REACT 迭代开始前调用 `check_depth(state)`
  - [x] 深度超限或循环检测时终止循环，设置 `error` 字段
  - [x] 日志记录 `depth_limit_exceeded` / `circular_call_detected` 事件

- [x] **T5: invoke/stream 端点传递调用链** (AC: #6)
  - [x] 修改 `backend/app/api/v1/agents.py`
  - [x] `invoke_agent` 端点：构建 initial_state 时设置 `call_chain` 和 `current_depth`
  - [x] `stream_agent` 端点：同上
  - [x] 从请求头 `X-Call-Chain` 解析外部调用链（可选）

- [x] **T6: 后端测试** (AC: #7)
  - [x] 新建 `backend/tests/engine/test_depth_guard.py`
  - [x] 测试 `check_depth` 各种场景
  - [x] 测试 `detect_cycle` 各种场景
  - [x] 测试 `format_call_chain` 格式化
  - [x] 测试自定义 `MAX_DEPTH`（环境变量）
  - [x] 运行 `cd backend && uv run pytest tests/engine/test_depth_guard.py -v`

## Dev Notes

### 🔧 技术栈与约定

**后端（FastAPI + LangGraph + Motor）：**
- Python 包管理：**uv**（非 pip/poetry），`uv run pytest`
- LangGraph StateGraph：`StateGraph(AgentState)` + `add_messages` reducer
- 日志：`structlog`，通过 `logger.info("event_name", key=value)` 记录
- 环境变量：`os.environ.get("AGENT_MAX_DEPTH", "3")`

### 📐 关键架构约束

**现有 depth_guard.py 骨架：**
```python
# backend/app/engine/agent/depth_guard.py
MAX_DEPTH = 3  # Agent → Workflow → Agent 最大嵌套层数

def check_depth(call_chain: list[str]) -> bool:
    """Check if the call depth exceeds the maximum allowed depth."""
    return len(call_chain) >= MAX_DEPTH
```

**需要改造为：**
```python
from dataclasses import dataclass

@dataclass
class DepthCheckResult:
    allowed: bool
    current_depth: int
    max_depth: int
    reason: str | None = None

def check_depth(state: AgentState) -> DepthCheckResult:
    call_chain = state.get("call_chain", [])
    current_depth = state.get("current_depth", 0)
    max_depth = int(os.environ.get("AGENT_MAX_DEPTH", "3"))

    # 循环检测
    if len(call_chain) != len(set(call_chain)):
        cycle = _find_cycle(call_chain)
        return DepthCheckResult(
            allowed=False,
            current_depth=current_depth,
            max_depth=max_depth,
            reason=f"Circular call detected: {format_call_chain(cycle)}"
        )

    # 深度超限
    if current_depth >= max_depth:
        return DepthCheckResult(
            allowed=False,
            current_depth=current_depth,
            max_depth=max_depth,
            reason=f"Depth limit exceeded: {current_depth} >= {max_depth}. "
                   f"Call chain: {format_call_chain(call_chain)}"
        )

    return DepthCheckResult(allowed=True, current_depth=current_depth, max_depth=max_depth)
```

**react_executor 集成位置（react_executor.py REACT 循环内）：**
```python
# 在 while iteration < _MAX_ITERATIONS 循环体开头添加
from app.engine.agent.depth_guard import check_depth

depth_result = check_depth(state)
if not depth_result.allowed:
    logger.warning(
        depth_result.reason and "circular" and "circular_call_detected"
        or "depth_limit_exceeded",
        agent_id=state.get("agent_id"),
        current_depth=depth_result.current_depth,
        call_chain=state.get("call_chain", []),
        reason=depth_result.reason,
    )
    return {
        **state,
        "error": depth_result.reason,
        "step_count": state.get("step_count", 0) + 1,
    }
```

**AgentState 扩展（state.py）：**
```python
class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    agent_id: str
    execution_path: str
    request_id: str
    tool_results: dict[str, Any]
    step_count: int
    error: str | None
    call_chain: list[str]       # 新增：有序调用链
    current_depth: int          # 新增：当前嵌套深度
```

### ⚠️ 回归防护

**不能破坏的现有行为：**
1. `react_executor.py` 的 REACT 循环正常执行（25 次上限不变）
2. `direct_executor.py` 和 `planner_executor.py` 的接口签名
3. `builder.py` 的 StateGraph 拓扑（evaluate → react → END）
4. `workflow_executor.py` 的 3 个 stub 工具（search_workflow/create_task/task_query）
5. `context.py` 的上下文压缩功能
6. invoke/stream 端点的现有行为和响应格式

**前端不修改：** 本 Story 纯后端，不涉及前端变更。

### 📁 文件清单

**后端修改的文件：**
- `backend/app/engine/state.py` — AgentState 添加 call_chain/current_depth
- `backend/app/engine/agent/depth_guard.py` — 完善深度保护逻辑
- `backend/app/engine/agent/evaluator.py` — 初始化深度追踪字段
- `backend/app/engine/agent/react_executor.py` — 集成深度检查
- `backend/app/api/v1/agents.py` — invoke/stream 传递调用链

**后端新建的文件：**
- `backend/tests/engine/test_depth_guard.py` — 深度保护单元测试

**不修改的文件：**
- `backend/app/engine/agent/builder.py` — 图拓扑不变
- `backend/app/engine/agent/direct_executor.py` — 不涉及
- `backend/app/engine/agent/planner_executor.py` — 不涉及
- `backend/app/engine/agent/workflow_executor.py` — stub 工具不变
- `backend/app/engine/agent/context.py` — 上下文压缩不变

### 🚫 本 Story 不做的事

- **不做 Workflow → Agent 嵌套保护** — Workflow 执行引擎未实现，无实际嵌套场景
- **不做深度保护的前端 UI** — 纯后端 Story
- **不做动态调整 MAX_DEPTH** — MVP 用环境变量配置即可
- **不做深度保护的 REST API 暴露** — 内部保护机制，无外部 API

### Project Structure Notes

- 后端 `backend/app/engine/` 是执行引擎层，包含 agent/ 子目录
- `depth_guard.py` 已存在于 `agent/` 子目录，直接修改即可
- 测试文件放在 `backend/tests/engine/`（与 `tests/api/` 同级）
- 如果 `tests/engine/` 目录不存在，需创建

### References

- [Source: docs/planning-artifacts/epics.md#Story 5.5] — 调用深度与循环保护需求
- [Source: docs/planning-artifacts/prd.md#FR-8] — 调用深度与循环保护 FR
- [Source: backend/app/engine/agent/depth_guard.py] — 现有骨架代码
- [Source: backend/app/engine/state.py] — AgentState TypedDict 定义
- [Source: backend/app/engine/agent/evaluator.py] — evaluate_input 函数
- [Source: backend/app/engine/agent/react_executor.py:42-120] — REACT 循环主逻辑
- [Source: backend/app/engine/agent/builder.py:15-60] — StateGraph 构建和工具注入
- [Source: backend/app/api/v1/agents.py:271-385] — invoke/stream 端点

## Dev Agent Record

### Agent Model Used

GLM-5 (via Claude Code)

### Debug Log References

- 全量回归测试 315 passed, 0 failed (2026-06-10)
- depth_guard 专项测试 30 passed (2026-06-10)

### Completion Notes List

- ✅ T1: AgentState 已包含 `call_chain: list[str]` 和 `current_depth: int` 字段（state.py）
- ✅ T2: depth_guard 模块完善 — `DepthCheckResult` dataclass、`check_depth()`、`detect_cycle()`、`format_call_chain()`、环境变量 `AGENT_MAX_DEPTH` 支持
- ✅ T3: evaluator 集成 — `evaluate_input()` 初始化 `call_chain=[agent_id]`、`current_depth=0`
- ✅ T4: react_executor 集成 — 每轮 REACT 迭代前调用 `check_depth(state)`，超限时设置 error 并记录日志
- ✅ T5: invoke/stream 端点 — initial_state 包含 call_chain/current_depth，支持 `X-Call-Chain` 请求头
- ✅ T6: 30 个单元测试全部通过，覆盖深度检查、循环检测、格式化、环境变量、边界条件

### File List

**修改的文件：**
- `backend/app/engine/state.py` — AgentState 添加 call_chain / current_depth 字段
- `backend/app/engine/agent/depth_guard.py` — 完善深度保护逻辑（dataclass + check + cycle detect）
- `backend/app/engine/agent/evaluator.py` — evaluate_input 初始化深度追踪字段
- `backend/app/engine/agent/react_executor.py` — REACT 循环集成深度检查
- `backend/app/api/v1/agents.py` — invoke/stream 端点传递调用链 + X-Call-Chain header

**新建的文件：**
- `backend/tests/engine/test_depth_guard.py` — 深度保护单元测试（30 个用例）

## Change Log

- 2026-06-10: Story 3-6 创建 — 调用深度与循环保护
- 2026-06-10: Story 3-6 实现完成 — T1~T6 全部完成，315 测试通过零回归

## Status

**Status:** review
