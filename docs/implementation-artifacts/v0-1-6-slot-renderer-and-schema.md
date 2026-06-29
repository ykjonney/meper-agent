---
baseline_commit: v0.1-5
---

# Story v0.1-6: Slot 渲染协议与 Renderer

**Epic:** v0.1 — Harness 拆包与基础
**Status:** done (实施完成，commit `8edcb04`；6 段式 system prompt Slot 渲染器)
**Depends on:** v0.1-5

## Story

As a Agent Flow 维护者,
I want 在 harness 内实现 `SlotDef` / `SLOT_SCHEMA` / `SlotRenderer` + `render_system_prompt_full`，并把现状 `backend/app/engine/agent/slot_renderer.py` + `prompt_template.py` 的能力（含 `build_tool_declaration` 协同）整体迁移到 harness，
So that Agent 启动时按固定 slot 顺序（role → task → constraints → context → output_format → tool_declaration）拼装 system prompt，与 v0.1-5 的 Middleware 边界清晰（**Renderer 在 Agent 启动时构造 system prompt**；**Middleware 在每次 LLM 调用前动态注入**）。

## Acceptance Criteria

- **AC1:** `packages/harness/src/agent_flow_harness/slots/schema.py` 定义 `SlotDef` Pydantic BaseModel（`name` / `label` / `required` / `description`），并声明 `SLOT_SCHEMA: list[SlotDef]`（固定 5 段：**role → task → constraints → context → output_format**）
- **AC2:** `packages/harness/src/agent_flow_harness/slots/renderer.py` 实现 `render_system_prompt_full(agent_doc, *, node_slot_overrides=None, strict=True) -> str` 异步函数
- **AC3:** 渲染顺序**严格固定**：role → task → constraints → context → output_format → tool_declaration（最后追加 tool 声明）
- **AC4:** slot 渲染格式：`【{label}】\n{value}`，**双换行**（`\n\n`）分隔每段
- **AC5:** `node_slot_overrides: dict[str, str] | None` 支持在 workflow 节点级别覆盖 slot 值（如 `{"role": "You are a ninja."}`）；覆盖优先级最高
- **AC6:** slot 来源优先级（**从高到低**）：node_slot_overrides > agent_doc["prompt_slots"][name] > 留空
- **AC7:** 必填 slot (`required=True`) 缺失时：
  - `strict=True`（默认）→ 抛 `ValueError("必填 Prompt Slot 缺失: ...")`，与现状 `bcdebc5` 行为一致
  - `strict=False` → 写占位段 `【{label}】\n（未配置）`，不阻断渲染
- **AC8:** 5 段中 `required` 字段：role=True, task=True, constraints=False, context=False, output_format=False（与现状 `SLOT_SCHEMA` 保持一致）
- **AC9:** 工具声明调用 `build_tool_declaration(agent_doc)`，**当前**为协议（注入点 — v0.1-6 在 harness 内定义协议签名；具体 tool 列表拼装在 v0.1-7 ToolRegistry + v0.1-1+ 跨 Story 实现）
- **AC10:** `render_system_prompt_full` 顶层 await 友好（async），**不依赖 MongoDB / 任何 IO**（v0.1-6 只接收 `agent_doc: dict` 纯数据）— 与现状 `slot_renderer` 一致
- **AC11:** `packages/harness/src/agent_flow_harness/slots/__init__.py` 通过 `__all__` 导出 `SlotDef` / `SLOT_SCHEMA` / `render_system_prompt_full` / `render_system_prompt_simple`
- **AC12:** 提供 25+ 单元测试覆盖：SLOT_SCHEMA 字段、5 段固定顺序、空 slot / 部分 slot、node_slot_overrides 覆盖、required 缺失抛错（strict=True）/ 占位（strict=False）、tool_declaration 协同、format 格式（双换行 / `【label】`）
- **AC13:** 提供 1 个**迁移兼容测试**：从 `backend/app/engine/agent/slot_renderer.py` 的 `render_system_prompt_full` 输入/输出**逐字段对比一致**

## Tasks / Subtasks

