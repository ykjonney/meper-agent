# Agent 后台任务执行链路 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Task 支持 workflow / agent 双执行目标——创建任务时可选已发布 Agent，经 Celery 后台跑 REACT 循环，任务看板完整管理。

**Architecture:** 单 Celery 入口分流（`run_workflow_task` 内按 `task.agent_id` 分流到新 AgentTaskRunner）；Runner 复用 `AgentExecutionService.invoke` 跑独立会话，状态机/调度扫描/取消/并发限制全部复用现有基建；Session 加 `task_id` 字段实现会话隐藏与任务详情跳转。

**Tech Stack:** FastAPI + Pydantic + Motor(MongoDB) + Celery + LangGraph harness；前端 React 19 + TanStack Query + Tailwind。

**Spec:** `docs/superpowers/specs/2026-11-10-agent-task-design.md`（含两处计划期修订，见 Task 8：取消升级为协作式中断；invoke 用 `execution_context="workflow"`）

## Global Constraints

- 后端包管理：**uv**（测试命令 `uv run pytest ...`，在 `backend/` 目录下）
- Python 3.12+；MongoDB 文档 `_id` 与 Pydantic `id` 别名互转（`populate_by_name=True`）
- 前端目录：`frontend-studio/`；构建检查 `npm run build`
- git commit 风格：`feat(scope): 中文描述`（参照 `git log --oneline -8`）
- 测试风格：`unittest.mock.patch` + `AsyncMock`（参照 `backend/tests/services/test_task_service_create.py`），pytest.mark.asyncio
- 不变量：`workflow_id` 与 `agent_id` **恰好其一非空**
- agent 任务输入约定：`input = {"instruction": "<用户指令文本>"}`
- 文档目录 `docs/` 被 .gitignore 忽略——spec/plan **不提交 git**，代码必须提交

---

### Task 1: 后端数据模型 + Schemas（契约层）

**Files:**
- Modify: `backend/app/models/task.py:100`
- Modify: `backend/app/models/session.py:35`
- Modify: `backend/app/schemas/task.py:14-21`（TaskCreate）、TaskSummary、TaskResponse
- Modify: `backend/app/schemas/execution.py:66-74`（ExecutionResponse）
- Modify: `backend/app/services/session_service.py:48-80`（create_session doc 组装）
- Test: `backend/tests/schemas/test_task_target_schemas.py`（新建）

**Interfaces:**
- Produces: `Task.agent_id: str`（默认 ""）、`Session.task_id: str`（默认 ""）、`TaskCreate.agent_id`、`TaskSummary.agent_id`、`TaskResponse.agent_id`、`ExecutionResponse.total_tokens: int`——后续所有任务依赖这些字段名。

- [ ] **Step 1: 写失败测试**

```python
"""Task 双目标 schema 契约：workflow_id / agent_id 恰好其一 + 字段透传。"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.task import TaskCreate, TaskSummary
from app.schemas.execution import ExecutionResponse


class TestTaskCreateTargetValidation:
    """TaskCreate：workflow_id 与 agent_id 必须恰好提供其一。"""

    def test_both_empty_raises(self) -> None:
        with pytest.raises(ValidationError):
            TaskCreate(workflow_id="", agent_id="", input={})

    def test_both_set_raises(self) -> None:
        with pytest.raises(ValidationError):
            TaskCreate(workflow_id="wf_1", agent_id="agent_1", input={})

    def test_agent_only_ok(self) -> None:
        body = TaskCreate(agent_id="agent_1", input={"instruction": "做调研"})
        assert body.agent_id == "agent_1"
        assert body.workflow_id == ""

    def test_workflow_only_ok(self) -> None:
        body = TaskCreate(workflow_id="wf_1", input={})
        assert body.agent_id == ""


class TestSummaryAndResponseFields:
    """TaskSummary / ExecutionResponse 新字段。"""

    def test_summary_accepts_agent_id(self) -> None:
        from datetime import UTC, datetime
        s = TaskSummary(
            id="task_1", workflow_id="", agent_id="agent_1",
            workflow_version="", status="running", input={},
            created_by="u1", created_by_type="user", version=1,
            total_tokens=0, created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
        )
        assert s.agent_id == "agent_1"

    def test_execution_response_total_tokens(self) -> None:
        r = ExecutionResponse(
            output="done", execution_path="react", request_id="r1",
            agent_id="agent_1", session_id="s1", total_tokens=123,
        )
        assert r.total_tokens == 123
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/schemas/test_task_target_schemas.py -v`
Expected: FAIL（`agent_id` 字段不存在 / 互斥校验不存在）

- [ ] **Step 3: 最小实现**

`backend/app/schemas/task.py` — TaskCreate 改为：

```python
class TaskCreate(BaseModel):
    """Request body for creating a new Task.

    双目标：workflow_id / agent_id 恰好其一非空（agent 任务 input 携带
    {"instruction": ...}，由 service 层校验）。
    """

    workflow_id: str = Field(default="", max_length=100)
    agent_id: str = Field(default="", max_length=100)
    input: dict[str, Any] = Field(default_factory=dict)
    scheduled_at: datetime | None = None
    # 工作流级 token 预算（0=不限制）：跨节点累计检查，超限任务诚实终止
    token_budget: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _require_exactly_one_target(self) -> TaskCreate:
        if bool(self.workflow_id) == bool(self.agent_id):
            raise ValueError("workflow_id 与 agent_id 必须恰好提供其一")
        return self
```

