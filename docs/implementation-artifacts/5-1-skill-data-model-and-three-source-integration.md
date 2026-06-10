---
baseline_commit: NO_VCS
---

# Story 5.1: Skill 数据模型与文件上传注册

**Epic:** Epic 5 — 工具系统
**Status:** ready-for-dev
**Story ID:** 5-1
**Story Key:** 5-1-skill-data-model-and-three-source-integration

## Story

As a 开发者，
I want 通过上传 Markdown 文件或文件夹注册标准 Skill 定义到工具池，包含版本控制和输入输出 Schema，
So that Agent 在配置时可以从统一工具池选择工具，运行时按标准接口调用。

> ⚠️ **关键背景**：
> - 当前项目尚无工具系统代码（`backend/app/models/tool.py`、`backend/app/services/tool_service.py` 等均不存在）
> - 前端 `pages/tools-page.tsx` 和 `pages/skills-page.tsx` 已存在 Mock 版本
> - `engine/agent/builder.py` 的 `_resolve_tools()` 当前是空实现（`return []`），工具注入到 Agent 运行时在 Story 5-2
>
> 🔧 **范围说明**：
> 1. **Skill 格式** — 标准 Markdown + YAML frontmatter 格式（业界通用 Agent Skill 定义）
> 2. **注册方式** — 文件/文件夹上传（不做前端 Markdown 编辑器）
> 3. **本 Story 只做工具注册和管理**，不涉及工具执行（执行/沙箱/熔断是 Agent 执行引擎的事，在后续 Story）
> 4. **MCP 工具** 是独立来源（Story 5-3），本 Story 只聚焦 Markdown Skill

## Skill 格式规范

### Markdown Skill 文件格式

```markdown
---
name: query-device-status
description: 查询 MES 系统中的设备实时状态数据
parameters:
  - name: device_id
    type: string
    description: 设备 ID
    required: true
  - name: fields
    type: array
    items:
      type: string
    description: 需要查询的字段列表
    required: false
    default: ["status", "temperature"]
returns:
  type: object
  description: 设备状态信息
  properties:
    status:
      type: string
    temperature:
      type: number
---

# 查询设备状态

## 使用说明

通过 MES API 查询指定设备的实时状态。

## 调用示例

输入：
```json
{"device_id": "DEV-001", "fields": ["status", "temperature"]}
```

输出：
```json
{"status": "running", "temperature": 42.5}
```
```

### YAML Frontmatter 字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `name` | string | 是 | 工具唯一标识，kebab-case |
| `description` | string | 是 | 工具描述，Agent 据此判断何时使用 |
| `parameters` | array | 否 | 输入参数列表（JSON Schema 风格） |
| `parameters[].name` | string | 是 | 参数名 |
| `parameters[].type` | string | 是 | 参数类型（string/number/boolean/array/object/integer） |
| `parameters[].description` | string | 否 | 参数描述 |
| `parameters[].required` | boolean | 否 | 是否必填（默认 false） |
| `parameters[].default` | any | 否 | 默认值 |
| `returns` | object | 否 | 返回值描述（JSON Schema 风格） |
| `returns.type` | string | 否 | 返回类型 |

Markdown body 部分为工具的详细使用说明和示例，存入 `instructions` 字段供 Agent 推理参考。

## Acceptance Criteria

### AC1: Skill 数据模型定义
**Given** 平台需要管理 Skill 资源
**When** 审查 `backend/app/models/tool.py` 模块
**Then** 定义 `ToolStatus(StrEnum)` 枚举：`DRAFT` / `ACTIVE` / `INACTIVE`
**And** 定义 `Tool` Pydantic 模型包含字段：
  - `id: str`（格式 `tool_{ULID}`，alias `_id`）
  - `name: str`（唯一，来自 Skill 定义的 frontmatter）
  - `description: str`（来自 Skill 定义的 frontmatter）
  - `input_schema: dict[str, Any]`（从 parameters 自动生成的 JSON Schema）
  - `output_schema: dict[str, Any]`（从 returns 自动生成的 JSON Schema）
  - `instructions: str`（Markdown body 部分的详细说明）
  - `source: str`（工具来源标识，固定为 `"markdown"`，为后续 MCP 来源预留扩展）
  - `source_file: str`（上传的源文件名，如 `query-device-status.md`）
  - `status: ToolStatus`（默认 `DRAFT`）
  - `version: int`（默认 1，每次更新自增）
  - `tags: list[str]`（可选标签）
  - `created_at: str`（ISO 时间戳）
  - `updated_at: str`（ISO 时间戳）

