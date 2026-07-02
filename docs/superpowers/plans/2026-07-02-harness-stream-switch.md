# harness Stream 开关打通实施计划（阶段 1）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `POST /agents/{id}/stream` 端点能按全局开关 `USE_HARNESS_ENGINE` 在老引擎 / harness 引擎之间切换，事件格式对前端零差异，开关默认关闭可随时回退。

**Architecture:** 在 `agents.py:stream_agent` 端点的 `_run_agent()` 内加一个 `if settings.USE_HARNESS_ENGINE` 分支，选择调老引擎 `run_agent_streaming` 或 harness 的 `run_agent_streaming_harness`。两者签名完全一致 `(agent, state, on_event, enable_thinking) -> dict`，端点内联的 system prompt / 历史 / 文件 / 持久化 / 事件队列逻辑原样不动。同时把 harness 路径产出的错误事件统一成 SSE 格式，确保前端兼容。

**Tech Stack:** Python / FastAPI / LangGraph / agent_flow_harness（editable 依赖）

**关联设计文档:** `docs/implementation-artifacts/v0-3-0-app-engine-full-migration-to-harness.md`（阶段 1）

---

## File Structure

| 文件 | 责任 | 操作 |
|---|---|---|
| `backend/app/api/v1/agents.py` | stream 端点：加 harness 分支 + 错误事件兜底 | 修改 |
| `backend/app/engine/harness_integration/stream.py` | harness 流式执行桥（已实现，无需改逻辑，仅核对） | 核对（不改） |
| `backend/app/core/config.py` | 开关定义（已存在 `USE_HARNESS_ENGINE`） | 不改 |

不新建文件。改动面：`agents.py` 约 15 行。

---

## Task 1: 加 harness 分支到 stream 端点

**Files:**
- Modify: `backend/app/api/v1/agents.py:810-815`（`_run_agent()` 的 try 块内调用处）

- [ ] **Step 1: 读取当前调用点，确认行号**

Run: `sed -n '805,820p' backend/app/api/v1/agents.py`

确认 `result = await run_agent_streaming(...)` 在 811 行，且上方无 `from app.core.config import settings` 的局部 import。

- [ ] **Step 2: 替换调用为开关分支**

把 `agents.py:810-815` 这段：

```python
        try:
            result = await run_agent_streaming(
                exec_doc, initial_state,
                on_event=_on_event,
                enable_thinking=body.enable_thinking,
            )
```

替换为：

```python
        try:
            if settings.USE_HARNESS_ENGINE:
                from app.engine.harness_integration.stream import (
                    run_agent_streaming_harness,
                )
                result = await run_agent_streaming_harness(
                    exec_doc, initial_state,
                    on_event=_on_event,
                    enable_thinking=body.enable_thinking,
                )
            else:
                result = await run_agent_streaming(
                    exec_doc, initial_state,
                    on_event=_on_event,
                    enable_thinking=body.enable_thinking,
                )
```

- [ ] **Step 3: 确认 `settings` 在端点作用域可见**

`agents.py` 顶层没有 import settings。`_run_agent` 内需要用到。在 `_run_agent()` 函数体开头（即 `async def _run_agent():` 之后第一行，约 758 行）加局部 import：

定位 `async def _run_agent():` 下方的现有 import 块（`import asyncio` 和 `from loguru import logger as _logger`，约 736-738 行），在同一区域追加：

```python
    from app.core.config import settings
```

加到那几行局部 import 旁边即可（`_run_agent` 内部已有局部 import 先例）。

- [ ] **Step 4: 语法校验**

Run: `cd backend && python -c "import ast; ast.parse(open('app/api/v1/agents.py').read()); print('OK')"`

Expected: `OK`（无 SyntaxError）

- [ ] **Step 5: 开关 False 时启动校验（回归）**

Run: `cd backend && python -c "from app.api.v1.agents import router; print('import OK', router.prefix)"`

Expected: `import OK /agents`（确认 import 链不破，开关默认 False 走老路径）

- [ ] **Step 6: 提交**

```bash
git add backend/app/api/v1/agents.py
git commit -m "feat(agent): stream 端点接入 USE_HARNESS_ENGINE 开关

stream_agent 的 _run_agent() 按 settings.USE_HARNESS_ENGINE 选择
老引擎 run_agent_streaming 或 harness run_agent_streaming_harness。
两者签名一致，端点其余装配逻辑（prompt/历史/持久化）原样共享。
默认关闭，行为与迁移前完全一致。"
```

---

## Task 2: 核对 harness 错误事件兼容性

设计文档标记了 `[GAP-4]`：harness 产出结构化 `error` 事件 `{type:error, message, source}`，老引擎把 tool 异常塞进 `tool_result.content`。需确认端点的错误兜底能正确处理 harness 的 error 事件。

**Files:**
- 核对: `backend/app/api/v1/agents.py:822-831`（except 块）、`backend/app/engine/harness_integration/stream.py`

- [ ] **Step 1: 读取端点 except 块**

