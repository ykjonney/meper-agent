# Workflow 定时触发系统实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 Workflow 引擎添加定时触发能力，支持 Cron 重复执行和一次性定时执行。

**Architecture:** 在 Workflow 模型中新增 trigger_config 字段，使用 Celery Beat 动态注册调度任务，通过 API 管理触发配置，前端提供可视化 Cron 构建器。

**Tech Stack:**
- Backend: FastAPI + Celery + Redis + MongoDB + Pydantic + Jinja2
- Frontend: React + TypeScript + Ant Design
- Testing: pytest (backend) + Jest (frontend)

---

## 阶段 1：后端数据模型与工具函数

### Task 1: TriggerConfig 数据模型

**Files:**
- Modify: `backend/app/models/workflow.py`
- Test: `backend/tests/models/test_workflow_trigger.py`

- [ ] **Step 1: 编写 TriggerConfig 模型测试**

```python
# backend/tests/models/test_workflow_trigger.py
from datetime import datetime, timezone
import pytest
from app.models.workflow import TriggerConfig

def test_trigger_config_cron():
    """测试 Cron 类型触发配置"""
    config = TriggerConfig(
        type="cron",
        enabled=True,
        cron_expression="0 9 * * *",
        default_input={"date": "{{ now() }}"}
    )
    assert config.type == "cron"
    assert config.enabled is True
    assert config.cron_expression == "0 9 * * *"
    assert config.execute_at is None

def test_trigger_config_once():
    """测试一次性触发配置"""
    execute_time = datetime(2026, 7, 10, 14, 0, tzinfo=timezone.utc)
    config = TriggerConfig(
        type="once",
        enabled=True,
        execute_at=execute_time,
        default_input={}
    )
    assert config.type == "once"
    assert config.execute_at == execute_time
    assert config.cron_expression is None

def test_trigger_config_defaults():
    """测试默认值"""
    config = TriggerConfig(type="cron")
    assert config.enabled is False
    assert config.default_input == {}
    assert config.last_triggered_at is None
```

- [ ] **Step 2: 运行测试验证失败**

```bash
cd backend
uv run pytest tests/models/test_workflow_trigger.py -v
```

Expected: FAIL - ImportError: cannot import name 'TriggerConfig'

- [ ] **Step 3: 实现 TriggerConfig 模型**

```python
# backend/app/models/workflow.py
# 在文件顶部导入区添加
from datetime import datetime
from typing import Any
from pydantic import BaseModel, Field
from app.models.base import generate_id, utc_now

# 添加 TriggerConfig 类（在 WorkflowStatus 之后）
class TriggerConfig(BaseModel):
    """Workflow 定时触发配置"""

    type: str  # "cron" | "once"
    enabled: bool = False
    cron_expression: str | None = None
    execute_at: datetime | None = None
    default_input: dict[str, Any] = Field(default_factory=dict)
    last_triggered_at: datetime | None = None
    next_trigger_at: datetime | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

# 在 Workflow 类中添加字段
class Workflow(BaseModel):
    # ... 现有字段保持不变 ...
    trigger_config: TriggerConfig | None = None
```

- [ ] **Step 4: 运行测试验证通过**

```bash
cd backend
uv run pytest tests/models/test_workflow_trigger.py -v
```

Expected: 3 tests PASS

- [ ] **Step 5: 提交**

```bash
cd backend
git add app/models/workflow.py tests/models/test_workflow_trigger.py
git commit -m "feat(workflow): add TriggerConfig model for scheduled triggers"
```

---

### Task 2: 模板渲染工具函数

**Files:**
- Create: `backend/app/utils/template_renderer.py`
- Test: `backend/tests/utils/test_template_renderer.py`

- [ ] **Step 1: 编写模板渲染测试**

```python
# backend/tests/utils/test_template_renderer.py
from datetime import datetime, timezone
import pytest
from app.utils.template_renderer import render_default_input

def test_render_static_values():
    """测试静态值不做处理"""
    default_input = {"department": "engineering", "count": 5}
    result = render_default_input(default_input)
    assert result == {"department": "engineering", "count": 5}

def test_render_now_template():
    """测试 {{ now() }} 模板"""
    default_input = {"timestamp": "{{ now() }}"}
    result = render_default_input(default_input)
    # 验证是 ISO 格式时间字符串
    assert "timestamp" in result
    datetime.fromisoformat(result["timestamp"])

def test_render_today_template():
    """测试 {{ today() }} 模板"""
    default_input = {"date": "{{ today() }}"}
    result = render_default_input(default_input)
    # 验证是 YYYY-MM-DD 格式
    assert len(result["date"]) == 10
    assert result["date"].count("-") == 2

def test_render_mixed():
    """测试混合模板和静态值"""
    default_input = {
        "date": "{{ today() }}",
        "department": "engineering",
        "timestamp": "{{ now() }}"
    }
    result = render_default_input(default_input)
    assert result["department"] == "engineering"
    assert "{{" not in result["date"]
    assert "{{" not in result["timestamp"]

def test_render_invalid_template():
    """测试无效模板降级处理"""
    default_input = {"invalid": "{{ undefined_func() }}"}
    result = render_default_input(default_input)
    # 无效模板返回原始字符串
    assert result["invalid"] == "{{ undefined_func() }}"
```

- [ ] **Step 2: 运行测试验证失败**

```bash
cd backend
uv run pytest tests/utils/test_template_renderer.py -v
```

Expected: FAIL - ImportError

- [ ] **Step 3: 实现模板渲染函数**

