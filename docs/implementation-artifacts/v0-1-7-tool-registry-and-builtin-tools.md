---
baseline_commit: v0.1-2
---

# Story v0.1-7: ToolRegistry 与内置工具

**Epic:** v0.1 — Harness 拆包与基础
**Status:** done (实施完成，commit `8a6f42a`；ToolRegistry + CommunityTool 协议，builtin.py 占位待 v0.2-2/v0.2-x)
**Depends on:** v0.1-2

## Story

As a Agent Flow 维护者，
I want 在 harness 内实现 ToolRegistry 统一工具接入协议 + 4 个内置工具（bash/read/write/write_to_output），
So that Agent 执行时通过 `registry.resolve(agent_doc)` 获取工具列表，替代当前 `_resolve_tools` 的四段拼装，建立清晰的工具扩展基线。

## Acceptance Criteria

- **AC1:** `packages/harness/src/agent_flow_harness/tools/registry.py` 实现 `ToolRegistry` 类，包含 `register(tool)` / `resolve(agent_doc)` / `list_community_tools()` 方法
- **AC2:** `ToolRegistry` 为单进程单例（全局可见），应用层启动时注册工具，Agent 执行时按 `agent_doc["tools"]` 过滤
- **AC3:** `packages/harness/src/agent_flow_harness/tools/builtin.py` 实现 4 个内置工具：
  - `bash` — 执行 shell 命令（带超时/工作目录隔离）
  - `read` — 读取文件内容（支持文本/二进制）
  - `write` — 写入文件（支持覆盖/追加）
  - `write_to_output` — 写入用户可见输出（非文件）
- **AC4:** `packages/harness/src/agent_flow_harness/tools/community.py` 定义 `CommunityTool` Protocol：
  - `name: str`
  - `description: str`
  - `config_schema: type[BaseModel]`（Pydantic 配置 schema）
  - `enabled_by_default: bool = False`
  - `build(config: BaseModel) -> BaseTool`
- **AC5:** 从 `backend/app/engine/tools/` 迁移 4 个内置工具代码到 harness，**行为完全一致**
- **AC6:** `engine/react.py`（v0.1-2 实现）改为通过 `ToolRegistry.resolve(agent_doc)` 获取工具列表，替代原 `_resolve_tools` 四段拼装
- **AC7:** `agent_doc["tools"]` 配置字段解析正确：
  ```python
  agent_doc["tools"] = [
      {"name": "bash", "enabled": True},
      {"name": "tavily_search", "enabled": True, "config": {"api_key_env": "TAVILY_API_KEY"}},
      {"name": "skill:code-review", "enabled": True},
      {"name": "mcp:github", "enabled": False},
  ]
  ```
- **AC8:** `resolve(agent_doc)` 按 `enabled` 字段过滤，返回 `list[BaseTool]`
- **AC9:** `CommunityTool` 协议支持第三方扩展：任何 PyPI 包注册 `CommunityTool` 即可被 harness 识别
- **AC10:** 提供 15+ 单元测试覆盖：
  - `ToolRegistry.register()` 注册内置工具
  - `ToolRegistry.resolve()` 按 agent_doc 过滤
  - `ToolRegistry.resolve()` 跳过 `enabled: False` 的工具
  - `ToolRegistry.list_community_tools()` 返回已注册的社区工具
  - 4 个内置工具各自的行为测试（bash/read/write/write_to_output）
  - `CommunityTool` 协议实现测试（mock 一个第三方工具）
- **AC11:** 应用层 `backend/app/engine/tools/` 删除已迁移代码，改为 `from agent_flow_harness.tools import ToolRegistry, builtin`
- **AC12:** 应用层全部 169+ 测试通过，harness 15+ 测试通过，无回归

## Tasks / Subtasks