### AC2: Skill Markdown 解析器
**Given** 开发者上传一个 Markdown Skill 文件
**When** 系统解析文件内容
**Then** 使用 YAML frontmatter 解析（`---` 分隔的元数据块）
**And** 提取 `name`、`description`、`parameters`、`returns` 字段
**And** 将 `parameters` 数组转换为标准 JSON Schema 格式的 `input_schema`
**And** 将 `returns` 对象转换为 JSON Schema 格式的 `output_schema`
**And** Markdown body（frontmatter 之后的内容）存入 `instructions` 字段
**And** 缺少必填字段（name 或 description）时抛出明确的解析错误
**And** frontmatter 格式错误（非合法 YAML）时抛出明确的解析错误

### AC3: 文件上传 API
**Given** 开发者通过 API 上传 Skill 文件
**When** 调用 `POST /api/v1/tools/upload`（multipart/form-data）
**Then** 支持上传**单个 `.md` 文件**
**And** 支持上传**包含多个 `.md` 文件的文件夹**（一次请求多个文件）
**And** 每个文件独立解析，成功的立即注册到工具池，失败的收集错误信息
**And** 返回批量结果：`{"created": [...], "errors": [...]}`
**And** 每个成功注册的工具包含完整 ToolResponse（id、name、description 等）
**And** 错误项包含文件名和具体错误原因
**And** 单文件大小限制 1MB，超出返回 413
**And** name 重复时返回冲突错误（不覆盖已有工具），冲突项放入 errors 列表

### AC4: Tool CRUD REST API
**Given** 平台后端已部署
**When** 开发者通过 API 操作 Tool
**Then** 提供以下端点：
  - `POST /api/v1/tools/upload` — 上传文件/文件夹注册工具（multipart）
  - `GET /api/v1/tools` — 查询工具列表（支持分页、按 status 过滤、按 name 搜索）
  - `GET /api/v1/tools/{tool_id}` — 获取工具详情
  - `PUT /api/v1/tools/{tool_id}` — 更新工具（如修改 status、tags，版本自增）
  - `DELETE /api/v1/tools/{tool_id}` — 删除工具（检查 Agent 引用）
**And** 所有端点需 JWT 认证 + RBAC（`tool:read` 给 GET，`tool:write` 给其他）
**And** name 唯一（在上传时校验）

### AC5: Tool 版本控制
**Given** 开发者编辑已存在的工具（修改 status 或 tags）
**When** 调用 PUT 更新
**Then** `version` 自动递增
**And** `updated_at` 更新为当前时间
**And** 删除被 Agent 引用的工具时返回 409，提示哪些 Agent 在引用

### AC6: 数据库索引
**Given** tools 集合写入 MongoDB
**When** 审查 `backend/app/db/indexes.py`
**Then** `tools` 集合创建索引：
  - `name` 唯一索引（`idx_tools_name`）
  - `status` 普通索引（`idx_tools_status`，用于状态过滤）

### AC7: 单元测试覆盖
**Given** 本 Story 的所有功能
**When** 运行测试套件
**Then** 覆盖以下场景：
  - Tool 模型字段验证（必填字段、枚举值）
  - Markdown 解析器（合法文件、缺字段、YAML 格式错误、body 提取）
  - JSON Schema 转换（parameters → input_schema，returns → output_schema）
  - 单文件上传成功
  - 多文件（文件夹）上传，部分成功部分失败
  - name 冲突处理
  - CRUD API 全流程（查询/更新/删除）
  - 版本自增逻辑
  - 删除被 Agent 引用的工具拦截
  - 分页、过滤、搜索
  - 运行 `cd backend && uv run pytest tests/models/test_tool.py tests/services/test_tool_service.py tests/api/test_tools.py tests/engine/test_skill_parser.py -v`