```python
# backend/app/utils/template_renderer.py
from datetime import datetime, timezone
from typing import Any
from jinja2 import Template, TemplateSyntaxError
from loguru import logger


def render_default_input(default_input: dict[str, Any]) -> dict[str, Any]:
    """渲染默认输入参数模板

    支持 Jinja2 模板语法，提供以下内置变量：
    - {{ now() }}: 当前 UTC 时间（ISO 格式）
    - {{ today() }}: 当前日期（YYYY-MM-DD）

    Args:
        default_input: 默认输入参数字典，值可以是模板字符串

    Returns:
        渲染后的参数字典
    """
    context = {
        "now": lambda: datetime.now(timezone.utc).isoformat(),
        "today": lambda: datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }

    rendered = {}
    for key, value in default_input.items():
        if isinstance(value, str) and "{{" in value:
            try:
                template = Template(value)
                rendered[key] = template.render(**context)
            except TemplateSyntaxError as e:
                logger.warning(
                    "template_render_failed",
                    key=key,
                    template=value,
                    error=str(e),
                )
                # 降级：返回原始字符串
                rendered[key] = value
        else:
            rendered[key] = value

    return rendered
```

- [ ] **Step 4: 运行测试验证通过**

```bash
cd backend
uv run pytest tests/utils/test_template_renderer.py -v
```

Expected: 5 tests PASS

- [ ] **Step 5: 提交**

```bash
cd backend
git add app/utils/template_renderer.py tests/utils/test_template_renderer.py
git commit -m "feat(utils): add template renderer for trigger default_input"
```

---

## 阶段 2：后端调度服务

### Task 3: TriggerSchedulerService 基础结构

**Files:**
- Create: `backend/app/services/trigger_scheduler_service.py`
- Test: `backend/tests/services/test_trigger_scheduler_service.py`

- [ ] **Step 1: 编写服务基础测试**

```python
# backend/tests/services/test_trigger_scheduler_service.py
import pytest
from unittest.mock import AsyncMock, patch
from app.services.trigger_scheduler_service import TriggerSchedulerService


@pytest.fixture
def service():
    return TriggerSchedulerService()


async def test_service_initialization(service):
    """测试服务初始化"""
    assert service._workflows == {}
    assert service._started is False


async def test_service_start_stop(service):
    """测试服务启停"""
    await service.start()
    assert service._started is True

    await service.stop()
    assert service._started is False
```

- [ ] **Step 2: 运行测试验证失败**

```bash
cd backend
uv run pytest tests/services/test_trigger_scheduler_service.py -v
```

Expected: FAIL - ImportError

- [ ] **Step 3: 实现服务基础结构**

```python
# backend/app/services/trigger_scheduler_service.py
from typing import Any
from loguru import logger
from app.db.mongodb import get_database


class TriggerSchedulerService:
    """定时触发调度服务

    负责管理 Celery Beat 调度的动态注册。
    """

    def __init__(self) -> None:
        self._workflows: dict[str, dict[str, Any]] = {}
        self._started: bool = False

    async def start(self) -> None:
        """服务启动时初始化调度器"""
        if self._started:
            logger.warning("trigger_scheduler_already_started")
            return

        self._started = True
        logger.info("trigger_scheduler_started")

        # 扫描所有已启用的触发配置
        await self._load_and_register_triggers()

    async def stop(self) -> None:
        """服务停止"""
        self._started = False
        self._workflows.clear()
        logger.info("trigger_scheduler_stopped")

    async def _load_and_register_triggers(self) -> None:
        """扫描并注册所有已启用的触发任务"""
        db = get_database()
        cursor = db["workflows"].find({
            "trigger_config.enabled": True
        })

        async for doc in cursor:
            workflow_id = doc["_id"]
            self._workflows[workflow_id] = doc
            logger.info(
                "trigger_registered",
                workflow_id=workflow_id,
                trigger_type=doc.get("trigger_config", {}).get("type"),
            )

    async def register_trigger(self, workflow_id: str) -> None:
        """注册单个触发任务"""
        db = get_database()
        doc = await db["workflows"].find_one({"_id": workflow_id})
        if doc and doc.get("trigger_config", {}).get("enabled"):
            self._workflows[workflow_id] = doc
            logger.info("trigger_registered", workflow_id=workflow_id)

    async def unregister_trigger(self, workflow_id: str) -> None:
        """移除触发任务"""
        if workflow_id in self._workflows:
            del self._workflows[workflow_id]
            logger.info("trigger_unregistered", workflow_id=workflow_id)

    async def update_trigger(self, workflow_id: str) -> None:
        """更新触发配置"""
        await self.unregister_trigger(workflow_id)
        await self.register_trigger(workflow_id)


# 模块级单例
_scheduler: TriggerSchedulerService | None = None


def get_trigger_scheduler() -> TriggerSchedulerService:
    """获取触发调度器单例"""
    global _scheduler
    if _scheduler is None:
        _scheduler = TriggerSchedulerService()
    return _scheduler
```

- [ ] **Step 4: 运行测试验证通过**

```bash
cd backend
uv run pytest tests/services/test_trigger_scheduler_service.py -v
```

Expected: 2 tests PASS

- [ ] **Step 5: 提交**

```bash
cd backend
git add app/services/trigger_scheduler_service.py tests/services/test_trigger_scheduler_service.py
git commit -m "feat(scheduler): add TriggerSchedulerService basic structure"
```

---

### Task 4: Celery Task 实现

**Files:**
- Create: `backend/app/workers/tasks/scheduled_workflow.py`
- Test: `backend/tests/workers/test_scheduled_workflow.py`

- [ ] **Step 1: 编写 Celery Task 测试**

