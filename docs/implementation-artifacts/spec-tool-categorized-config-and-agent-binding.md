---
title: '工具分类配置与 Agent 绑定'
type: 'feature'
created: '2026-06-10'
status: 'done'
baseline_commit: NO_VCS
context: []
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Agent 的 `tool_ids` 是扁平 ID 列表，无法区分 Skill / MCP / Built-in 三类不同来源的工具；Built-in 工具始终全量注入不可配置；MCP 工具完全未接入 Agent 执行。

**Approach:** 将 Agent 模型中的 `tool_ids` 拆分为 `skill_ids` / `mcp_connection_ids` / `builtin_config` 三个独立字段；Built-in 工具改为白名单模式；MCP 按连接绑定，执行时自动加载并注入 MCP 工具。

## Boundaries & Constraints

**Always:**
- `skill_ids` 引用 `source="markdown"` 的 Tool 文档
- `mcp_connection_ids` 引用 MCP 连接，执行时加载该连接下所有 `source="mcp"` 的 Tool 文档注入
- `builtin_config` 是白名单列表，只注入列表中的内置工具名称
- 旧的 `tool_ids` 字段在读取时自动映射到 `skill_ids`（向后兼容）
- 前端工具选择器按三类分别展示：Built-in（checkbox）/ Skill（multi-select）/ MCP Connection（multi-select）

**Ask First:** 无

**Never:**
- 不要删除旧 Agent 文档中的 `tool_ids` 字段（只做读取兼容）
- 不要在 Agent 模型中增加新字段以外的复杂嵌套结构
- 不要将 MCP 工具解析到单个工具粒度绑定（按连接绑定即可）

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| 旧 Agent 只有 tool_ids | DB 文档 `{"tool_ids": ["t1","t2"]}` | 读取时自动映射为 `skill_ids: ["t1","t2"]`，builder 正常注入 | N/A |
| builtin_config 含无效名称 | `builtin_config: ["bash","nope"]` | 只注入 bash，忽略 "nope" | 静默忽略无效名称 |
| mcp_connection_ids 含断开连接的 ID | `mcp_connection_ids: ["mcp1"]` 且 mcp1 状态为 disconnected | 执行时跳过该连接，不注入任何工具 | 日志 warning，不抛异常 |
| 所有分类字段均为空 | 三个字段都是空列表 | 只注入 workflow tools（search_workflow 等） | N/A |

</frozen-after-approval>

## Code Map

- `backend/app/models/agent.py` -- Agent 模型，`tool_ids` 改为 `skill_ids` + `mcp_connection_ids` + `builtin_config`
- `backend/app/models/tool.py` -- Tool 模型已有 `source`/`mcp_connection_id`，无需修改
- `backend/app/models/mcp_connection.py` -- MCP 连接模型，无需修改
- `backend/app/schemas/agent.py` -- AgentCreate/Update/Response 更新字段
- `backend/app/services/agent_service.py` -- create/update/duplicate 适配新字段 + 向后兼容
- `backend/app/api/v1/agents.py` -- invoke/stream 从 `skill_ids` 读取，传递 `builtin_config` 给 builder
- `backend/app/api/v1/tools.py` -- `list_tools` 增加 `source` 查询参数
- `backend/app/engine/agent/builder.py` -- `_resolve_tools` 适配三个分类来源；`_make_react_node` 接收 `builtin_config` 过滤
- `backend/app/engine/agent/builtin_tools.py` -- 导出名称注册表供过滤
- `frontend/src/services/agent-api.ts` -- Agent 类型增加新字段
- `frontend/src/services/tools-api.ts` -- `ToolListParams` 增加 `source`
- `frontend/src/components/agent-config-form.tsx` -- 新增三类工具选择器 UI
- `frontend/src/components/tool-selector.tsx` -- 新建：分类工具选择组件

## Tasks & Acceptance

**Execution:**
- [ ] `backend/app/models/agent.py` -- `tool_ids` 替换为 `skill_ids: list[str]` + `mcp_connection_ids: list[str]` + `builtin_config: list[str]`；添加属性兼容 `tool_ids` 读取
- [ ] `backend/app/schemas/agent.py` -- AgentCreate/Update/Response 同步更新字段
- [ ] `backend/app/services/agent_service.py` -- create/update/duplicate 适配新字段；写入时同时写 `tool_ids`（兼容）和新字段
- [ ] `backend/app/api/v1/agents.py` -- invoke/stream 从 `skill_ids` 构建 skill declaration；传递 `builtin_config` 给 builder
- [ ] `backend/app/api/v1/tools.py` -- `list_tools` 增加 `source` 可选查询参数
- [ ] `backend/app/engine/agent/builtin_tools.py` -- 导出 `BUILTIN_TOOL_REGISTRY: dict[str, BaseTool]` 供按名称过滤
- [ ] `backend/app/engine/agent/builder.py` -- `_resolve_tools` 读取 `skill_ids` + `mcp_connection_ids` + `builtin_config`；MCP 工具暂为 MVP 空列表
- [x] `frontend/src/services/agent-api.ts` -- Agent 类型增加 `skill_ids` / `mcp_connection_ids` / `builtin_config`
- [x] `frontend/src/services/tools-api.ts` -- `ToolListParams` 增加 `source` 参数
- [x] `frontend/src/components/tool-selector.tsx` -- 新建：三段式工具选择器（Built-in checkbox / Skill multi-select / MCP connection multi-select）
- [x] `frontend/src/components/agent-config-form.tsx` -- 整合 ToolSelector，提交时传新字段
- [x] `frontend/src/pages/agents-page.tsx` -- Agent 列表卡片展示三类工具数量标签
- [ ] `backend/tests/` -- 单元测试覆盖：向后兼容、白名单过滤、MCP 跳过