- [ ] **Story 文件** — 创建本文档
- [ ] **SlotDef / SLOT_SCHEMA** — Pydantic model + 5 段固定 schema
- [ ] **render_system_prompt_full** — 异步渲染（顺序 / 优先级 / 必填 / 工具声明）
- [ ] **render_system_prompt_simple** — 简化版（无 tool 声明，用于 unit test / dev）
- [ ] **build_tool_declaration 协议** — 在 harness 内定义签名，v0.1-6 stub 由应用层注入
- [ ] **应用层迁移** — `backend/app/engine/agent/slot_renderer.py` 改为 `from agent_flow_harness.slots import render_system_prompt_full`
- [ ] **应用层删除** — `backend/app/models/prompt_template.py` 的 `SLOT_SCHEMA` + `SlotDef` 改为 re-export harness 版本
- [ ] **25+ 单元测试** — 覆盖各分支
- [ ] **1 个迁移兼容测试** — 与现状输入/输出对比
- [ ] **Run & Verify** — harness + 应用层全部测试通过

## Dev Notes

### §1 SlotDef + SLOT_SCHEMA

```python
# packages/harness/src/agent_flow_harness/slots/schema.py
from pydantic import BaseModel, Field

class SlotDef(BaseModel):
    """单个 Prompt Slot 的元数据"""
    name: str = Field(..., description="slot 名称，作为 agent_doc['prompt_slots'] 的 key")
    label: str = Field(..., description="UI 标签 + 渲染时【】包裹的标题")
    required: bool = Field(False, description="缺失时 strict=True 是否抛错")
    description: str = Field("", description="slot 用途说明（仅 UI/文档用）")

# 5 段固定 Slot Schema（顺序不可变）
SLOT_SCHEMA: list[SlotDef] = [
    SlotDef(
        name="role",
        label="角色",
        required=True,
        description="Agent 的身份与角色定位（人设）",
    ),
    SlotDef(
        name="task",
        label="任务",
        required=True,
        description="Agent 需完成的核心任务描述",
    ),
    SlotDef(
        name="constraints",
        label="约束",
        required=False,
        description="Agent 行为约束（不要做什么 / 必须遵守什么）",
    ),
    SlotDef(
        name="context",
        label="上下文",
        required=False,
        description="业务背景信息（领域知识 / 业务现状）",
    ),
    SlotDef(
        name="output_format",
        label="输出格式",
        required=False,
        description="输出格式要求（Markdown / JSON / 表格 / 长度限制）",
    ),
]
```

### §2 render_system_prompt_full 主流程

```python
# packages/harness/src/agent_flow_harness/slots/renderer.py
from __future__ import annotations

import logging
from agent_flow_harness.slots.schema import SLOT_SCHEMA, SlotDef
from agent_flow_harness.tools import build_tool_declaration  # v0.1-7 由 ToolRegistry 实现

logger = logging.getLogger(__name__)


async def render_system_prompt_full(
    agent_doc: dict,
    *,
    node_slot_overrides: dict[str, str] | None = None,
    strict: bool = True,
) -> str:
    """
    按固定顺序渲染 Agent 的完整 system prompt。

    渲染顺序：role → task → constraints → context → output_format → tool_declaration

    Args:
        agent_doc: Agent 配置（dict，来自 MongoDB / agent_doc["prompt_slots"]）
        node_slot_overrides: workflow 节点级 slot 覆盖（如 Loop 节点内嵌 Agent 时）
        strict: True 时必填 slot 缺失抛 ValueError；False 时写占位段

    Returns:
        完整 system prompt 字符串
    """
    overrides = node_slot_overrides or {}
    agent_slots: dict[str, str] = agent_doc.get("prompt_slots") or {}
    parts: list[str] = []
    missing_required: list[str] = []

    for slot_def in SLOT_SCHEMA:
        name = slot_def.name
        # 优先级：overrides > agent_slots > 留空
        if name in overrides:
            value = overrides[name]
        elif name in agent_slots:
            value = agent_slots[name]
        else:
            value = None

        if value:
            parts.append(f"【{slot_def.label}】\n{value}")
        elif slot_def.required:
            missing_required.append(slot_def.label)

    if missing_required:
        if strict:
            raise ValueError(
                f"必填 Prompt Slot 缺失: {', '.join(missing_required)}。"
                f"Agent '{agent_doc.get('agent_id', '?')}' 缺少必填 slots。"
            )
        else:
            # non-strict: 写占位
            for label in missing_required:
                parts.append(f"【{label}】\n（未配置）")

    # 追加 tool_declaration
    tool_decl = await build_tool_declaration(agent_doc)
    if tool_decl:
        parts.append(tool_decl)

    return "\n\n".join(parts)


async def render_system_prompt_simple(agent_doc: dict) -> str:
    """
    简化版：只渲染 5 段，不追加 tool 声明。

    用于：unit test / 开发预览 / 嵌入到其他组合 prompt 中。
    """
    return await render_system_prompt_full(agent_doc, strict=False)
```