- [ ] **Story 文件** — 创建本文档
- [ ] **ToolRegistry 类** — 实现 `register()` / `resolve()` / `list_community_tools()`
- [ ] **单例模式** — 全局 `TOOL_REGISTRY = ToolRegistry()` 实例
- [ ] **builtin.py 迁移** — 从 `backend/app/engine/tools/bash.py` 复制 `bash_tool`
- [ ] **builtin.py 迁移** — 从 `backend/app/engine/tools/file_ops.py` 复制 `read_tool` / `write_tool`
- [ ] **builtin.py 迁移** — 从 `backend/app/engine/tools/output.py` 复制 `write_to_output_tool`
- [ ] **CommunityTool 协议** — 定义 `CommunityTool` Protocol + `config_schema` / `build()` 方法
- [ ] **resolve 逻辑** — 按 `agent_doc["tools"]` 过滤 + 实例化 CommunityTool
- [ ] **react.py 集成** — 改为 `registry.resolve(agent_doc)` 获取工具
- [ ] **删除旧代码** — 删除 `backend/app/engine/tools/` 已迁移文件
- [ ] **15+ 单元测试** — 覆盖注册/解析/内置工具/CommunityTool
- [ ] **Run & Verify** — 应用层全部 169+ 测试通过，harness 15+ 测试通过，无回归

## Dev Notes

### 核心约束（绝不能违反）

**harness 不可依赖以下**（应用层基础设施）：

```
❌ fastapi / uvicorn / starlette
❌ motor / pymongo / mongoengine / beanie
❌ celery / redis / kombu
❌ app.models.* / app.services.* / app.api.*
```

**harness 允许依赖**：

```
✅ langgraph >= 1.0.8
✅ langchain-core / langchain-* (官方库)
✅ pydantic >= 2.0
✅ structlog
✅ typing-extensions
```

### ToolRegistry 设计

**单例模式**（与现状 `ToolRegistry` 一致）：

```python
# packages/harness/src/agent_flow_harness/tools/registry.py
from typing import Union
from langchain_core.tools import BaseTool
from agent_flow_harness.tools.community import CommunityTool

class ToolRegistry:
    """
    工具的全局注册中心。
    应用层启动时：registry.register(MyTool())
    Agent 执行时：ctx = registry.resolve(agent_doc)
    """
    def __init__(self):
        self._tools: dict[str, BaseTool] = {}
        self._community_tools: dict[str, CommunityTool] = {}

    def register(self, tool: Union[BaseTool, CommunityTool]) -> None:
        """注册工具。BaseTool 直接存入；CommunityTool 存入待后续 build。"""
        if isinstance(tool, CommunityTool):
            self._community_tools[tool.name] = tool
        else:
            self._tools[tool.name] = tool

    def resolve(self, agent_doc: dict) -> list[BaseTool]:
        """
        按 agent_doc["tools"] 字段过滤，返回最终工具列表。

        agent_doc["tools"] = [
            {"name": "bash", "enabled": True},
            {"name": "tavily_search", "enabled": True, "config": {...}},
            {"name": "skill:code-review", "enabled": True},
            {"name": "mcp:github", "enabled": False},  # 跳过
        ]
        """
        tool_configs = agent_doc.get("tools", [])
        result = []

        for tool_config in tool_configs:
            if not tool_config.get("enabled", True):
                continue

            name = tool_config["name"]

            # 1. 优先查找内置工具
            if name in self._tools:
                result.append(self._tools[name])

            # 2. 其次查找社区工具（需要 build）
            elif name in self._community_tools:
                community_tool = self._community_tools[name]
                config_data = tool_config.get("config", {})
                config = community_tool.config_schema(**config_data)
                built_tool = community_tool.build(config)
                result.append(built_tool)

            # 3. 未找到 — 记录警告，跳过
            else:
                logger.warning(f"Tool '{name}' not found in registry, skipping")

        return result

    def list_community_tools(self) -> list[CommunityTool]:
        """返回所有已注册的社区工具（未 build）。"""
        return list(self._community_tools.values())

# 全局单例
TOOL_REGISTRY = ToolRegistry()
```

### 内置工具迁移

**从 `backend/app/engine/tools/` 迁移 4 个工具：**

| 源文件 | 工具名 | 行为 |
|--------|--------|------|
| `bash.py` | `bash` | 执行 shell 命令（subprocess.run + 超时 + 工作目录） |
| `file_ops.py` | `read` | 读取文件（支持文本/二进制 + 路径校验） |
| `file_ops.py` | `write` | 写入文件（覆盖/追加 + 路径校验） |
| `output.py` | `write_to_output` | 写入用户可见输出（非文件，存入 state） |

**迁移要点：**
- 保留原有行为（参数校验、异常处理、返回值格式）
- 替换 `from app.engine.sandbox import ...` 为 `from agent_flow_harness.sandbox import ...`（v0.2 实现）
- v0.1-7 阶段 sandbox 仍通过 `config["configurable"]["sandbox"]` 注入