```python
# backend/tests/workers/test_scheduled_workflow.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from app.workers.tasks.scheduled_workflow import execute_scheduled_workflow


@patch("app.workers.tasks.scheduled_workflow.TaskService")
@patch("app.workers.tasks.scheduled_workflow.get_database")
@patch("app.workers.tasks.scheduled_workflow.render_default_input")
@patch("app.workers.tasks.scheduled_workflow.WorkflowEngine")
async def test_execute_scheduled_workflow_success(
    mock_engine_class, mock_render, mock_db_func, mock_task_service
):
    """测试成功执行定时任务"""
    # Mock 数据库返回
    mock_db = MagicMock()
    mock_db_func.return_value = mock_db

    workflow_doc = {
        "_id": "wf_xxx",
        "name": "Test Workflow",
        "trigger_config": {
            "type": "cron",
            "default_input": {"date": "{{ today() }}"}
        }
    }
    mock_db["workflows"].find_one = AsyncMock(return_value=workflow_doc)

    # Mock 模板渲染
    mock_render.return_value = {"date": "2026-07-07"}

    # Mock TaskService.create_task
    task_doc = {"_id": "task_xxx", "status": "pending"}
    mock_task_service.create_task = AsyncMock(return_value=task_doc)

    # Mock WorkflowEngine
    mock_engine = MagicMock()
    mock_engine.run_and_persist = AsyncMock(return_value={"result": "success"})
    mock_engine_class.return_value = mock_engine

    # 执行
    result = execute_scheduled_workflow("wf_xxx")

    # 验证
    assert result["status"] == "success"
    mock_task_service.create_task.assert_called_once()
    mock_engine.run_and_persist.assert_called_once_with("task_xxx")


@patch("app.workers.tasks.scheduled_workflow.get_database")
async def test_execute_scheduled_workflow_not_found(mock_db_func):
    """测试 Workflow 不存在"""
    mock_db = MagicMock()
    mock_db_func.return_value = mock_db
    mock_db["workflows"].find_one = AsyncMock(return_value=None)

    result = execute_scheduled_workflow("wf_not_exist")

    assert result["status"] == "error"
    assert "not found" in result["message"].lower()
```

- [ ] **Step 2: 运行测试验证失败**

```bash
cd backend
uv run pytest tests/workers/test_scheduled_workflow.py -v
```

Expected: FAIL - ImportError

- [ ] **Step 3: 实现 Celery Task**

```python
# backend/app/workers/tasks/scheduled_workflow.py
from datetime import datetime, timezone
from loguru import logger
from celery import shared_task

from app.db.mongodb import get_database
from app.models.base import utc_now
from app.utils.template_renderer import render_default_input


@shared_task(name="execute_scheduled_workflow")
def execute_scheduled_workflow(workflow_id: str) -> dict:
    """定时触发执行 Workflow

    Args:
        workflow_id: Workflow ID

    Returns:
        Task 执行结果摘要
    """
    import asyncio
    return asyncio.run(_execute_async(workflow_id))


async def _execute_async(workflow_id: str) -> dict:
    """异步执行逻辑"""
    db = get_database()

    # 1. 加载 Workflow
    workflow_doc = await db["workflows"].find_one({"_id": workflow_id})
    if not workflow_doc:
        logger.error("scheduled_workflow_not_found", workflow_id=workflow_id)
        return {"status": "error", "message": f"Workflow {workflow_id} not found"}

    trigger_config = workflow_doc.get("trigger_config", {})
    if not trigger_config.get("enabled"):
        logger.warning("scheduled_workflow_disabled", workflow_id=workflow_id)
        return {"status": "error", "message": "Trigger is disabled"}

    # 2. 渲染默认输入参数
    default_input = trigger_config.get("default_input", {})
    rendered_input = render_default_input(default_input)

    logger.info(
        "scheduled_workflow_starting",
        workflow_id=workflow_id,
        rendered_input=rendered_input,
    )

    # 3. 创建 Task 实例
    from app.services.task_service import TaskService

    task_doc = await TaskService.create_task(
        workflow_id=workflow_id,
        input_data=rendered_input,
        created_by="system",
        created_by_type="system",
    )
    task_id = task_doc["_id"]

    logger.info(
        "scheduled_workflow_task_created",
        workflow_id=workflow_id,
        task_id=task_id,
    )

    # 4. 执行 Workflow
    try:
        from app.engine.workflow.engine import WorkflowEngine

        engine = WorkflowEngine()
        await engine.run_and_persist(task_id)

        # 5. 更新 last_triggered_at
        await db["workflows"].update_one(
            {"_id": workflow_id},
            {"$set": {"trigger_config.last_triggered_at": utc_now()}},
        )

        logger.info("scheduled_workflow_completed", workflow_id=workflow_id, task_id=task_id)
        return {"status": "success", "task_id": task_id}

    except Exception as e:
        logger.error(
            "scheduled_workflow_failed",
            workflow_id=workflow_id,
            task_id=task_id,
            error=str(e),
        )
        return {"status": "error", "task_id": task_id, "message": str(e)}
```

- [ ] **Step 4: 注册 Celery Task**

```python
# backend/app/workers/celery_app.py
# 在 include 列表中添加
celery_app = Celery(
    "agent_flow",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=[
        "app.workers.tasks.maintenance",
        "app.workers.tasks.webhook_delivery",
        "app.workers.tasks.scheduled_workflow",  # 新增
    ],
)
```

- [ ] **Step 5: 运行测试验证通过**

```bash
cd backend
uv run pytest tests/workers/test_scheduled_workflow.py -v
```

Expected: 2 tests PASS

- [ ] **Step 6: 提交**

```bash
cd backend
git add app/workers/tasks/scheduled_workflow.py app/workers/celery_app.py tests/workers/test_scheduled_workflow.py
git commit -m "feat(workers): add execute_scheduled_workflow Celery task"
```