### §3 渲染格式（与现状完全一致）

每段格式：

```
【{label}】\n{value}
```

段与段之间：**双换行**（`\n\n`）分隔。

完整 prompt 形态：

```
【角色】
You are a professional product manager.

【任务】
分析用户需求并撰写 PRD。

【约束】
- 不超过 2000 字
- 使用简体中文

【上下文】
当前在做 agent-flow 项目...

【输出格式】
Markdown 格式，含小标题。

<tool_declaration 内容>
```

### §4 build_tool_declaration 协议（v0.1-6 stub）

```python
# packages/harness/src/agent_flow_harness/tools/registry.py
# v0.1-6 stub — v0.1-7 ToolRegistry Story 完整实现
async def build_tool_declaration(agent_doc: dict) -> str:
    """
    生成 tool 声明文本（拼到 system prompt 末尾）。

    v0.1-6: stub — 返回 "" (空字符串，与无 tool 场景一致)
    v0.1-7: 完整实现 — 拼装 Skill / MCP / Builtin / Task tool 4 类声明
    """
    return ""
```

**v0.1-6 → v0.1-7 演进路径**：
- v0.1-6：build_tool_declaration 在 harness 内 stub，**不依赖**应用层
- v0.1-7：ToolRegistry 完整实现，从 `agent_doc["skill_ids"]` / `mcp_connection_ids` / `builtin_config` 等查询生成声明
- 应用层 `backend/app/engine/agent/builder.build_tool_declaration` 整体迁移到 harness

### §5 优先级矩阵

| 优先级 | 来源 | 场景 |
|-------|------|------|
| 1（最高）| `node_slot_overrides[name]` | workflow Loop 节点内嵌 Agent 时覆盖 |
| 2 | `agent_doc["prompt_slots"][name]` | Agent 自身配置（MongoDB 持久化） |
| 3（最低）| 留空 | 未配置 |

**node_slot_overrides 用例**（v0.1-6 + 后续 workflow 节点扩展）：

```python
# Loop 节点内嵌的 Agent A 临时换 persona
system_prompt = await render_system_prompt_full(
    agent_doc=agent_functional_analyst,
    node_slot_overrides={"role": "You are a strict reviewer."},
)
```

### §6 应用层迁移策略

**v0.1-6 不删除** `backend/app/engine/agent/slot_renderer.py` 整个文件 — 改为**薄壳**：

```python
# backend/app/engine/agent/slot_renderer.py (v0.1-6 迁移后)
"""薄壳 — 转发到 harness"""
from agent_flow_harness.slots import (
    render_system_prompt_full,
    render_system_prompt_simple,
    SlotDef,
    SLOT_SCHEMA,
)

__all__ = [
    "render_system_prompt_full",
    "render_system_prompt_simple",
    "SlotDef",
    "SLOT_SCHEMA",
]
```

`backend/app/models/prompt_template.py` 同理 — 删 `SlotDef` / `SLOT_SCHEMA` 定义，改为 re-export：

```python
# backend/app/models/prompt_template.py (v0.1-6 迁移后)
from agent_flow_harness.slots.schema import SlotDef, SLOT_SCHEMA

__all__ = ["SlotDef", "SLOT_SCHEMA"]
```