**builtin.py 结构：**

```python
# packages/harness/src/agent_flow_harness/tools/builtin.py
from langchain_core.tools import tool
from agent_flow_harness.tools.sandbox import SandboxProvider

@tool
async def bash(
    command: str,
    timeout: int = 30,
    workspace: str | None = None,
) -> str:
    """
    Execute a shell command.

    Args:
        command: The shell command to execute.
        timeout: Maximum execution time in seconds (default: 30).
        workspace: Working directory (default: sandbox workspace).

    Returns:
        Command output (stdout + stderr).
    """
    sandbox: SandboxProvider = get_sandbox_from_context()
    result = await sandbox.execute(command, timeout=timeout, workspace=workspace)
    return f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}\nexit_code: {result.exit_code}"

@tool
async def read(file_path: str, binary: bool = False) -> str:
    """Read a file."""
    ...

@tool
async def write(file_path: str, content: str, append: bool = False) -> str:
    """Write to a file."""
    ...

@tool
async def write_to_output(content: str) -> str:
    """Write user-visible output (not a file)."""
    ...
```

### CommunityTool 协议

**第三方可实现的工具协议：**

```python
# packages/harness/src/agent_flow_harness/tools/community.py
from typing import Protocol
from pydantic import BaseModel
from langchain_core.tools import BaseTool

class CommunityTool(Protocol):
    """
    第三方可实现的工具协议。
    任何 PyPI 包注册 CommunityTool 即可被 harness 识别。
    """
    name: str
    description: str
    config_schema: type[BaseModel]  # Pydantic 配置 schema
    enabled_by_default: bool = False

    def build(self, config: BaseModel) -> BaseTool:
        """根据配置构建工具实例。"""
        ...
```

**示例：第三方 tavily_search 工具**

```python
# agent_flow_harness_community_tavily.py
from pydantic import BaseModel, Field
from langchain_core.tools import BaseTool, tool
from agent_flow_harness.tools.community import CommunityTool

class TavilyConfig(BaseModel):
    api_key_env: str = Field(default="TAVILY_API_KEY")

class TavilySearchTool(CommunityTool):
    name = "tavily_search"
    description = "Search the web using Tavily API"
    config_schema = TavilyConfig
    enabled_by_default = False

    def build(self, config: TavilyConfig) -> BaseTool:
        import os
        api_key = os.environ.get(config.api_key_env)
        if not api_key:
            raise ValueError(f"Environment variable {config.api_key_env} not set")

        @tool
        def tavily_search(query: str) -> str:
            """Search the web."""
            # 调用 Tavily API
            ...

        return tavily_search
```

### Agent 工具配置

**agent_doc["tools"] 字段：**

```python
agent_doc["tools"] = [
    {"name": "bash", "enabled": True},
    {"name": "read", "enabled": True},
    {"name": "write", "enabled": True},
    {"name": "write_to_output", "enabled": True},
    {"name": "tavily_search", "enabled": True, "config": {"api_key_env": "TAVILY_API_KEY"}},
    {"name": "skill:code-review", "enabled": True},
    {"name": "mcp:github", "enabled": False},  # 禁用
]
```

**解析逻辑：**
1. 遍历 `agent_doc["tools"]`
2. 跳过 `enabled: False` 的工具
3. 按 `name` 查找 `ToolRegistry`：
   - 内置工具（bash/read/write/write_to_output）→ 直接返回
   - 社区工具（tavily_search）→ 用 `config` 调用 `build()`
   - skill: / mcp: 前缀 → v0.2 实现（skill.py / mcp.py）
4. 返回 `list[BaseTool]`

### 与当前 `_resolve_tools` 的对比

**当前实现（`backend/app/engine/agent/builder.py`）：**

```python
def _resolve_tools(agent_doc: dict) -> list[BaseTool]:
    tools = []

    # 1. 内置工具
    if agent_doc.get("use_bash"):
        tools.append(bash_tool)
    if agent_doc.get("use_read"):
        tools.append(read_tool)
    # ...

    # 2. Skill 工具
    for skill_id in agent_doc.get("skills", []):
        skill = db.skills.find_one({"_id": skill_id})
        tools.extend(skill_to_tools(skill))

    # 3. MCP 工具
    for mcp_id in agent_doc.get("mcp_servers", []):
        mcp = db.mcp_servers.find_one({"_id": mcp_id})
        tools.extend(mcp_to_tools(mcp))

    # 4. Task 工具
    tools.extend(task_management_tools)

    return tools
```