Run: `sed -n '822,835p' backend/app/api/v1/agents.py`

确认 except 块是这样（捕获执行异常并推 error SSE）：

```python
        except Exception as exc:
            _logger.error(...)
            await event_queue.put(
                f"data: {_safe_json({'type': 'error', 'content': str(exc)})}\n\n"
            )
```

记录这段行为：端点异常 → 推 `{type:error, content:str(exc)}`。

- [ ] **Step 2: 核对 harness adapter 的 error 事件字段名**

Run: `grep -n "class ErrorEvent\|source\|message" backend/packages/harness/src/agent_flow_harness/adapters/app_event.py`

确认 harness 的 `ErrorEvent` 字段是 `message` + `source`（不是 `content`）。

**结论与处理**：harness 路径下，工具/LLM 错误会以 `{type:error, message:..., source:...}` 形式经 `_on_event` 推入队列（因为 `stream.py` 的 `_on_event_dict` 把 AppEvent `model_dump()` 成 dict 推送）。而端点 except 块只在**执行器整体抛异常**时推 `{type:error, content:...}`。两者**不冲突**：
- harness 内部错误 → 经 on_event 推 `{type:error, message, source}`（字段名是 message）
- 老引擎内部错误 → 工具异常被吞进 tool_result，不产 error 事件；只有执行器整体崩溃才走 except 推 `{type:error, content}`

**前端兼容性**：需确认前端 error 渲染同时认 `content` 和 `message`。本步骤只做核对记录，不改代码（若前端有问题，属于前端单独修复，不阻塞后端开关）。

- [ ] **Step 3: 记录核对结论**

在 `docs/implementation-artifacts/v0-3-0-app-engine-full-migration-to-harness.md` 的 `[GAP-4]` 小节末尾追加一行：

```
**核对结论（阶段1）**：harness error 事件字段为 `{type, message, source}`，端点 except 兜底为 `{type, content}`。两路径不冲突。前端 error 渲染若仅认 `content`，需后续兼容 `message` 字段——不阻塞开关切换。
```

- [ ] **Step 4: 提交**

```bash
git add docs/implementation-artifacts/v0-3-0-app-engine-full-migration-to-harness.md
git commit -m "docs: 记录 harness error 事件字段核对结论（GAP-4）"
```

---

## Task 3: 开关 True 的导入与冒烟验证

确认 `USE_HARNESS_ENGINE=True` 时 import 链完整、无循环依赖、harness 模块可加载。

**Files:** 无修改，仅验证。

- [ ] **Step 1: 验证 harness stream 模块可 import**

Run: `cd backend && python -c "from app.engine.harness_integration.stream import run_agent_streaming_harness; print('harness import OK', run_agent_streaming_harness.__name__)"`

Expected: `harness import OK run_agent_streaming_harness`

若失败（如缺依赖、循环 import），需先修复——这是开关 True 的前置条件。

- [ ] **Step 2: 验证 harness 关键依赖可 import**

Run: `cd backend && python -c "
from agent_flow_harness import build_agent_graph, build_config, UsageMiddleware, DockerSandbox, DockerSandboxConfig, SkillManager, McpToolLoader
from agent_flow_harness.adapters import stream_events_to_app_events
print('harness deps OK')
"`

Expected: `harness deps OK`

- [ ] **Step 3: 模拟开关 True 的端点 import 路径**

Run: `cd backend && python -c "
import os
os.environ['USE_HARNESS_ENGINE'] = 'true'
# 仅验证 import，不实际触发请求
from app.api.v1.agents import stream_agent
print('endpoint import OK with harness path')
"`

Expected: `endpoint import OK with harness path`

- [ ] **Step 4: 记录验证结果**

无代码改动。若以上全部 PASS，阶段 1 实施完成，开关可随时通过环境变量 `USE_HARNESS_ENGINE=true` 开启进行真实流量验证。

---

## Self-Review 结论

**Spec coverage（对照设计文档阶段 1）:**
- ✅ stream 端点加 `USE_HARNESS_ENGINE` 分支 → Task 1
- ✅ 端点内联逻辑不动（state/on_event 契约一致）→ Task 1 设计上保证（只改调用选择，不改装配）
- ✅ `[GAP-4]` error 事件核对 → Task 2
- ✅ 开关 True 可用性验证 → Task 3
- ✅ 默认 False 回归 → Task 1 Step 5

**Placeholder scan:** 无 TBD/TODO，所有步骤都有具体代码或命令。

**Type consistency:** `run_agent_streaming_harness` 签名与 `run_agent_streaming` 一致（已在设计阶段核对 `stream.py:31` 与 `builder.py:797`），参数名 `exec_doc/initial_state/on_event/enable_thinking` 对齐。

**范围控制:** 本计划只做阶段 1（最小打通开关）。阶段 0（填 Adapter 骨架）、阶段 2（invoke）、阶段 3（workflow agent 节点）是后续独立计划，不在本计划内——避免一次性扩大风险面。