`backend/app/engine/agent/builder.build_tool_declaration` 暂时保留应用层实现(v0.1-7 ToolRegistry 迁移) — v0.1-6 **不删除**,通过 v0.1-1 的 monkey patch / override 机制(见 §7)注入到 harness。

### §7 harness ↔ 应用层解耦机制

harness 的 `render_system_prompt_full` 需要 `build_tool_declaration` 函数。两种注入方式:

**方案 A（v0.1-6 默认）**：harness 内部 stub 返回 `""`，应用层在调用 `render_system_prompt_full` 后**手动追加**自己的 tool 声明：

```python
# 应用层调用方式（v0.1-6）
from agent_flow_harness.slots import render_system_prompt_full
from app.engine.agent.builder import build_tool_declaration  # 应用层实现

system_prompt = await render_system_prompt_full(agent_doc, strict=True)
tool_decl = await build_tool_declaration(agent_doc)
if tool_decl:
    system_prompt = f"{system_prompt}\n\n{tool_decl}"
```

**方案 B（v0.1-7+）**：harness 暴露 `set_tool_declaration_builder(fn)` 注册表，应用层注册自己的实现：

```python
# v0.1-7+ 调用方式
from agent_flow_harness.slots import render_system_prompt_full, set_tool_declaration_builder
from app.engine.agent.builder import build_tool_declaration

set_tool_declaration_builder(build_tool_declaration)
system_prompt = await render_system_prompt_full(agent_doc)  # 内部已含 tool_decl
```

**v0.1-6 选 A 方案** — 解耦清晰,harness 不依赖应用层;v0.1-7 ToolRegistry 迁移后切 B 方案。

### §8 兼容性

- `render_system_prompt_full(agent_doc, *, node_slot_overrides, strict)` 行为**与现状** `backend/app/engine/agent/slot_renderer.py:render_system_prompt_full` **完全一致**
- `SLOT_SCHEMA` 5 段固定顺序 + required 字段 + label 命名**与现状完全一致**
- 渲染格式 `【{label}】\n{value}` + `\n\n` 分隔**与现状完全一致**
- 必填缺失抛 `ValueError("必填 Prompt Slot 缺失: ...")` **与现状完全一致** (commit `bcdebc5` 后的行为)
- `node_slot_overrides` 参数为**新增能力**（现状不支持；v0.1-6 引入）

### §9 Slot vs Middleware 分工（强调 — A 方案）

| 维度 | Slot Renderer | Middleware |
|------|--------------|------------|
| 触发时机 | Agent 启动时构造一次 | 每次 LLM/Tool 调用前/后 |
| 作用对象 | `system prompt`（消息首条） | `messages` / `tool_call` / `result` |
| 典型能力 | 固定 5 段 prompt 装配 | audit / trace / prompt 动态注入 |
| 配置载体 | `agent_doc["prompt_slots"]` | `agent_doc["middleware"]` |
| 节点级覆盖 | `node_slot_overrides` | （v0.1.1+ 考虑） |

**判断口诀**：
- "**Agent 启动后第一眼看到什么**" → Slot Renderer（构造）
- "**每次 LLM 调用前要追加/改什么**" → Middleware（动态）

### §10 测试组织

```
packages/harness/tests/
├── slots/
│   ├── test_schema.py                  # SlotDef / SLOT_SCHEMA 字段 (5 个用例)
│   ├── test_renderer.py                # render 行为 (15 个用例)
│   │   ├── test_empty_agent_doc
│   │   ├── test_all_slots_filled
│   │   ├── test_role_only
│   │   ├── test_missing_required_strict_raises
│   │   ├── test_missing_required_non_strict_placeholder
│   │   ├── test_optional_missing_omitted
│   │   ├── test_node_overrides_highest_priority
│   │   ├── test_node_overrides_partial
│   │   ├── test_fixed_render_order
│   │   ├── test_label_brackets_format
│   │   ├── test_double_newline_separator
│   │   ├── test_tool_declaration_appended
│   │   ├── test_tool_declaration_empty_when_no_tools
│   │   ├── test_multiple_optional_slots
│   │   └── test_agent_doc_prompt_slots_missing_key
│   └── test_simple.py                  # render_system_prompt_simple (3 个用例)
└── integration/
    └── test_slot_migration_compat.py   # 与现状输入/输出逐字段对比 (1 个用例)
```