（文件头 import 加 `model_validator`：`from pydantic import BaseModel, Field, model_validator`）

TaskSummary / TaskResponse 各加一行字段（与 workflow_id 同区域）：

```python
    agent_id: str = ""
```

`backend/app/api/v1/tasks.py` — `_doc_to_full_response`（54-78 行）与 `_doc_to_summary`（81-102 行）在 `workflow_id=` 行后各加：

```python
        agent_id=doc.get("agent_id", ""),
```

`backend/app/schemas/execution.py` — ExecutionResponse 加：

```python
    total_tokens: int = Field(default=0, description="本轮请求 token 增量（后台任务 Runner 写回 task.total_tokens 用）")
```

`backend/app/models/task.py` — Task 模型 100 行 workflow_id 改默认空、紧跟其后加 agent_id：

```python
    # 双目标：workflow_id / agent_id 恰好其一非空（schema 层校验）。
    workflow_id: str = Field(default="", max_length=100)
    agent_id: str = Field(default="", max_length=100)
```

`backend/app/models/session.py` — Session 模型 updated_at 前加：

```python
    # 非空 = 任务自动创建的会话：会话列表隐藏（list_sessions 过滤），
    # 任务详情「查看执行过程」经 session_id 直达。
    task_id: str = Field(default="", max_length=100)
```

`backend/app/services/session_service.py` — create_session 的 doc dict 组装（68-73 行）加一项：

```python
            "task_id": session.task_id,
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/schemas/test_task_target_schemas.py -v`
Expected: 全部 PASS

- [ ] **Step 5: 回归既有测试 + 提交**

Run: `cd backend && uv run pytest tests/schemas/ tests/services/test_task_service_create.py tests/api/test_tasks_create.py -q`
Expected: PASS（既有测试不受影响——workflow_id 默认空但创建路径都显式传）

```bash
git add backend/app/models/task.py backend/app/models/session.py backend/app/schemas/task.py backend/app/schemas/execution.py backend/app/api/v1/tasks.py backend/app/services/session_service.py backend/tests/schemas/test_task_target_schemas.py
git commit -m "feat(task): Task/Session 双目标契约——agent_id + session.task_id + schema 互斥校验"
```

---

### Task 2: TaskService.create_task agent 分支 + API 透传

**Files:**
- Modify: `backend/app/services/task_service.py:112-246`（create_task）
- Modify: `backend/app/api/v1/tasks.py:108-139`（create_task 端点）
- Test: `backend/tests/services/test_task_service_create.py`（追加）

**Interfaces:**
- Consumes: Task 1 的 `TaskCreate.agent_id`
- Produces: `TaskService.create_task(..., agent_id: str = "")`——agent 模式校验 published + instruction 非空；抛 `ValidationError(code="AGENT_NOT_FOUND"|"AGENT_NOT_PUBLISHED"|"TASK_MISSING_INSTRUCTION"|"TASK_TARGET_REQUIRED")`。

- [ ] **Step 1: 写失败测试** — 追加到 `backend/tests/services/test_task_service_create.py` 末尾：

```python
class TestCreateTaskAgentTarget:
    """create_task agent 分支：published 校验 + instruction 必填 + 互斥。"""

    @pytest.mark.asyncio
    async def test_both_targets_raises(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            await TaskService.create_task(workflow_id="wf_1", agent_id="agent_1", input_data={})
        assert exc_info.value.code == "TASK_TARGET_REQUIRED"

    @pytest.mark.asyncio
    async def test_agent_not_found_raises(self) -> None:
        mock_agents = MagicMock()
        mock_agents.find_one = AsyncMock(return_value=None)
        mock_db = MagicMock()
        mock_db.__getitem__ = MagicMock(return_value=mock_agents)

        with patch("app.services.task_service.get_database", return_value=mock_db):
            with pytest.raises(ValidationError) as exc_info:
                await TaskService.create_task(
                    workflow_id="", agent_id="agent_x",
                    input_data={"instruction": "做"},
                )
        assert exc_info.value.code == "AGENT_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_agent_not_published_raises(self) -> None:
        mock_agents = MagicMock()
        mock_agents.find_one = AsyncMock(return_value={"_id": "agent_1", "status": "draft"})
        mock_db = MagicMock()
        mock_db.__getitem__ = MagicMock(return_value=mock_agents)

        with patch("app.services.task_service.get_database", return_value=mock_db):
            with pytest.raises(ValidationError) as exc_info:
                await TaskService.create_task(
                    workflow_id="", agent_id="agent_1",
                    input_data={"instruction": "做"},
                )
        assert exc_info.value.code == "AGENT_NOT_PUBLISHED"

    @pytest.mark.asyncio
    async def test_missing_instruction_raises(self) -> None:
        mock_agents = MagicMock()
        mock_agents.find_one = AsyncMock(return_value={"_id": "agent_1", "status": "published"})
        mock_db = MagicMock()
        mock_db.__getitem__ = MagicMock(return_value=mock_agents)

        with patch("app.services.task_service.get_database", return_value=mock_db):
            with pytest.raises(ValidationError) as exc_info:
                await TaskService.create_task(
                    workflow_id="", agent_id="agent_1", input_data={},
                )
        assert exc_info.value.code == "TASK_MISSING_INSTRUCTION"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/services/test_task_service_create.py::TestCreateTaskAgentTarget -v`