---

## 阶段 3：后端 API

### Task 5: 触发配置 API 端点

**Files:**
- Modify: `backend/app/api/v1/workflows.py`
- Test: `backend/tests/api/v1/test_workflow_triggers.py`

- [ ] **Step 1: 编写 API 测试**

```python
# backend/tests/api/v1/test_workflow_triggers.py
import pytest
from httpx import AsyncClient
from unittest.mock import patch, AsyncMock

@pytest.fixture
def mock_workflow_with_trigger():
    return {
        "_id": "wf_xxx",
        "name": "Test Workflow",
        "trigger_config": {
            "type": "cron",
            "enabled": True,
            "cron_expression": "0 9 * * *",
            "default_input": {"date": "{{ today() }}"},
        }
    }


async def test_create_trigger_config(client: AsyncClient, mock_workflow_with_trigger):
    """测试创建触发配置"""
    with patch("app.api.v1.workflows.get_database") as mock_db:
        mock_db.return_value = {"workflows": AsyncMock()}
        mock_db.return_value["workflows"].find_one = AsyncMock(return_value=None)
        mock_db.return_value["workflows"].update_one = AsyncMock()

        response = await client.post(
            "/api/workflows/wf_xxx/trigger",
            json={
                "type": "cron",
                "enabled": True,
                "cron_expression": "0 9 * * *",
                "default_input": {"date": "{{ today() }}"}
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert data["type"] == "cron"
        assert data["enabled"] is True


async def test_get_trigger_config(client: AsyncClient, mock_workflow_with_trigger):
    """测试获取触发配置"""
    with patch("app.api.v1.workflows.get_database") as mock_db:
        mock_db.return_value = {"workflows": AsyncMock()}
        mock_db.return_value["workflows"].find_one = AsyncMock(
            return_value=mock_workflow_with_trigger
        )

        response = await client.get("/api/workflows/wf_xxx/trigger")

        assert response.status_code == 200
        data = response.json()
        assert data["type"] == "cron"
        assert data["cron_expression"] == "0 9 * * *"


async def test_toggle_trigger(client: AsyncClient, mock_workflow_with_trigger):
    """测试切换启用状态"""
    with patch("app.api.v1.workflows.get_database") as mock_db:
        mock_db.return_value = {"workflows": AsyncMock()}
        mock_db.return_value["workflows"].find_one = AsyncMock(
            return_value=mock_workflow_with_trigger
        )
        mock_db.return_value["workflows"].update_one = AsyncMock()

        response = await client.patch(
            "/api/workflows/wf_xxx/trigger/toggle",
            json={"enabled": False}
        )

        assert response.status_code == 200
        assert response.json()["enabled"] is False


async def test_delete_trigger(client: AsyncClient, mock_workflow_with_trigger):
    """测试删除触发配置"""
    with patch("app.api.v1.workflows.get_database") as mock_db:
        mock_db.return_value = {"workflows": AsyncMock()}
        mock_db.return_value["workflows"].find_one = AsyncMock(
            return_value=mock_workflow_with_trigger
        )
        mock_db.return_value["workflows"].update_one = AsyncMock()

        response = await client.delete("/api/workflows/wf_xxx/trigger")

        assert response.status_code == 200
```

- [ ] **Step 2: 运行测试验证失败**

```bash
cd backend
uv run pytest tests/api/v1/test_workflow_triggers.py -v
```

Expected: FAIL - 404 Not Found (路由不存在)

- [ ] **Step 3: 实现 API 端点**