### §11 应用层迁移清单（v0.1-6 完成时）

| 文件 | 改动 | 备注 |
|------|------|------|
| `backend/app/engine/agent/slot_renderer.py` | 改写为薄壳（re-export harness） | 保留文件名（应用层 import 路径不变）|
| `backend/app/models/prompt_template.py` | 删 SlotDef/SLOT_SCHEMA 定义，re-export harness | 同上 |
| `backend/app/engine/agent/builder.py` | 不改（build_tool_declaration 应用层实现保留到 v0.1-7）| v0.1-6 不动 |
| `backend/tests/engine/agent/test_slot_renderer.py` | 不改 | 应用层测试继续验证（薄壳转发）|

### §12 已知风险

| 风险 | 缓解 |
|------|------|
| harness `build_tool_declaration` stub 返回空字符串，应用层忘记追加 tool 声明 | 方案 A 在 dev notes §7 显式给出"应用层调用方式"代码示例 |
| `node_slot_overrides` 与未来 node 级 prompt template 字段冲突 | 命名空间化（v0.1.1 调整） |
| 5 段固定 schema 不够灵活（用户想加自定义段） | 显式不支持；v0.1.1+ 考虑 `extra_slots: list[SlotDef]` 扩展 |
| `strict=False` 占位段 `\n（未配置）` 在中文环境显示不优雅 | 现状即如此，v0.1-6 不改 |
| 应用层 `build_tool_declaration` 依赖 MongoDB，harness 注入困难 | v0.1-6 方案 A：应用层在 harness 渲染后追加；v0.1-7 切方案 B |

## Dev Agent Record

### Implementation Plan

1. 定义 `SlotDef` + `SLOT_SCHEMA`（Pydantic + 5 段固定列表）
2. 实现 `render_system_prompt_full`（异步 + 顺序 + 优先级 + 必填 + 工具声明 stub）
3. 实现 `render_system_prompt_simple`（简化版，无 tool 声明）
4. 在 harness `tools/registry.py` 放 `build_tool_declaration` stub（v0.1-6 返回空）
5. `slots/__init__.py` re-export
6. 迁移应用层：`backend/app/engine/agent/slot_renderer.py` 改薄壳
7. 迁移应用层：`backend/app/models/prompt_template.py` 改 re-export
8. 写 25+ 单元测试 + 1 个迁移兼容测试
9. 运行完整测试套件

### Debug Log



### Completion Notes



## File List

**新增文件:**
- `packages/harness/src/agent_flow_harness/slots/__init__.py` — re-export
- `packages/harness/src/agent_flow_harness/slots/schema.py` — SlotDef + SLOT_SCHEMA
- `packages/harness/src/agent_flow_harness/slots/renderer.py` — render_system_prompt_full / render_system_prompt_simple
- `packages/harness/tests/slots/test_schema.py`
- `packages/harness/tests/slots/test_renderer.py`
- `packages/harness/tests/slots/test_simple.py`
- `packages/harness/tests/integration/test_slot_migration_compat.py`

**修改文件:**
- `backend/app/engine/agent/slot_renderer.py` — 改写为薄壳（re-export harness）
- `backend/app/models/prompt_template.py` — 改 re-export
- `packages/harness/src/agent_flow_harness/__init__.py` — re-export slots 入口

**未修改文件（保留到 v0.1-7）:**
- `backend/app/engine/agent/builder.py` — `build_tool_declaration` 应用层实现保留
- `packages/harness/src/agent_flow_harness/tools/registry.py` — v0.1-6 stub，v0.1-7 完整实现

## Change Log

- 2026-06-23: Story v0.1-6 创建 — Slot 渲染协议与 Renderer（ready-for-dev，依赖 v0.1-5）

## Status

**Status:** ready-for-dev