Expected: FAIL（TASK_TARGET_REQUIRED 等分支不存在）

- [ ] **Step 3: 实现** — `create_task` 签名加 `agent_id: str = ""` 参数（`token_budget: int = 0` 之后），方法体开头 workflow_id 空校验（153-157 行）替换为：

```python
        if bool(workflow_id) == bool(agent_id):
            raise ValidationError(
                code="TASK_TARGET_REQUIRED",
                message="workflow_id 与 agent_id 必须恰好提供其一",
            )
        if agent_id:
            # agent 目标：must published + instruction 非空（fail fast，
            # 与下方 workflow 模板存在性校验同一目的——不产生僵尸 task）。
            agent_doc = await db["agents"].find_one({"_id": agent_id}, {"status": 1})
            if agent_doc is None:
                raise ValidationError(
                    code="AGENT_NOT_FOUND",
                    message=f"Agent {agent_id} 不存在",
                )
            if agent_doc.get("status") != "published":
                raise ValidationError(
                    code="AGENT_NOT_PUBLISHED",
                    message="只能委派已发布的 Agent 执行后台任务",
                )
            if not (input_data.get("instruction") or "").strip():
                raise ValidationError(
                    code="TASK_MISSING_INSTRUCTION",
                    message="agent 任务必须提供非空 instruction 指令",
                )
        else:
            if not workflow_id:
                raise ValidationError(
                    code="TASK_MISSING_WORKFLOW_ID",
                    message="workflow_id 不能为空",
                )
```

注意：`db = get_database()` 在 162 行才赋值——把上面 agent 校验块移到 162 行之后、workflow 存在性校验之前，workflow 存在性校验包进 `else:`（agent 分支跳过）。Task 文档构造处（搜 `Task(`，约 200 行附近）加 `agent_id=agent_id,`。`logger.debug("task_create_start", ...)` 加 `agent_id=agent_id,`。

API 端点 `backend/app/api/v1/tasks.py` create_task（114-139 行）改为：

```python
    # agent 目标跳过 workflow input_schema 校验（instruction 文本非变量表单）
    if not body.agent_id:
        wf_doc = await WorkflowService.get(body.workflow_id)
        if wf_doc is not None:
            input_schema = extract_input_schema(wf_doc.get("nodes", []))
            if input_schema:
                validate_workflow_input(body.input, input_schema)

    doc = await TaskService.create_task(
        workflow_id=body.workflow_id,
        agent_id=body.agent_id,
        input_data=body.input,
        created_by=current_user.id,
        created_by_type="user",
        scheduled_at=body.scheduled_at,
        token_budget=body.token_budget,
    )
    return _doc_to_full_response(doc)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/services/test_task_service_create.py tests/api/test_tasks_create.py -v`