## Tasks / Subtasks

### 后端（Backend）

- [x] **T1: Tool 数据模型定义** (AC: #1)
  - [x] 新建 `backend/app/models/tool.py`
  - [x] 定义 `ToolStatus(StrEnum)` 枚举：`DRAFT` / `ACTIVE` / `INACTIVE`
  - [x] 定义 `Tool` Pydantic 模型（参考 `models/agent.py` 模式）
  - [x] 字段：id、name、description、input_schema、output_schema、instructions、source、source_file、status、version、tags、created_at、updated_at
  - [x] 使用 `ConfigDict(populate_by_name=True)`，`id` 字段 `alias="_id"`

- [x] **T2: Skill Markdown 解析器** (AC: #2)
  - [x] 新建 `backend/app/engine/tool/__init__.py`
  - [x] 新建 `backend/app/engine/tool/skill_parser.py`
  - [x] 实现 `parse_skill_markdown(content: str, filename: str = "") -> ParsedSkill`
  - [x] 使用 `pyyaml` 解析 YAML frontmatter
  - [x] 提取 name、description、parameters、returns
  - [x] 将 parameters 数组转换为 JSON Schema 格式的 input_schema
  - [x] 将 returns 对象转换为 JSON Schema 格式的 output_schema
  - [x] 提取 Markdown body 作为 instructions
  - [x] 校验必填字段（name、description），缺失抛出 `SkillParseError`
  - [x] 定义 `ParsedSkill` dataclass（name、description、input_schema、output_schema、instructions）
  - [x] 定义 `SkillParseError` 异常类（含 filename、detail）

- [x] **T3: Tool Schema 定义** (AC: #1, #4)
  - [x] 新建 `backend/app/schemas/tool.py`
  - [x] `ToolResponse` — 响应体（全部字段）
  - [x] `ToolListResponse` — 分页列表响应（参考 `AgentListResponse`）
  - [x] `ToolUpdate` — 更新请求（status、tags）
  - [x] `ToolUploadResult` — 单个上传结果（success/tool/error）
  - [x] `ToolUploadResponse` — 批量上传响应（created 列表 + errors 列表）

- [x] **T4: Tool Service 层** (AC: #4, #5)
  - [x] 新建 `backend/app/services/tool_service.py`
  - [x] `ToolService` 静态方法类，`COLLECTION = "tools"`
  - [x] `create_tool(parsed: ParsedSkill, source_file: str) -> dict` — 从解析结果创建（name 唯一校验、ID 生成、时间戳）
  - [x] `get_tool(tool_id) -> dict | None`
  - [x] `list_tools(page, page_size, status, name) -> tuple[list, total]`（分页+过滤+搜索）
  - [x] `update_tool(tool_id, ...) -> dict | None`（版本自增）
  - [x] `delete_tool(tool_id) -> bool`（检查 agents 集合的 tool_ids 引用）
  - [x] `find_by_name(name) -> dict | None`（上传时校验用）
  - [x] 参考 `services/agent_service.py` 模式

- [x] **T5: Tool API 端点** (AC: #3, #4)
  - [x] 新建 `backend/app/api/v1/tools.py`
  - [x] `router = APIRouter(prefix="/tools", tags=["tools"], dependencies=[Depends(get_current_user)])`
  - [x] `POST /tools/upload` — 文件/文件夹上传（`UploadFile = File(...)`，支持多文件 `List[UploadFile]`）
  - [x] `GET /tools` — 列表查询（分页、过滤、搜索，viewer+ 可访问）
  - [x] `GET /tools/{tool_id}` — 详情查询（viewer+）
  - [x] `PUT /tools/{tool_id}` — 更新工具（admin/developer）
  - [x] `DELETE /tools/{tool_id}` — 删除工具（admin/developer）
  - [x] 在 `backend/app/api/v1/router.py` 注册 tools_router

- [x] **T6: 数据库索引注册** (AC: #6)
  - [x] 修改 `backend/app/db/indexes.py`
  - [x] 在 `create_indexes()` 中添加 `tools` 集合索引
  - [x] `name` 唯一索引（`idx_tools_name`）
  - [x] `status` 普通索引（`idx_tools_status`）

- [x] **T7: 单元测试** (AC: #7)
  - [x] 新建 `backend/tests/models/test_tool.py` — 模型字段验证
  - [x] 新建 `backend/tests/engine/test_skill_parser.py` — Markdown 解析器测试
  - [x] 新建 `backend/tests/services/test_tool_service.py` — Service 层测试
  - [x] 新建 `backend/tests/api/test_tools.py` — API 端点测试（含文件上传）
  - [x] 运行 `cd backend && uv run pytest tests/models/test_tool.py tests/engine/test_skill_parser.py tests/services/test_tool_service.py tests/api/test_tools.py -v`

## Dev Notes

### 🔧 技术栈与约定

**后端（FastAPI + Motor + Pydantic）：**
- Python 包管理：**uv**（非 pip/poetry），`uv run pytest`
- Pydantic v2 BaseModel（参考 `models/agent.py`）
- Motor 异步 MongoDB（参考 `services/agent_service.py`）
- 日志：`loguru.logger`，结构化日志
- 测试：pytest + pytest-asyncio（mode=auto）
- 文件上传：FastAPI 的 `UploadFile` + `python-multipart`（已在依赖中）
- YAML 解析：`pyyaml`（需要 `uv add pyyaml`）

### 📐 关键架构约束

**数据模型参考 `models/agent.py` 模式：**
```python
# backend/app/models/tool.py
from enum import StrEnum
from typing import Any
from pydantic import BaseModel, ConfigDict, Field

class ToolStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    INACTIVE = "inactive"

class Tool(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    id: str = Field(alias="_id")
    name: str
    description: str = ""
    input_schema: dict[str, Any] = {}
    output_schema: dict[str, Any] = {}
    instructions: str = ""  # Markdown body
    source: str = "markdown"  # 预留扩展（markdown / mcp）
    source_file: str = ""
    status: ToolStatus = ToolStatus.DRAFT
    version: int = 1
    tags: list[str] = []
    created_at: str = ""
    updated_at: str = ""
```

**Skill Markdown 解析器示例（`engine/tool/skill_parser.py`）：**
```python
import re
import yaml
from dataclasses import dataclass

FRONTMATTER_PATTERN = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)", re.DOTALL)

@dataclass
class ParsedSkill:
    name: str
    description: str
    input_schema: dict
    output_schema: dict
    instructions: str

class SkillParseError(Exception):
    def __init__(self, filename: str, detail: str):
        self.filename = filename
        self.detail = detail
        super().__init__(f"{filename}: {detail}")

def parse_skill_markdown(content: str, filename: str = "") -> ParsedSkill:
    """Parse a Markdown Skill file with YAML frontmatter.

    Expected format:
        ---
        name: tool-name
        description: What this tool does
        parameters:
          - name: param1
            type: string
            required: true
        returns:
          type: object
        ---
        # Instructions for the agent...
    """
    match = FRONTMATTER_PATTERN.match(content)
    if not match:
        raise SkillParseError(filename, "Missing YAML frontmatter (--- delimiters)")

    yaml_block, body = match.groups()
    try:
        meta = yaml.safe_load(yaml_block) or {}
    except yaml.YAMLError as e:
        raise SkillParseError(filename, f"Invalid YAML: {e}") from e

    name = meta.get("name")
    description = meta.get("description")
    if not name or not description:
        raise SkillParseError(
            filename,
            f"Missing required field: {'name' if not name else 'description'}"
        )

    input_schema = _params_to_json_schema(meta.get("parameters", []))
    output_schema = _returns_to_json_schema(meta.get("returns", {}))

    return ParsedSkill(
        name=name,
        description=description,
        input_schema=input_schema,
        output_schema=output_schema,
        instructions=body.strip(),
    )

def _params_to_json_schema(params: list[dict]) -> dict:
    """Convert parameters array to JSON Schema object."""
    properties = {}
    required = []
    for p in params:
        pname = p.get("name", "")
        properties[pname] = {
            "type": p.get("type", "string"),
            "description": p.get("description", ""),
        }
        if "default" in p:
            properties[pname]["default"] = p["default"]
        if p.get("required"):
            required.append(pname)
    schema = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema

def _returns_to_json_schema(returns: dict) -> dict:
    """Convert returns object to JSON Schema."""
    if not returns:
        return {"type": "string"}
    return {"type": returns.get("type", "string"),
            "description": returns.get("description", ""),
            **({"properties": returns["properties"]} if "properties" in returns else {})}
```

**API 文件上传端点示例：**
```python
from fastapi import UploadFile, File

@router.post("/upload", response_model=ToolUploadResponse)
async def upload_tools(
    files: list[UploadFile] = File(..., description="Skill Markdown 文件（支持多文件）"),
    _: UserResponse = Depends(require_any_role("admin", "developer")),
) -> ToolUploadResponse:
    """Upload one or more Skill Markdown files to register tools."""
    created = []
    errors = []
    for f in files:
        content = await f.read()
        if len(content) > 1_000_000:
            errors.append({"filename": f.filename, "error": "File too large (>1MB)"})
            continue
        try:
            parsed = parse_skill_markdown(content.decode(), f.filename or "")
            existing = await ToolService.find_by_name(parsed.name)
            if existing:
                errors.append({"filename": f.filename, "error": f"Tool '{parsed.name}' already exists"})
                continue
            doc = await ToolService.create_tool(parsed, f.filename or "")
            created.append(_doc_to_response(doc))
        except SkillParseError as e:
            errors.append({"filename": e.filename, "error": e.detail})
    return ToolUploadResponse(created=created, errors=errors)
```

**Service 层参考 `services/agent_service.py` 模式：**
```python
# backend/app/services/tool_service.py
from app.db.mongodb import get_database
from app.models.base import generate_id, utc_now
from app.engine.tool.skill_parser import ParsedSkill

class ToolService:
    COLLECTION = "tools"

    @classmethod
    def _collection(cls):
        return get_database()[cls.COLLECTION]

    @staticmethod
    async def create_tool(parsed: ParsedSkill, source_file: str = "") -> dict:
        doc = {
            "_id": generate_id("tool"),
            "name": parsed.name,
            "description": parsed.description,
            "input_schema": parsed.input_schema,
            "output_schema": parsed.output_schema,
            "instructions": parsed.instructions,
            "source": "markdown",
            "source_file": source_file,
            "status": "draft",
            "version": 1,
            "tags": [],
            "created_at": utc_now().isoformat(),
            "updated_at": utc_now().isoformat(),
        }
        await ToolService._collection().insert_one(doc)
        return doc
```

**router.py 注册：**
```python
# backend/app/api/v1/router.py
from app.api.v1.tools import router as tools_router
api_v1_router.include_router(tools_router)
```

### 📐 工具注册到 Agent 的完整链路（供后续 Story 参考）

本 Story 只做 **①注册和管理** 部分，后续链路在 Story 5-2 实现：

```
①注册（本 Story 5-1）：
  上传 .md → skill_parser 解析 → tools 集合存储

②配置（已存在）：
  Agent.tool_ids = ["tool_xxx", ...]（Agent 编辑页面已实现）

③运行时注入（Story 5-2）：
  builder._resolve_tools(agent) → 从 tool_ids 查询 tools 集合
    → 转为 LangChain StructuredTool
    → llm.bind_tools(all_tools)

④执行（Story 5-2，属于 Agent 执行引擎）：
  react_executor → LLM 返回 tool_calls → _execute_tool()
    → 超时控制 / 错误处理
```

### ⚠️ 回归防护

**不能破坏的现有行为：**
1. 现有 API 端点（agents、models、auth 等）正常工作
2. 现有数据库索引创建逻辑
3. 现有测试套件全部通过
4. Agent 的 `tool_ids` 字段语义不变（Tool ID 作为字符串引用）

**前端不修改：** 本 Story 纯后端，前端 tools-page.tsx 和 skills-page.tsx 仍是 Mock 数据，后续 Story 集成。

### 📁 文件清单

**后端新建的文件：**
- `backend/app/models/tool.py` — Tool 数据模型
- `backend/app/schemas/tool.py` — Tool Schema 定义
- `backend/app/services/tool_service.py` — Tool Service 层
- `backend/app/api/v1/tools.py` — Tool API 端点（含文件上传）
- `backend/app/engine/tool/__init__.py` — tool 引擎模块
- `backend/app/engine/tool/skill_parser.py` — Markdown Skill 解析器
- `backend/tests/models/test_tool.py` — 模型测试
- `backend/tests/engine/test_skill_parser.py` — 解析器测试
- `backend/tests/services/test_tool_service.py` — Service 测试
- `backend/tests/api/test_tools.py` — API 测试

**后端修改的文件：**
- `backend/app/api/v1/router.py` — 注册 tools_router
- `backend/app/db/indexes.py` — 添加 tools 集合索引
- `backend/pyproject.toml` — 添加 `pyyaml` 依赖

**不修改的文件：**
- `backend/app/models/agent.py` — Agent 模型不变
- `backend/app/api/v1/agents.py` — Agent API 不变
- `backend/app/services/agent_service.py` — Agent Service 不变
- `backend/app/engine/agent/builder.py` — `_resolve_tools()` 在 Story 5-2 实现

### 🚫 本 Story 不做的事

- **不做工具执行** — Tool 的实际调用、超时、沙箱在 Story 5-2（Agent 执行引擎层）
- **不做前端 Markdown 编辑器** — 只做文件/文件夹上传
- **不做 MCP 工具** — MCP 来源的工具在 Story 5-3
- **不做 builder._resolve_tools() 实现** — 工具注入 Agent 运行时在 Story 5-2
- **不做 Git 拉取** — Git 仓库拉取 Skill 在后续 Story
- **不做前端集成** — 前端仍是 Mock 数据

### Dependencies to Add

- `pyyaml` — YAML frontmatter 解析（`uv add pyyaml`）

### Project Structure Notes

- 后端测试目录：
  - `tests/api/` — API 端点测试（已有 test_agents.py 等参考）
  - `tests/services/` — Service 层测试
  - `tests/models/` — 模型测试
  - `tests/engine/` — 引擎模块测试（已有 test_depth_guard.py 等）
- 测试使用 pytest-asyncio，mode=auto
- API 测试使用 FastAPI TestClient（参考 `tests/api/test_agents.py`）

### References

- [Source: docs/planning-artifacts/prd.md#FR-13] — Skill 管理功能需求（三种来源）
- [Source: docs/planning-artifacts/architecture.md#FR-13/14/15] — 工具系统架构规划
- [Source: docs/planning-artifacts/architecture.md#engine/tool] — 工具引擎目录规划（registry/skill_runner/mcp_client/sandbox）
- [Source: backend/app/engine/agent/builder.py:120-127] — `_resolve_tools()` 当前空实现（Story 5-2 实现点）
- [Source: backend/app/engine/agent/builder.py:94-117] — `_make_react_node` 工具注入逻辑
- [Source: backend/app/models/agent.py] — Agent 模型模式参考（含 tool_ids 字段）
- [Source: backend/app/schemas/agent.py] — Agent Schema 模式参考
- [Source: backend/app/services/agent_service.py] — Agent Service 模式参考
- [Source: backend/app/api/v1/agents.py] — Agent API 模式参考
- [Source: backend/app/db/indexes.py] — 索引注册模式参考
- [Source: frontend/src/pages/tools-page.tsx] — 前端工具页（Mock，不修改）
- [Source: frontend/src/pages/skills-page.tsx] — 前端 Skill 页（Mock，不修改）

## Dev Agent Record

### Agent Model Used

claude-opus-4-6（Claude Code CLI）

### Debug Log References

- 2026-06-10: 修复 `test_tool_service.py` 中 Motor mock 的使用问题（`AsyncMock` → `MagicMock` 用于 cursor 返回值）
- 2026-06-10: 修复 `test_tools.py` 中 `parse_skill_markdown` mock patch 路径（`app.api.v1.tools` → `app.engine.tool.skill_parser`，因实际代码用 local import）

### Completion Notes List

- ✅ **T1: Tool 数据模型** — 定义 `ToolStatus(StrEnum)` + `Tool` Pydantic 模型，`_id` alias、自动 ID 生成、时间戳默认值。字段长度约束（name 1-100、description max 500）
- ✅ **T2: Skill 解析器** — YAML frontmatter 正则解析 + `pyyaml` 安全加载，`_params_to_json_schema` 支持 items/default/enum，`_returns_to_json_schema` 支持 properties/items。错误处理覆盖：缺 frontmatter、YAML 非法、非 dict 类型、缺 name/description
- ✅ **T3: Schema 定义** — `ToolResponse`、`ToolListResponse`、`ToolUpdate`、`ToolUploadErrorItem`、`ToolUploadResponse`，响应模型完整
- ✅ **T4: Service 层** — `ToolService` 包含 `create_tool_from_parsed`（含 ConflictError 处理）、`get_tool`、`list_tools`（分页+regex 搜索）、`update_tool`（version 自增）、`delete_tool`（Agent 引用检查）、`find_by_name`
- ✅ **T5: API 端点** — 5 个端点全部实现：`POST /upload`、`GET /tools`、`GET /tools/{id}`、`PUT /tools/{id}`、`DELETE /tools/{id}`。JWT + RBAC（`require_any_role`）配置正确
- ✅ **T6: 索引注册** — `idx_tools_name`(unique) + `idx_tools_status` 已添加到 `db/indexes.py`
- ✅ **T7: 单元测试** — 58 个测试全部通过（model 7 + parser 21 + service 12 + api 18）。覆盖：字段验证、枚举、frontmatter 解析、JSON Schema 转换、上传成功/失败/多文件/名称冲突、CRUD 全流程、分页/过滤/搜索、版本自增、Agent 引用拦截

**测试结果：**
```
tests/models/test_tool.py .......                  [ 12%]
tests/engine/test_skill_parser.py ..................... [ 48%]
tests/services/test_tool_service.py ............     [ 68%]
tests/api/test_tools.py ..................            [100%]
58 passed, 1 warning in 0.07s
```

**回归测试：** 全套 363 测试通过（排除 test_agent_execution.py 的 4 个预先存在的失败，与本 Story 无关）

### File List

**后端新建的文件：**
- `backend/app/models/tool.py` — Tool 数据模型（ToolStatus 枚举 + Tool Pydantic 模型）
- `backend/app/schemas/tool.py` — Tool Schema 定义（5 个响应/请求模型）
- `backend/app/services/tool_service.py` — Tool Service 层（CRUD + 名称校验 + 引用检查）
- `backend/app/api/v1/tools.py` — Tool API 端点（upload + CRUD，JWT + RBAC）
- `backend/app/engine/tool/__init__.py` — tool 引擎模块初始化
- `backend/app/engine/tool/skill_parser.py` — Markdown Skill 解析器（YAML frontmatter + JSON Schema 转换）
- `backend/tests/models/test_tool.py` — 模型字段验证测试（7 个）
- `backend/tests/engine/test_skill_parser.py` — 解析器测试（21 个）
- `backend/tests/services/test_tool_service.py` — Service 层测试（12 个）
- `backend/tests/api/test_tools.py` — API 端点测试（18 个，含文件上传、CRUD、RBAC）

**后端修改的文件：**
- `backend/app/api/v1/router.py` — 注册 tools_router
- `backend/app/db/indexes.py` — 添加 tools 集合索引（idx_tools_name unique + idx_tools_status）
- `backend/pyproject.toml` — 添加 `pyyaml>=6.0.3` 依赖

## Change Log

- 2026-06-10: Story 5-1 创建 — Skill 数据模型与三种来源集成
- 2026-06-10: Story 5-1 重写 — 聚焦标准 Skill Markdown 格式 + 文件上传注册
- 2026-06-10: Story 5-1 实现完成 — 全部 7 个 task 完成，58 个测试通过，状态推进到 review

## Status

**Status:** review