**Acceptance Criteria:**
- Given Agent 无旧 `tool_ids`，when 创建，then 三个新字段按传入值存储
- Given Agent 旧文档只有 `tool_ids`，when 通过 API 查询，then 返回中包含映射后的 `skill_ids`
- Given `builtin_config: ["read"]`，when Agent 执行，then 只有 `read` 工具可用（没有 bash/write）
- Given `mcp_connection_ids` 含已断开连接，when Agent 执行，then 日志记录 warning 但不影响整体执行

## Design Notes

**Agent 模型新结构：**
```python
class Agent(BaseModel):
    # ... 现有字段不变 ...
    skill_ids: list[str] = Field(default_factory=list)  # 替代 tool_ids
    mcp_connection_ids: list[str] = Field(default_factory=list)
    builtin_config: list[str] = Field(default_factory=list)  # 白名单
    # 保留 tool_ids 字段用于读取兼容（非 persisted，只做 getter）
```

**向后兼容策略：**
- Agent 文档写入时同时填充 `tool_ids = skill_ids`（保持旧字段非空）
- Agent 文档读取时，如果只有 `tool_ids` 没有 `skill_ids`，自动映射
- 首次写入新 Agent 时，三个新字段都写入 DB

**工具选择器 UI 布局：**
```
┌─ Agent 工具配置 ─────────────────────┐
│                                      │
│ □ Built-in 工具（始终可用）           │
│   ☑ bash  ☑ read  ☑ write           │
│                                      │
│ ▼ Skill 工具（Markdown 上传）          │
│   [web-search] [code-review] [+]     │
│                                      │
│ ▼ MCP 连接                           │
│   [database-mcp] [search-mcp] [+]    │
│                                      │
└──────────────────────────────────────┘
```

**Builder tool resolution 逻辑（执行时）：**
```python
async def _resolve_tools(agent: dict) -> list:
    tools = []
    # 1. Skill tools (from skill_ids)
    if skill_ids:
        docs = await ToolService.get_tools_by_ids(skill_ids)
        allowed = {d["name"] for d in docs}
        tools += [_make_skill_loader(allowed), _make_skill_file_loader(allowed)]

    # 2. MCP tools (from mcp_connection_ids) — MVP: 遍历连接查 tool 文档
    for conn_id in mcp_connection_ids:
        mcp_tools = await ToolService.get_mcp_tools(conn_id)
        tools += [make_mcp_tool_wrapper(t) for t in mcp_tools]

    # 3. Built-in tools (filtered by builtin_config whitelist)
    for name in builtin_config:
        if name in BUILTIN_TOOL_REGISTRY:
            tools.append(BUILTIN_TOOL_REGISTRY[name])

    return tools
```

## Verification

**Commands:**
- `cd backend && uv run pytest tests/ -q` -- expected: 全部 passed
- `cd backend && uv run pytest tests/engine/agent/test_builder.py -v` -- expected: 新增测试覆盖三个分类场景
- `cd frontend && npx tsc --noEmit` -- expected: 无新增类型错误

## Suggested Review Order

**类型定义层** — 前端类型同步后端契约，新增三个分类字段并保留向后兼容

- Agent 接口新增 `skill_ids` / `mcp_connection_ids` / `builtin_config`，`tool_ids` 标记 @deprecated
  [`agent-api.ts:21`](../../frontend/src/services/agent-api.ts#L21)
- AgentCreateInput/AgentUpdateInput 同步新字段，`tool_ids` 可选保留
  [`agent-api.ts:43`](../../frontend/src/services/agent-api.ts#L43)
- ToolListParams 新增 `source` 过滤参数，支持按来源查询
  [`tools-api.ts:37`](../../frontend/src/services/tools-api.ts#L37)

**UI 组件层** — 三段式工具选择器，受控组件模式直接集成表单

- 三段式选择器：Built-in Checkbox / Skill Multi-select / MCP Multi-select，含加载态/空态/错误态
  [`tool-selector.tsx:61`](../../frontend/src/components/tool-selector.tsx#L61)
- Built-in 工具使用 Checkbox.Group 避免双击切换问题
  [`tool-selector.tsx:115`](../../frontend/src/components/tool-selector.tsx#L115)
- Skill 选择使用 `s.id` 作为值以匹配后端 `skill_ids` 契约
  [`tool-selector.tsx:181`](../../frontend/src/components/tool-selector.tsx#L181)

**表单集成层** — ToolSelector 嵌入 Agent 配置表单，创建/编辑均支持

- 新增 `toolConfig` state 统一管理三类字段，useEffect 回填时使用 `length > 0` 判断兼容旧数据
  [`agent-config-form.tsx:66`](../../frontend/src/components/agent-config-form.tsx#L66)
- 保存时传递 `skill_ids` / `mcp_connection_ids` / `builtin_config`
  [`agent-config-form.tsx:109`](../../frontend/src/components/agent-config-form.tsx#L109)

**列表展示层** — Agent 卡片分颜色展示三类工具数量标签

- Skill（蓝）/ Built-in（黄）/ MCP（绿）三个标签，仅在对应字段非空时显示
  [`agents-page.tsx:336`](../../frontend/src/pages/agents-page.tsx#L336)