Expected: 全部 PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/services/task_service.py backend/app/api/v1/tasks.py backend/tests/services/test_task_service_create.py
git commit -m "feat(task): create_task 支持 agent 目标——published 校验 + instruction 必填"
```

---

### Task 3: AgentExecutionService.invoke 增强（execution_context / cancel_checker / total_tokens）

**Files:**
- Modify: `backend/app/services/agent_execution_service.py:61-180`（invoke）
- Test: `backend/tests/services/test_agent_invoke_task_mode.py`（新建）

**Interfaces:**
- Consumes: Task 1 的 `ExecutionResponse.total_tokens`
- Produces: `AgentExecutionService.invoke(agent_id, body, user_id, *, external_call_chain=None, user_token=None, execution_context: str | None = None, cancel_checker=None)`——`execution_context=None` 回退 "chat"（现有调用零影响）；`cancel_checker` 透传 `harness_invoke`；ExecutionResponse 填 `total_tokens`。Task 4 依赖这三个契约。

- [ ] **Step 1: 写失败测试**

```python
"""invoke 任务模式增强：execution_context/cancel_checker 透传 + total_tokens 出参。"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.schemas.agent import ExecutionRequest
from app.schemas.execution import ExecutionResponse
from app.services.agent_execution_service import AgentExecutionService


@pytest.mark.asyncio
async def test_invoke_passes_workflow_context_and_checker() -> None:
    """execution_context="workflow" + cancel_checker 应透传 harness_invoke。"""
    captured: dict = {}

    async def fake_harness_invoke(exec_doc, initial_state, **kwargs):
        captured.update(kwargs)
        return {
            "messages": [], "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            "execution_path": "react", "step_count": 2,
        }

    async def fake_resolve(agent_id, body, user_id):
        return "session_new"

    async def fake_system_prompt(exec_doc, user_id, **kwargs):
        return "sys"

    with (
        patch("app.services.agent_service.AgentService.get_agent", new=AsyncMock(return_value={"_id": "agent_1"})),
        patch("app.services.agent_execution_service._resolve_session", new=fake_resolve),
        patch("app.services.agent_execution_service._load_chat_subagents", new=AsyncMock(return_value=([], []))),
        patch("app.services.agent_execution_service._build_system_prompt_checked", new=fake_system_prompt),
        patch("app.services.agent_execution_service._build_user_content", new=AsyncMock(return_value="hi")),
        patch("app.services.agent_execution_service._assemble_messages", new=lambda *a: []),
        patch("app.services.agent_execution_service._load_legacy_records", new=AsyncMock(return_value=[])),
        patch("app.services.session_service.SessionService.get_session", new=AsyncMock(return_value={"total_tokens": 0})),
        patch("app.services.agent_execution_service.harness_invoke", new=fake_harness_invoke),
        patch("app.services.agent_execution_service._record_execution_log", new=AsyncMock()),
        patch("app.services.agent_execution_service.messages_to_timeline_entries", new=lambda *a, **k: []),
        patch("app.services.agent_execution_service._should_persist_messages", new=lambda uid: False),
    ):
        checker = lambda: False  # noqa: E731
        resp = await AgentExecutionService.invoke(
            "agent_1", ExecutionRequest(input="hi"), "user_1",
            execution_context="workflow", cancel_checker=checker,
        )

    assert captured.get("execution_context") == "workflow"
    assert captured.get("cancel_checker") is checker
    assert isinstance(resp, ExecutionResponse)
    assert resp.total_tokens == 15
```

（若 `ExecutionRequest` import 路径不是 `app.schemas.agent`，按 `app/schemas/execution.py` 实际位置调整——Task 执行者先 `grep -rn "class ExecutionRequest" backend/app/schemas/` 确认。）

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/services/test_agent_invoke_task_mode.py -v`
Expected: FAIL（invoke 无 execution_context 参数）

- [ ] **Step 3: 实现** — invoke 签名（62-69 行）加两个关键字参数：

```python
    async def invoke(
        agent_id: str,
        body: ExecutionRequest,
        user_id: str,
        *,
        external_call_chain: list[str] | None = None,
        user_token: str | None = None,
        # 后台任务用 "workflow"：无人值守语义（剥离交互工具，注入 abort_workflow）。
        # None 回退 "chat"，现有调用方零影响。
        execution_context: str | None = None,
        # 协作式取消检查器（每轮 REACT 迭代边界调用，True=取消挂起）。
        cancel_checker=None,
    ) -> ExecutionResponse:
```

exec_ctx 行（82 行）改为：

```python
        exec_ctx = "plan" if getattr(body, "plan_mode", False) else (execution_context or "chat")
```

harness_invoke 调用（117-126 行）参数列表加两项：

```python
                cancel_checker=cancel_checker,
```

（execution_context 已传 `exec_ctx`，透传即生效。）

返回值（173-180 行）加：

```python
            total_tokens=(request_usage or {}).get("total_tokens", 0),
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/services/test_agent_invoke_task_mode.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/services/agent_execution_service.py backend/tests/services/test_agent_invoke_task_mode.py
git commit -m "feat(agent): invoke 支持 execution_context/cancel_checker 透传与 total_tokens 出参"
```

---

### Task 4: Celery 入口分流 + AgentTaskRunner

**Files:**
- Modify: `backend/app/workers/tasks/workflow_execution.py:42-81`
- Create: `backend/app/workers/tasks/agent_task_runner.py`
- Modify: `backend/app/services/task_service.py`（新增 `update_task_output` 静态方法，放 `add_total_tokens` 附近）
- Test: `backend/tests/workers/test_agent_task_runner.py`（新建）

**Interfaces:**
- Consumes: Task 2 的 `TaskService.create_task(agent_id=...)`、Task 3 的 `invoke(execution_context=..., cancel_checker=...)` 与 `ExecutionResponse.total_tokens`
- Produces: `agent_task_runner.run_agent_async(task_id: str) -> dict`（Celery worker 唯一 agent 入口）；`TaskService.update_task_output(task_id: str, output: dict) -> None`

- [ ] **Step 1: 写失败测试**

```python
"""AgentTaskRunner 状态流转：成功/失败/取消守卫/入口分流。"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.workers.tasks.agent_task_runner import run_agent_async


def _task_doc(**over):
    doc = {
        "_id": "task_1", "agent_id": "agent_1", "status": "pending",
        "input": {"instruction": "做调研"}, "created_by": "user_1",
    }
    doc.update(over)
    return doc


@pytest.mark.asyncio
async def test_success_writes_output_and_completes() -> None:
    resp = MagicMock(output="结果", session_id="session_9", step_count=3, total_tokens=77)
    transition_calls: list = []

    async def fake_transition(task_id, to_status, **kw):
        transition_calls.append(to_status)
        return {"_id": task_id, "status": to_status}

    with (
        patch("app.services.task_service.TaskService.get_task", new=AsyncMock(side_effect=[_task_doc(), _task_doc(status="running"), _task_doc(status="running")])),
        patch("app.services.task_service.TaskService.transition_task", new=fake_transition),
        patch("app.services.task_service.TaskService.update_task_output", new=AsyncMock()) as upd,
        patch("app.services.task_service.TaskService.add_total_tokens", new=AsyncMock()) as tok,
        patch("app.services.session_service.SessionService.update_session", new=AsyncMock()) as sess,
        patch("app.services.agent_execution_service.AgentExecutionService.invoke", new=AsyncMock(return_value=resp)),
    ):
        result = await run_agent_async("task_1")

    assert result["status"] == "success"
    # output 含最终答案 + 会话关联
    out_arg = upd.call_args.args[1]
    assert out_arg["output"] == "结果"
    assert out_arg["session_id"] == "session_9"
    sess.assert_awaited_once_with("session_9", {"task_id": "task_1"})
    tok.assert_awaited_once_with("task_1", 77)
    assert transition_calls == ["running", "completed"]