```python
# backend/app/api/v1/workflows.py
# 在文件顶部导入区添加
from app.models.workflow import TriggerConfig

# 在文件末尾添加新的路由

@router.post(
    "/{workflow_id}/trigger",
    response_model=dict,
    summary="创建或更新触发配置",
)
async def create_or_update_trigger(
    workflow_id: str,
    trigger_config: TriggerConfig,
) -> dict:
    """创建或更新 Workflow 的定时触发配置"""
    from app.db.mongodb import get_database
    from app.models.base import utc_now

    db = get_database()

    # 验证 Workflow 存在
    workflow_doc = await db["workflows"].find_one({"_id": workflow_id})
    if not workflow_doc:
        from app.core.exceptions import NotFoundError
        raise NotFoundError(
            code="WORKFLOW_NOT_FOUND",
            message=f"Workflow {workflow_id} not found",
        )

    # 更新触发配置
    config_dict = trigger_config.model_dump()
    config_dict["updated_at"] = utc_now()
    if not config_dict.get("created_at"):
        config_dict["created_at"] = utc_now()

    await db["workflows"].update_one(
        {"_id": workflow_id},
        {"$set": {"trigger_config": config_dict}},
    )

    # 更新调度器
    from app.services.trigger_scheduler_service import get_trigger_scheduler
    await get_trigger_scheduler().update_trigger(workflow_id)

    return config_dict


@router.get(
    "/{workflow_id}/trigger",
    response_model=dict,
    summary="获取触发配置",
)
async def get_trigger(workflow_id: str) -> dict:
    """获取 Workflow 的定时触发配置"""
    from app.db.mongodb import get_database

    db = get_database()
    workflow_doc = await db["workflows"].find_one({"_id": workflow_id})

    if not workflow_doc:
        from app.core.exceptions import NotFoundError
        raise NotFoundError(
            code="WORKFLOW_NOT_FOUND",
            message=f"Workflow {workflow_id} not found",
        )

    trigger_config = workflow_doc.get("trigger_config")
    if not trigger_config:
        from app.core.exceptions import NotFoundError
        raise NotFoundError(
            code="TRIGGER_NOT_FOUND",
            message=f"No trigger config for workflow {workflow_id}",
        )

    return trigger_config


@router.delete(
    "/{workflow_id}/trigger",
    response_model=dict,
    summary="删除触发配置",
)
async def delete_trigger(workflow_id: str) -> dict:
    """删除 Workflow 的定时触发配置"""
    from app.db.mongodb import get_database

    db = get_database()

    # 验证 Workflow 存在
    workflow_doc = await db["workflows"].find_one({"_id": workflow_id})
    if not workflow_doc:
        from app.core.exceptions import NotFoundError
        raise NotFoundError(
            code="WORKFLOW_NOT_FOUND",
            message=f"Workflow {workflow_id} not found",
        )

    # 删除触发配置
    await db["workflows"].update_one(
        {"_id": workflow_id},
        {"$unset": {"trigger_config": ""}},
    )

    # 从调度器移除
    from app.services.trigger_scheduler_service import get_trigger_scheduler
    await get_trigger_scheduler().unregister_trigger(workflow_id)

    return {"status": "deleted"}


@router.patch(
    "/{workflow_id}/trigger/toggle",
    response_model=dict,
    summary="切换触发配置启用状态",
)
async def toggle_trigger(workflow_id: str, body: dict) -> dict:
    """切换触发配置的启用/禁用状态"""
    from app.db.mongodb import get_database
    from app.models.base import utc_now

    db = get_database()

    # 验证 Workflow 存在
    workflow_doc = await db["workflows"].find_one({"_id": workflow_id})
    if not workflow_doc:
        from app.core.exceptions import NotFoundError
        raise NotFoundError(
            code="WORKFLOW_NOT_FOUND",
            message=f"Workflow {workflow_id} not found",
        )

    trigger_config = workflow_doc.get("trigger_config")
    if not trigger_config:
        from app.core.exceptions import NotFoundError
        raise NotFoundError(
            code="TRIGGER_NOT_FOUND",
            message=f"No trigger config for workflow {workflow_id}",
        )

    # 切换状态
    enabled = body.get("enabled", not trigger_config.get("enabled", False))
    trigger_config["enabled"] = enabled
    trigger_config["updated_at"] = utc_now()

    await db["workflows"].update_one(
        {"_id": workflow_id},
        {"$set": {"trigger_config": trigger_config}},
    )

    # 更新调度器
    from app.services.trigger_scheduler_service import get_trigger_scheduler
    if enabled:
        await get_trigger_scheduler().register_trigger(workflow_id)
    else:
        await get_trigger_scheduler().unregister_trigger(workflow_id)

    return trigger_config
```

- [ ] **Step 4: 运行测试验证通过**

```bash
cd backend
uv run pytest tests/api/v1/test_workflow_triggers.py -v
```

Expected: 4 tests PASS

- [ ] **Step 5: 提交**

```bash
cd backend
git add app/api/v1/workflows.py tests/api/v1/test_workflow_triggers.py
git commit -m "feat(api): add trigger config CRUD endpoints"
```

---

### Task 6: 服务启动集成

**Files:**
- Modify: `backend/app/core/start.py`

- [ ] **Step 1: 在启动时初始化 TriggerSchedulerService**

```python
# backend/app/core/start.py
# 在 lifespan 函数中添加

from app.services.trigger_scheduler_service import get_trigger_scheduler

async def lifespan(app: FastAPI):
    # ... 现有启动代码 ...

    # 启动触发调度器
    trigger_scheduler = get_trigger_scheduler()
    await trigger_scheduler.start()

    yield

    # 停止触发调度器
    await trigger_scheduler.stop()

    # ... 现有关闭代码 ...
```

- [ ] **Step 2: 提交**

```bash
cd backend
git add app/core/start.py
git commit -m "feat(startup): initialize TriggerSchedulerService on app start"
```

---

## 阶段 4：前端实现

### Task 7: TypeScript 类型定义

**Files:**
- Create: `frontend/src/types/workflow-trigger.ts`

- [ ] **Step 1: 创建类型定义**

```typescript
// frontend/src/types/workflow-trigger.ts

export type TriggerType = "cron" | "once";

export interface TriggerConfig {
  type: TriggerType;
  enabled: boolean;
  cron_expression?: string;
  execute_at?: string; // ISO datetime string
  default_input: Record<string, any>;
  last_triggered_at?: string;
  next_trigger_at?: string;
  created_at: string;
  updated_at: string;
}

export interface CronPreset {
  label: string;
  value: string;
  cron: string;
}

export const CRON_PRESETS: CronPreset[] = [
  { label: "每小时", value: "hourly", cron: "0 * * * *" },
  { label: "每天 09:00", value: "daily_9", cron: "0 9 * * *" },
  { label: "每周一 09:00", value: "weekly_mon_9", cron: "0 9 * * 1" },
  { label: "每月 1 号 09:00", value: "monthly_1_9", cron: "0 9 1 * *" },
];
```

- [ ] **Step 2: 提交**

```bash
cd frontend
git add src/types/workflow-trigger.ts
git commit -m "feat(types): add workflow trigger TypeScript types"
```

---

### Task 8: API 服务层

**Files:**
- Create: `frontend/src/services/workflow-trigger-api.ts`

- [ ] **Step 1: 创建 API 服务**