**v0.1-7 新实现：**

```python
def _resolve_tools(agent_doc: dict) -> list[BaseTool]:
    from agent_flow_harness.tools import TOOL_REGISTRY
    return TOOL_REGISTRY.resolve(agent_doc)
```

**优势：**
- 代码从 50+ 行减少到 3 行
- 工具注册集中化（应用层启动时一次注册）
- 支持社区工具扩展（第三方可实现 CommunityTool）
- agent_doc 配置统一（不再分散在多个字段）

### 测试组织（v0.1-7）

```
packages/harness/tests/
├── tools/
│   ├── test_registry.py         # 10+ 用例
│   │   ├── test_register_builtin_tool
│   │   ├── test_register_community_tool
│   │   ├── test_resolve_enabled_tools
│   │   ├── test_resolve_skip_disabled_tools
│   │   ├── test_resolve_build_community_tool
│   │   ├── test_resolve_tool_not_found_warning
│   │   ├── test_list_community_tools
│   │   ├── test_global_singleton
│   │   └── test_resolve_empty_tools_config
│   ├── test_builtin_bash.py     # 2 用例
│   ├── test_builtin_read.py     # 2 用例
│   ├── test_builtin_write.py    # 2 用例
│   └── test_community.py        # 2 用例（mock 第三方工具）
```

### 兼容性

- `ToolRegistry.resolve()` 的**对外行为**（输入 agent_doc，输出 list[BaseTool]）**完全保持**
- 应用层 API（`POST /api/v1/sessions/{id}/messages`）**无变化**
- 前端 SSE 事件 schema 由 v0.1-3 继续保证不变

### 已知风险

| 风险 | 缓解 |
|------|------|
| 单例模式不支持多租户 | v0.1-7 不修复；v0.2 考虑 `ToolRegistry(scope="agent")` |
| 工具配置错误（typo）静默失败 | `resolve()` 记录 warning 日志，不抛异常 |
| 内置工具行为变更 | 保留原有测试，迁移后逐一对比 |

## Dev Agent Record

### Implementation Plan

1. 创建 `packages/harness/src/agent_flow_harness/tools/` 目录
2. 实现 `ToolRegistry` 类（register / resolve / list_community_tools）
3. 实现 4 个内置工具（bash / read / write / write_to_output）
4. 定义 `CommunityTool` Protocol
5. 从 `backend/app/engine/tools/` 迁移代码
6. 更新 `engine/react.py` 改为 `TOOL_REGISTRY.resolve(agent_doc)`
7. 删除 `backend/app/engine/tools/` 已迁移文件
8. 编写 15+ 单元测试
9. 运行完整测试套件

### Debug Log



### Completion Notes



## File List

**新增文件:**
- `packages/harness/src/agent_flow_harness/tools/__init__.py`
- `packages/harness/src/agent_flow_harness/tools/registry.py` — ToolRegistry 类
- `packages/harness/src/agent_flow_harness/tools/builtin.py` — 4 个内置工具
- `packages/harness/src/agent_flow_harness/tools/community.py` — CommunityTool Protocol
- `packages/harness/tests/tools/__init__.py`
- `packages/harness/tests/tools/test_registry.py` — 10+ 测试
- `packages/harness/tests/tools/test_builtin_bash.py`
- `packages/harness/tests/tools/test_builtin_read.py`
- `packages/harness/tests/tools/test_builtin_write.py`
- `packages/harness/tests/tools/test_community.py`

**修改文件:**
- `packages/harness/src/agent_flow_harness/__init__.py` — re-export ToolRegistry / CommunityTool
- `packages/harness/src/agent_flow_harness/engine/react.py` — 改为 TOOL_REGISTRY.resolve(agent_doc)
- `packages/app/pyproject.toml` — 无变化（已在 v0.1-1 添加 Git 依赖）

**删除文件:**
- `backend/app/engine/tools/__init__.py`
- `backend/app/engine/tools/bash.py`
- `backend/app/engine/tools/file_ops.py`
- `backend/app/engine/tools/output.py`

## Change Log

- 2026-06-23: Story v0.1-7 创建 — ToolRegistry 与内置工具（ready-for-dev，依赖 v0.1-2）

## Status

**Status:** ready-for-dev