@pytest.mark.asyncio
async def test_invoke_error_marks_failed() -> None:
    async def fake_transition(task_id, to_status, **kw):
        assert kw.get("error_info"), "failed 转换必须携带 error_info"
        return {"_id": task_id}

    with (
        patch("app.services.task_service.TaskService.get_task", new=AsyncMock(side_effect=[_task_doc(), _task_doc(status="running")])),
        patch("app.services.task_service.TaskService.transition_task", new=fake_transition),
        patch("app.services.agent_execution_service.AgentExecutionService.invoke", new=AsyncMock(side_effect=RuntimeError("boom"))),
    ):
        result = await run_agent_async("task_1")

    assert result["status"] == "error"


@pytest.mark.asyncio
async def test_cancelled_result_discarded() -> None:
    """回写前发现已 cancelled → 丢弃结果、不再转换状态。"""
    resp = MagicMock(output="x", session_id="s", step_count=1, total_tokens=1)
    with (
        patch("app.services.task_service.TaskService.get_task", new=AsyncMock(side_effect=[_task_doc(), _task_doc(status="running"), _task_doc(status="cancelled")])),
        patch("app.services.task_service.TaskService.transition_task", new=AsyncMock()) as tr,
        patch("app.services.task_service.TaskService.update_task_output", new=AsyncMock()) as upd,
        patch("app.services.session_service.SessionService.update_session", new=AsyncMock()),
        patch("app.services.agent_execution_service.AgentExecutionService.invoke", new=AsyncMock(return_value=resp)),
    ):
        result = await run_agent_async("task_1")

    assert result["status"] == "cancelled"
    tr.assert_not_awaited()
    upd.assert_not_awaited()


@pytest.mark.asyncio
async def test_concurrency_conflict_leaves_pending() -> None:
    """pending→running 撞并发上限 → 任务保持 pending 等待 FIFO/下轮扫描。

    用 Exception 规避 ConflictError 构造签名猜测——runner 捕获所有异常
    转 skipped，语义覆盖并发冲突。
    """
    with (
        patch("app.services.task_service.TaskService.get_task", new=AsyncMock(return_value=_task_doc())),
        patch("app.services.task_service.TaskService.transition_task", new=AsyncMock(side_effect=Exception("并发已满"))),
    ):
        result = await run_agent_async("task_1")

    assert result["status"] == "skipped"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/workers/test_agent_task_runner.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现** — 新建 `backend/app/workers/tasks/agent_task_runner.py`：

```python
"""Agent 目标 Task 的后台执行器（Celery worker 侧）。

与 WorkflowEngine.run_and_persist 平行的 agent 执行路径：
- 状态机转换 / 并发限制 / FIFO 调度：复用 TaskService.transition_task
- REACT 循环：复用 AgentExecutionService.invoke（execution_context="workflow"
  ——无人值守语义，剥离交互工具，后台任务不会挂起等人）
- 协作式取消：cancel_checker 每轮 REACT 边界查 task DB status（Redis flag
  方案是 API 进程 request_id 维度，这里以 DB 状态为准更直接，revoke 仍兜底）
- 结果回写守卫：回写前复查 status，已 cancelled 则丢弃（用户取消先于完成）
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from loguru import logger

from app.models.task import TaskStatus
from app.schemas.execution import ExecutionRequest
from app.services.agent_execution_service import AgentExecutionService
from app.services.session_service import SessionService
from app.services.task_service import TaskService


async def run_agent_async(task_id: str) -> dict[str, Any]:
    """Execute an agent-target Task: running → invoke → completed/failed.

    Returns a Celery result summary dict (status: success/error/skipped/cancelled).
    """
    task_doc = await TaskService.get_task(task_id)
    if task_doc is None:
        logger.warning("agent_task_not_found", task_id=task_id)
        return {"status": "skipped", "task_id": task_id, "message": "task not found"}

    agent_id = task_doc.get("agent_id", "")
    instruction = (task_doc.get("input") or {}).get("instruction", "")

    async def _cancel_checker() -> bool:
        fresh = await TaskService.get_task(task_id)
        return bool(fresh) and fresh.get("status") == TaskStatus.CANCELLED.value

    try:
        await TaskService.transition_task(
            task_id, TaskStatus.RUNNING, timeline_event_type="started",
        )
    except Exception as exc:  # 并发满等 ConflictError——保持 pending 等下轮
        logger.warning("agent_task_start_deferred", task_id=task_id, error=str(exc))
        return {"status": "skipped", "task_id": task_id, "message": str(exc)}
    # started_at 与 workflow 引擎同语义（慢任务警告扫描时间基准）
    await TaskService.update_task_output(
        task_id, {}, extra={"started_at": datetime.now(UTC).isoformat()},
    )

    try:
        resp = await AgentExecutionService.invoke(
            agent_id,
            ExecutionRequest(input=instruction),
            task_doc.get("created_by", ""),
            execution_context="workflow",
            cancel_checker=_cancel_checker,
        )
    except Exception as exc:
        logger.error("agent_task_failed", task_id=task_id, error=str(exc))
        await TaskService.transition_task(
            task_id, TaskStatus.FAILED,
            error_info={"error_message": str(exc)[:2000], "error_code": "AGENT_INVOKE_ERROR"},
        )
        return {"status": "error", "task_id": task_id, "message": str(exc)}

    # 回写守卫：取消先于完成 → 丢弃结果，保持 cancelled
    fresh = await TaskService.get_task(task_id)
    if fresh is None or fresh.get("status") == TaskStatus.CANCELLED.value:
        logger.info("agent_task_result_discarded", task_id=task_id)
        return {"status": "cancelled", "task_id": task_id}

    await SessionService.update_session(resp.session_id, {"task_id": task_id})
    await TaskService.update_task_output(task_id, {
        "output": resp.output,
        "session_id": resp.session_id,
        "step_count": resp.step_count,
        "agent_id": agent_id,
    })
    if resp.total_tokens:
        await TaskService.add_total_tokens(task_id, resp.total_tokens)
    await TaskService.transition_task(task_id, TaskStatus.COMPLETED)
    logger.info("agent_task_completed", task_id=task_id, session_id=resp.session_id)
    return {"status": "success", "task_id": task_id}
```