```typescript
// frontend/src/services/workflow-trigger-api.ts
import { request } from "@/utils/request";
import type { TriggerConfig } from "@/types/workflow-trigger";

export const WorkflowTriggerAPI = {
  /**
   * 创建或更新触发配置
   */
  async updateTrigger(workflowId: string, config: Partial<TriggerConfig>) {
    return request.post<TriggerConfig>(
      `/api/workflows/${workflowId}/trigger`,
      config
    );
  },

  /**
   * 获取触发配置
   */
  async getTrigger(workflowId: string) {
    return request.get<TriggerConfig>(
      `/api/workflows/${workflowId}/trigger`
    );
  },

  /**
   * 删除触发配置
   */
  async deleteTrigger(workflowId: string) {
    return request.delete<{ status: string }>(
      `/api/workflows/${workflowId}/trigger`
    );
  },

  /**
   * 切换启用状态
   */
  async toggleTrigger(workflowId: string, enabled: boolean) {
    return request.patch<TriggerConfig>(
      `/api/workflows/${workflowId}/trigger/toggle`,
      { enabled }
    );
  },
};
```

- [ ] **Step 2: 提交**

```bash
cd frontend
git add src/services/workflow-trigger-api.ts
git commit -m "feat(api): add workflow trigger API service"
```

---

### Task 9: CronPresetSelector 组件

**Files:**
- Create: `frontend/src/components/workflows/CronPresetSelector.tsx`

- [ ] **Step 1: 创建组件**

```typescript
// frontend/src/components/workflows/CronPresetSelector.tsx
import React from "react";
import { Select, Input, Collapse } from "antd";
import { CRON_PRESETS } from "@/types/workflow-trigger";

interface CronPresetSelectorProps {
  value?: string;
  onChange?: (value: string) => void;
}

export const CronPresetSelector: React.FC<CronPresetSelectorProps> = ({
  value = "",
  onChange,
}) => {
  const [isCustom, setIsCustom] = React.useState(false);

  const handlePresetChange = (presetValue: string) => {
    if (presetValue === "custom") {
      setIsCustom(true);
    } else {
      setIsCustom(false);
      const preset = CRON_PRESETS.find((p) => p.value === presetValue);
      if (preset) {
        onChange?.(preset.cron);
      }
    }
  };

  const handleCustomChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    onChange?.(e.target.value);
  };

  return (
    <div className="space-y-3">
      <Select
        className="w-full"
        value={isCustom ? "custom" : CRON_PRESETS.find((p) => p.cron === value)?.value || "daily_9"}
        onChange={handlePresetChange}
        options={[
          ...CRON_PRESETS.map((p) => ({ label: p.label, value: p.value })),
          { label: "自定义（高级）", value: "custom" },
        ]}
      />

      {isCustom && (
        <Input
          value={value}
          onChange={handleCustomChange}
          placeholder="Cron 表达式，如：0 9 * * *"
          addonAfter={
            <span className="text-xs text-gray-500">
              分 时 日 月 周
            </span>
          }
        />
      )}

      {value && (
        <div className="text-sm text-gray-500">
          预览: <code>{value}</code>
        </div>
      )}
    </div>
  );
};
```

- [ ] **Step 2: 提交**

```bash
cd frontend
git add src/components/workflows/CronPresetSelector.tsx
git commit -m "feat(ui): add CronPresetSelector component"
```

---

### Task 10: DefaultInputEditor 组件

**Files:**
- Create: `frontend/src/components/workflows/DefaultInputEditor.tsx`

- [ ] **Step 1: 创建组件**

```typescript
// frontend/src/components/workflows/DefaultInputEditor.tsx
import React from "react";
import { Table, Input, Button, Space, Typography } from "antd";
import { PlusOutlined, DeleteOutlined } from "@ant-design/icons";

interface DefaultInputEditorProps {
  value?: Record<string, any>;
  onChange?: (value: Record<string, any>) => void;
}

export const DefaultInputEditor: React.FC<DefaultInputEditorProps> = ({
  value = {},
  onChange,
}) => {
  const data = React.useMemo(() => {
    return Object.entries(value).map(([key, val]) => ({
      key,
      name: key,
      value: String(val),
    }));
  }, [value]);

  const handleAdd = () => {
    const newKey = `param_${Date.now()}`;
    onChange?.({ ...value, [newKey]: "" });
  };

  const handleDelete = (key: string) => {
    const newValue = { ...value };
    delete newValue[key];
    onChange?.(newValue);
  };

  const handleChange = (key: string, newValue: string) => {
    onChange?.({ ...value, [key]: newValue });
  };

  const columns = [
    {
      title: "参数名",
      dataIndex: "name",
      key: "name",
      width: 150,
    },
    {
      title: "值",
      dataIndex: "value",
      key: "value",
      render: (text: string, record: any) => (
        <Input
          value={text}
          onChange={(e) => handleChange(record.key, e.target.value)}
          placeholder="支持模板语法，如 {{ now() }}"
        />
      ),
    },
    {
      title: "操作",
      key: "action",
      width: 80,
      render: (_: any, record: any) => (
        <Button
          type="text"
          danger
          icon={<DeleteOutlined />}
          onClick={() => handleDelete(record.key)}
        />
      ),
    },
  ];

  return (
    <div>
      <Table
        dataSource={data}
        columns={columns}
        pagination={false}
        size="small"
        footer={() => (
          <Button type="dashed" onClick={handleAdd} icon={<PlusOutlined />}>
            添加参数
          </Button>
        )}
      />
      <Typography.Text type="secondary" className="mt-2 block">
        提示: 支持模板语法，如 {"{{ now() }}"}、{"{{ today() }}"}
      </Typography.Text>
    </div>
  );
};
```

- [ ] **Step 2: 提交**

```bash
cd frontend
git add src/components/workflows/DefaultInputEditor.tsx
git commit -m "feat(ui): add DefaultInputEditor component"
```

---

### Task 11: TriggerConfigEditor 主组件

**Files:**
- Create: `frontend/src/components/workflows/TriggerConfigEditor.tsx`

- [ ] **Step 1: 创建主编辑器组件**