`backend/app/services/task_service.py` — `add_total_tokens`（304 行附近）后新增：

```python
    @staticmethod
    async def update_task_output(task_id: str, output: dict[str, Any], *, extra: dict[str, Any] | None = None) -> None:
        """Write task.output (merged) plus optional extra top-level fields.

        Agent 任务 Runner 专用（workflow 引擎自行写 collection）。output 为
        {} 时只写 extra（如 started_at）。
        """
        set_fields: dict[str, Any] = {"updated_at": utc_now()}
        if output:
            set_fields["output"] = output
        if extra:
            set_fields.update(extra)
        await TaskService._collection().update_one({"_id": task_id}, {"$set": set_fields})
```

（`utc_now` 已在文件头 import；若与现有 output 写回语义冲突，执行者对照 engine 的写法微调。）

`backend/app/workers/tasks/workflow_execution.py` — `_run_async`（58 行）开头加分流：

```python
    try:
        # 双目标分流：agent_id 非空 → AgentTaskRunner（同一状态机/调度/取消基建）
        from app.services.task_service import TaskService

        task_doc = await TaskService.get_task(task_id)
        if task_doc and task_doc.get("agent_id"):
            from app.workers.tasks.agent_task_runner import run_agent_async

            return await run_agent_async(task_id)

        engine = WorkflowEngine()
        result = await engine.run_and_persist(task_id)
        # ……（以下现有逻辑不动）
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/workers/test_agent_task_runner.py tests/workers/ -v`
Expected: 全部 PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/workers/tasks/agent_task_runner.py backend/app/workers/tasks/workflow_execution.py backend/app/services/task_service.py backend/tests/workers/test_agent_task_runner.py
git commit -m "feat(task): AgentTaskRunner 后台执行器——Celery 入口双目标分流 + 协作式取消"
```

---

### Task 5: 会话列表过滤任务会话

**Files:**
- Modify: `backend/app/services/session_service.py:158-177`（list_sessions）
- Test: `backend/tests/services/test_session_list_hides_task_sessions.py`（新建）

**Interfaces:**
- Consumes: Task 1 的 `Session.task_id`
- Produces: 会话列表（`GET /sessions`）默认不含任务会话；`GET /sessions/{id}` 详情不受影响（任务详情跳转可达）

- [ ] **Step 1: 写失败测试**

```python
"""会话列表过滤：task_id 非空（含字段缺失）的会话不出现在列表。"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.session_service import SessionService


@pytest.mark.asyncio
async def test_list_excludes_task_sessions() -> None:
    captured: dict = {}

    class FakeCursor:
        def sort(self, *a):
            return self

        def skip(self, *a):
            return self

        def limit(self, *a):
            return self

        async def to_list(self, length):
            return []

    col = MagicMock()
    col.count_documents = AsyncMock(return_value=0)
    col.find = lambda q: (captured.update(q) or FakeCursor())

    with patch.object(SessionService, "_collection", return_value=col):
        await SessionService.list_sessions(user_id="u1", page=1, page_size=20)

    assert captured["task_id"] == {"$in": ["", None]}, \
        "必须用 $in ['', None]（$in 含 None 同时匹配字段缺失的旧文档）"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/services/test_session_list_hides_task_sessions.py -v`
Expected: FAIL（filter 无 task_id 条件，KeyError）

- [ ] **Step 3: 实现** — `list_sessions` 的 filter_query（169 行）改为：

```python
        # 任务会话（task_id 非空）不出现在会话列表——任务详情页经 session_id
        # 直达详情（get_session 不过滤）。$in 含 None 以匹配字段缺失的旧文档。
        filter_query: dict = {"user_id": user_id, "task_id": {"$in": ["", None]}}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/services/test_session_list_hides_task_sessions.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/services/session_service.py backend/tests/services/test_session_list_hides_task_sessions.py
git commit -m "feat(session): 会话列表隐藏任务会话——task_id 过滤，详情直达不受影响"
```

---

### Task 6: 前端 API 层 + 创建分流（TaskBoard）

**Files:**
- Modify: `frontend-studio/src/services/tasks-api.ts:126-143,179-`（TaskSummary/TaskDetail/TaskCreatePayload）、`296`（create）
- Modify: `frontend-studio/src/components/TaskBoard.tsx:112-116,331-345,387-430`（state/mutation/handleCreateSubmit）、创建弹窗 JSX（814 行附近的调度选项区）

**Interfaces:**
- Consumes: 后端 `POST /tasks` 的 `agent_id` + `input.instruction` 契约（Task 2）
- Produces: `tasksApi.create({ agent_id, input })`；TaskBoard agent 分支提交路径

- [ ] **Step 1: 类型层** — `tasks-api.ts`：

`TaskSummary` 与 `TaskDetail` 的 `workflow_id: string` 行后各加：

```typescript
  /** 双目标：agent_id 非空 = agent 任务（workflow_id 为空串） */
  agent_id: string
```

`TaskCreatePayload` 加：

```typescript
  /** agent 任务目标：与 workflow_id 互斥（恰好其一） */
  agent_id?: string
```

- [ ] **Step 2: mutation 分流** — `TaskBoard.tsx` createTask mutation（331-345 行）改为：

```tsx
  const createTask = useMutation({
    // structuredInput：结构化表单收集的值（workflow 有输入变量定义时优先）；
    // agent 目标：input = {instruction}，entryId 此时存的是 agent id
    mutationFn: (vars: { entryId: string; input: string; structuredInput?: Record<string, unknown>; targetKind: 'workflow' | 'agent' }) =>
      vars.targetKind === 'agent'
        ? tasksApi.create({ agent_id: vars.entryId, input: { instruction: vars.input } })
        : tasksApi.create({
            workflow_id: resolveTemplateId(vars.entryId),
            input: vars.structuredInput ?? (vars.input ? { prompt: vars.input } : {}),
          }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: taskKeys.lists() })
      setCreateOpen(false)
      setNewTask({ entryId: '', input: '' })
    },
    onError: (e) => setActionError(`创建任务失败：${getErrorMessage(e)}`),
  })
```

- [ ] **Step 3: 删 stub + 提交分流 + preventDefault 修复** — `handleCreateSubmit`（387-430 行）签名加 event 并首行阻止默认提交（**当前缺 preventDefault 导致原生表单提交整页刷新回聊天主页——agent stub toast 一闪而过即被刷新吞掉，正是「点了执行跳聊天页」的根因**），删除 392-396 行 stub toast 块，两处 `createTask.mutate(...)`（426、429 行）都加 `targetKind: target?.kind ?? 'workflow'`：

```tsx
  const handleCreateSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!newTask.entryId) {
      setActionError('请先选择一个已发布的工作流')
      return
    }
    // ……（后续现状逻辑，stub 块删除，mutate 调用加 targetKind）
```

（`if (hasInputVariables) {` 分支保持现状，仅两处 mutate 调用补参：）

```tsx
    if (hasInputVariables) {
      // ……（现状不变）
      createTask.mutate({ ...newTask, structuredInput: res.values, targetKind: target?.kind ?? 'workflow' })
      return
    }
    createTask.mutate({ ...newTask, targetKind: target?.kind ?? 'workflow' })
```

（target 选择器选 agent 时 `newTask.entryId` 需存 agent `_id`——执行者检查选中 handler：现有代码选 workflow 时 `setNewTask({entryId: entry._id})` 且 `setTarget({kind, id, ...})`。若选 agent 时 entryId 未写 agent id，在该 handler 里补 `setNewTask({ entryId: agent._id, input: '' })`。）

- [ ] **Step 4: 调度模式 agent 适配** — agent 目标时调度不走 triggers（调度规则绑定 workflow），改走带 `scheduled_at` 的单次创建：`handleCreateSubmit` 的 `createMode === 'sched'` 分支（397-415 行）前面插入：

```tsx
    // agent 目标：调度规则(triggers)绑定 workflow，仅支持单次定时——
    // 创建带 scheduled_at 的任务，到期由 task_scheduler_service 自动拉起
    if (createMode === 'sched' && target?.kind === 'agent') {
      if (!schedOnceAt) {
        setActionError('请选择一次性执行的时间')
        return
      }
      setActionError(null)
      createTask.mutate({
        ...newTask,
        targetKind: 'agent',
        scheduledAt: new Date(schedOnceAt).toISOString(),
      } as typeof newTask & { scheduledAt: string })
      return
    }
```

对应 mutationFn 类型与 `tasksApi.create` 调用加 `scheduled_at?: string`（`TaskCreatePayload` 同步加字段，透传给后端 `scheduled_at`）。创建弹窗 JSX（814 行附近）：`target?.kind === 'agent'` 时调度频率选项只渲染「一次性」（隐藏 daily/weekly/monthly/hourly/adv），并隐藏或禁用 agent + 周期组合——执行者按现有 SCHED_FREQ_LABEL 渲染处加条件即可。

- [ ] **Step 5: 构建验证 + 提交**

Run: `cd frontend-studio && npm run build`
Expected: 编译零错误（类型检查通过）

```bash
git add frontend-studio/src/services/tasks-api.ts frontend-studio/src/components/TaskBoard.tsx
git commit -m "feat(task-board): 创建任务支持 agent 目标——指令输入/单次定时/删 stub 拦截"
```

---

### Task 7: 前端展示（目标名 / 详情页 / 执行过程跳转）

**Files:**
- Modify: `frontend-studio/src/components/TaskBoard.tsx`（agentNameMap + 列表目标名渲染处）
- Modify: `frontend-studio/src/components/task/TaskDetailPage.tsx`（agent 任务条件渲染）

**Interfaces:**
- Consumes: `TaskSummary.agent_id`（Task 6）、后端 `output = {output, session_id, step_count, agent_id}`（Task 4）
- Produces: agent 任务在列表/详情的完整展示

- [ ] **Step 1: 目标名解析** — `TaskBoard.tsx` 在 `workflowNameMap`（237 行附近）后加：

```tsx
  // agent 目标名解析：与 workflowNameMap 同构（published 列表 → id→name）
  const { data: agentData } = useQuery({
    queryKey: agentKeys.list({ page: 1, page_size: 100, status: 'published' }),
    queryFn: () => agentApi.list({ page: 1, page_size: 100, status: 'published' }),
  })
  const agentNameMap = useMemo(() => {
    const map: Record<string, string> = {}
    for (const a of agentData?.items ?? []) map[a.id] = a.name
    return map
  }, [agentData])
```

（`agentApi/agentKeys` 已 import——TaskBoard 26 行已有。若与现有 `agentsQuery` 重复则复用现有 query。）列表/看板卡片目标名渲染处（搜 `workflowNameMap[`）：`t.agent_id ? agentNameMap[t.agent_id] ?? t.agent_id : workflowNameMap[t.workflow_id] ?? ''`。

- [ ] **Step 2: 详情页 agent 渲染** — `TaskDetailPage.tsx`：agent 任务（`task.agent_id` 非空）跳过节点图/时间线渲染区（`TaskFlowGraph` 调用处），替换为结果卡：

```tsx
{task.agent_id ? (
  <div className="space-y-3">
    <div className="af-card p-4">
      <div className="text-[13px] text-ink-faint mb-1">执行指令</div>
      <div className="text-[14px] whitespace-pre-wrap">{String(task.input?.instruction ?? '')}</div>
    </div>
    {task.output?.output && (
      <div className="af-card p-4">
        <div className="text-[13px] text-ink-faint mb-1">执行结果</div>
        <div className="text-[14px] whitespace-pre-wrap">{String(task.output.output)}</div>
        {task.output?.session_id && (
          <button
            className="mt-3 text-[13px] text-brand underline-offset-2 hover:underline"
            onClick={() => { sessionStorage.setItem('af_open_session_id', String(task.output!.session_id)); nav('/') }}
          >
            查看执行过程 →
          </button>
        )}
      </div>
    )}
  </div>
) : (
  /* 现有节点图/时间线渲染不动 */
)}
```

（className/路由以项目实际为准：`af-card`/`text-ink-faint` 等语义类见 `docs/design/DESIGN_SYSTEM.md`；导航用组件现有 router 手段——执行者先看该文件既有跳转写法再落地；**会话页需支持 `af_open_session_id` 定位打开会话**——若会话页无此机制，最小实现：`ChatHomepage` 挂载时读 sessionStorage 并打开对应会话，读取后即清除。）

- [ ] **Step 3: 构建验证 + 提交**

Run: `cd frontend-studio && npm run build`
Expected: 零错误

```bash
git add frontend-studio/src/components/TaskBoard.tsx frontend-studio/src/components/task/TaskDetailPage.tsx
git commit -m "feat(task-board): agent 任务展示——目标名/指令结果详情/查看执行过程跳转"
```

---

### Task 8: Spec 修订 + 全链路验收

**Files:**
- Modify: `docs/superpowers/specs/2026-11-10-agent-task-design.md`（两处计划期修订，不提交 git）

**Interfaces:** 无代码产出——收尾任务。

- [ ] **Step 1: spec 修订** — 编辑 spec：

1. 第 4 节「取消语义」段落替换为：协作式中断——Runner 传 `cancel_checker`（查 task DB status），harness 每轮 REACT 边界检查；Celery revoke 兜底；回写守卫丢弃迟到的成功结果。删除原 `ponytail:` 注释（协作式中断已落地，无需 upgrade path）。
2. 第 4 节执行流 invoke 调用注明 `execution_context="workflow"`（无人值守语义：剥离交互式工具、注入 abort_workflow——后台任务绝不挂起等人）。

- [ ] **Step 2: 后端全量回归**

Run: `cd backend && uv run pytest tests/ -q`
Expected: 全部 PASS

- [ ] **Step 3: 手动验收清单**（起前后端后逐项勾选）

1. 新建任务选已发布 agent + 指令 → 立即执行 → 看板出现且最终 completed，详情显示指令/答案/token
2. 详情「查看执行过程」→ 跳会话页可见完整 REACT 轨迹（用户消息 + agent 消息）
3. 会话主页列表**不含**任务会话
4. 运行中取消 → 任务 cancelled；若 agent 已在跑，下一轮边界中断，迟到结果被丢弃
5. failed 任务 retry → 重跑成功
6. agent 任务 + 一次性定时 → 到期由调度自动拉起执行
7. 原 workflow 任务创建/执行/定时调度全流程回归正常（分流不影响旧路径）

- [ ] **Step 4: 验收问题修复后提交**

```bash
git add -A && git commit -m "fix(task): Agent 后台任务验收修复"
```