```typescript
// frontend/src/components/workflows/TriggerConfigEditor.tsx
import React, { useEffect, useState } from "react";
import { Form, Radio, DatePicker, Switch, Button, Space, message, Card } from "antd";
import dayjs from "dayjs";
import { CronPresetSelector } from "./CronPresetSelector";
import { DefaultInputEditor } from "./DefaultInputEditor";
import { WorkflowTriggerAPI } from "@/services/workflow-trigger-api";
import type { TriggerConfig } from "@/types/workflow-trigger";

interface TriggerConfigEditorProps {
  workflowId: string;
}

export const TriggerConfigEditor: React.FC<TriggerConfigEditorProps> = ({
  workflowId,
}) => {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [triggerConfig, setTriggerConfig] = useState<TriggerConfig | null>(null);

  useEffect(() => {
    loadTriggerConfig();
  }, [workflowId]);

  const loadTriggerConfig = async () => {
    try {
      const config = await WorkflowTriggerAPI.getTrigger(workflowId);
      setTriggerConfig(config);
      form.setFieldsValue({
        type: config.type,
        enabled: config.enabled,
        cron_expression: config.cron_expression,
        execute_at: config.execute_at ? dayjs(config.execute_at) : null,
        default_input: config.default_input,
      });
    } catch (error) {
      // 404 表示没有触发配置，正常
      setTriggerConfig(null);
    }
  };

  const handleSave = async () => {
    try {
      const values = await form.validateFields();
      setLoading(true);

      const config: Partial<TriggerConfig> = {
        type: values.type,
        enabled: values.enabled,
        default_input: values.default_input || {},
      };

      if (values.type === "cron") {
        config.cron_expression = values.cron_expression;
      } else {
        config.execute_at = values.execute_at.toISOString();
      }

      await WorkflowTriggerAPI.updateTrigger(workflowId, config);
      message.success("触发配置已保存");
      await loadTriggerConfig();
    } catch (error) {
      message.error("保存失败");
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async () => {
    try {
      await WorkflowTriggerAPI.deleteTrigger(workflowId);
      message.success("触发配置已删除");
      setTriggerConfig(null);
      form.resetFields();
    } catch (error) {
      message.error("删除失败");
    }
  };

  const handleToggle = async (checked: boolean) => {
    try {
      await WorkflowTriggerAPI.toggleTrigger(workflowId, checked);
      message.success(checked ? "已启用" : "已禁用");
      await loadTriggerConfig();
    } catch (error) {
      message.error("操作失败");
    }
  };

  const triggerType = Form.useWatch("type", form);

  return (
    <Card title="定时触发配置">
      <Form
        form={form}
        layout="vertical"
        initialValues={{
          type: "cron",
          enabled: false,
          default_input: {},
        }}
      >
        <Form.Item name="type" label="触发类型">
          <Radio.Group>
            <Radio value="cron">Cron 重复执行</Radio>
            <Radio value="once">一次性执行</Radio>
          </Radio.Group>
        </Form.Item>

        {triggerType === "cron" && (
          <Form.Item
            name="cron_expression"
            label="执行频率"
            rules={[{ required: true, message: "请选择执行频率" }]}
          >
            <CronPresetSelector />
          </Form.Item>
        )}

        {triggerType === "once" && (
          <Form.Item
            name="execute_at"
            label="执行时间"
            rules={[{ required: true, message: "请选择执行时间" }]}
          >
            <DatePicker
              showTime
              format="YYYY-MM-DD HH:mm"
              className="w-full"
            />
          </Form.Item>
        )}

        <Form.Item name="default_input" label="默认输入参数">
          <DefaultInputEditor />
        </Form.Item>

        {triggerConfig && (
          <Form.Item label="状态">
            <Space>
              <Switch
                checked={triggerConfig.enabled}
                onChange={handleToggle}
              />
              <span>{triggerConfig.enabled ? "已启用" : "已禁用"}</span>
            </Space>
            {triggerConfig.next_trigger_at && (
              <div className="text-sm text-gray-500 mt-2">
                下次执行: {dayjs(triggerConfig.next_trigger_at).format("YYYY-MM-DD HH:mm")} (UTC)
              </div>
            )}
            {triggerConfig.last_triggered_at && (
              <div className="text-sm text-gray-500">
                上次执行: {dayjs(triggerConfig.last_triggered_at).format("YYYY-MM-DD HH:mm")} (UTC)
              </div>
            )}
          </Form.Item>
        )}

        <Form.Item>
          <Space>
            <Button type="primary" onClick={handleSave} loading={loading}>
              保存
            </Button>
            {triggerConfig && (
              <Button danger onClick={handleDelete}>
                删除触发配置
              </Button>
            )}
          </Space>
        </Form.Item>
      </Form>
    </Card>
  );
};
```

- [ ] **Step 2: 提交**

```bash
cd frontend
git add src/components/workflows/TriggerConfigEditor.tsx
git commit -m "feat(ui): add TriggerConfigEditor main component"
```

---

### Task 12: 集成到 Workflow 详情页

**Files:**
- Modify: `frontend/src/pages/WorkflowDetailPage.tsx`

- [ ] **Step 1: 添加定时触发 Tab**

```typescript
// frontend/src/pages/WorkflowDetailPage.tsx
// 在导入区添加
import { TriggerConfigEditor } from "@/components/workflows/TriggerConfigEditor";

// 在 Tabs 中添加新 Tab
<Tabs defaultActiveKey="basic">
  <TabPane tab="基本信息" key="basic">
    {/* 现有内容 */}
  </TabPane>

  <TabPane tab="节点设计" key="nodes">
    {/* 现有内容 */}
  </TabPane>

  {/* 新增 Tab */}
  <TabPane tab="定时触发" key="trigger">
    <TriggerConfigEditor workflowId={workflowId} />
  </TabPane>

  <TabPane tab="执行历史" key="history">
    {/* 现有内容 */}
  </TabPane>
</Tabs>
```

- [ ] **Step 2: 提交**

```bash
cd frontend
git add src/pages/WorkflowDetailPage.tsx
git commit -m "feat(ui): integrate TriggerConfigEditor into Workflow detail page"
```

---

## 阶段 5：测试与优化

### Task 13: 集成测试

**Files:**
- Create: `backend/tests/integration/test_scheduled_workflow_integration.py`

- [ ] **Step 1: 编写端到端集成测试**

```python
# backend/tests/integration/test_scheduled_workflow_integration.py
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, AsyncMock

from app.models.workflow import TriggerConfig
from app.services.trigger_scheduler_service import get_trigger_scheduler
from app.workers.tasks.scheduled_workflow import execute_scheduled_workflow


async def test_full_workflow_integration(test_db):
    """测试完整的定时触发流程"""
    db = test_db

    # 1. 创建 Workflow
    workflow_id = "wf_integration_test"
    await db["workflows"].insert_one({
        "_id": workflow_id,
        "name": "Integration Test Workflow",
        "status": "published",
        "trigger_config": {
            "type": "cron",
            "enabled": True,
            "cron_expression": "* * * * *",  # 每分钟
            "default_input": {"test_param": "test_value"},
        },
        "nodes": [
            {"node_id": "start", "type": "start", "config": {}},
            {"node_id": "end", "type": "end", "config": {}},
        ],
        "edges": [],
    })

    # 2. 启动调度器
    scheduler = get_trigger_scheduler()
    await scheduler.start()

    # 3. 验证触发配置已加载
    assert workflow_id in scheduler._workflows

    # 4. 手动触发执行
    result = execute_scheduled_workflow(workflow_id)
    assert result["status"] == "success"
    assert "task_id" in result

    # 5. 验证 Task 已创建
    task_id = result["task_id"]
    task_doc = await db["tasks"].find_one({"_id": task_id})
    assert task_doc is not None
    assert task_doc["workflow_id"] == workflow_id
    assert task_doc["input"] == {"test_param": "test_value"}

    # 6. 清理
    await scheduler.stop()
    await db["workflows"].delete_one({"_id": workflow_id})
    await db["tasks"].delete_one({"_id": task_id})
```

- [ ] **Step 2: 运行集成测试**

```bash
cd backend
uv run pytest tests/integration/test_scheduled_workflow_integration.py -v
```

Expected: PASS

- [ ] **Step 3: 提交**

```bash
cd backend
git add tests/integration/test_scheduled_workflow_integration.py
git commit -m "test(integration): add end-to-end scheduled workflow test"
```

---

### Task 14: 文档更新

**Files:**
- Modify: `docs/superpowers/specs/2026-07-07-workflow-scheduled-trigger-design.md`

- [ ] **Step 1: 更新文档状态**

```markdown
# 在文档顶部更新状态
**状态:** 已完成
**完成日期:** 2026-07-07
```

- [ ] **Step 2: 提交**

```bash
git add docs/superpowers/specs/2026-07-07-workflow-scheduled-trigger-design.md
git commit -m "docs: mark scheduled trigger spec as completed"
```

---

## 总结

### 文件清单

**后端新增 (6 files):**
- `backend/app/utils/template_renderer.py`
- `backend/app/services/trigger_scheduler_service.py`
- `backend/app/workers/tasks/scheduled_workflow.py`
- `backend/tests/models/test_workflow_trigger.py`
- `backend/tests/utils/test_template_renderer.py`
- `backend/tests/services/test_trigger_scheduler_service.py`
- `backend/tests/workers/test_scheduled_workflow.py`
- `backend/tests/api/v1/test_workflow_triggers.py`
- `backend/tests/integration/test_scheduled_workflow_integration.py`

**后端修改 (3 files):**
- `backend/app/models/workflow.py`
- `backend/app/api/v1/workflows.py`
- `backend/app/workers/celery_app.py`
- `backend/app/core/start.py`

**前端新增 (5 files):**
- `frontend/src/types/workflow-trigger.ts`
- `frontend/src/services/workflow-trigger-api.ts`
- `frontend/src/components/workflows/CronPresetSelector.tsx`
- `frontend/src/components/workflows/DefaultInputEditor.tsx`
- `frontend/src/components/workflows/TriggerConfigEditor.tsx`

**前端修改 (1 file):**
- `frontend/src/pages/WorkflowDetailPage.tsx`

### 实施顺序

1. **后端基础** (Tasks 1-2): 数据模型 + 工具函数
2. **后端调度** (Tasks 3-4): 服务 + Celery Task
3. **后端 API** (Tasks 5-6): 端点 + 启动集成
4. **前端实现** (Tasks 7-12): 类型 + API + 组件 + 集成
5. **测试优化** (Tasks 13-14): 集成测试 + 文档

### 验收标准

- [ ] 用户可以创建 Cron 类型的定时触发配置
- [ ] 用户可以创建一次性类型的定时触发配置
- [ ] 用户可以启用/禁用触发配置
- [ ] 用户可以配置默认输入参数（支持模板语法）
- [ ] Cron 触发按时间表自动执行
- [ ] 一次性触发在指定时间自动执行
- [ ] 前端可视化构建 Cron 表达式
- [ ] 触发配置可以删除
- [ ] 服务重启后触发配置自动恢复
- [ ] 执行失败不影响下次触发
- [ ] 所有测试通过

---

**计划完成**
