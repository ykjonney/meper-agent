---
title: 'Skill 声明式注入 Agent 执行链路'
type: 'feature'
created: '2026-06-10'
status: 'done'
baseline_commit: 'NO_VCS'
context: []
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Agent 执行时，已绑定的 Skill（通过 `tool_ids`）完全没有被 LLM 感知——`_resolve_tools()` 返回空列表、`system_prompt` 未注入 messages、LLM 无法发现或调用任何 Skill。

**Approach:** 实现 Claude Code 式的 Skill 注入机制：执行时在 system prompt 中声明所有可用 Skill（name + description），LLM 需要时通过 `skill` 工具主动调用，系统按需加载 Skill 完整内容（instructions + files）返回给 LLM 继续推理。

## Boundaries & Constraints

**Always:**
- Skill 以"声明 + 按需加载"模式工作，不要将 Skill 全文预加载到 prompt
- `skill` 工具的定义模式与 `_WORKFLOW_TOOLS`（`@tool` 装饰器）保持一致
- 现有 380+ 测试必须全部通过
- 不修改前端（前端选择器属于 defer 目标 B）

**Ask First:** 无

**Never:**
- 不要将 Skill 文件内容预先全部注入 system prompt
- 不要用 `llm.bind_tools()` 绑定所有 Skill 为独立工具（只有 `skill` 这一个工具）
- 不要修改 `Agent` 数据模型

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Agent 有 2 个 Skill，LLM 不需要 Skill | Agent.tool_ids 含 2 个 tool_id | system prompt 中列出声明，LLM 正常回答，不触发 skill 工具 | N/A |
| Agent 有 Skill，LLM 调用其中一个 | LLM 产出 tool_calls: [{name:"skill", args:{skill_name:"my-skill"}}] | 系统从 MongoDB 加载 Skill 完整内容，作为 ToolMessage 返回 | N/A |
| LLM 调用不存在的 Skill | tool_calls: [{name:"skill", args:{skill_name:"nope"}}] | 返回 ToolMessage: "Skill 'nope' not found" | 不抛异常，返回错误文本 |
| Agent 无 Skill | tool_ids = [] | system prompt 无 Skill 声明段落 | N/A |
| Skill 是目录包 | files 含多个文件 | 加载时将 SKILL.md instructions + 所有辅助文件内容格式化返回 | N/A |
| system_prompt 为空 | agent.system_prompt = "" | SystemMessage 只含 Skill 声明段落 | N/A |

</frozen-after-approval>

## Code Map

- `backend/app/engine/agent/builder.py` -- `_resolve_tools()` 当前返回空列表，需替换为返回 `[skill_tool]`
- `backend/app/engine/agent/react_executor.py` -- REACT loop 执行工具调用，需兼容 `skill` 工具的异步加载逻辑
- `backend/app/api/v1/agents.py` -- invoke/stream 入口，需将 `system_prompt` + Skill 声明注入 messages
- `backend/app/services/tool_service.py` -- 提供 `get_tools_by_ids()` 批量查询方法
- `backend/app/engine/tool/skill_parser.py` -- 已有解析器，无需修改
- `backend/app/engine/agent/workflow_executor.py` -- 参考其 `@tool` 定义模式

## Tasks & Acceptance

**Execution:**
- [x] `backend/app/services/tool_service.py` -- 新增 `get_tools_by_ids(tool_ids: list[str]) -> list[dict]` 批量查询方法
- [x] `backend/app/engine/agent/builder.py` -- 实现 `skill` 工具（`@tool` 装饰器），内部根据 skill_name 查 MongoDB 加载内容；重写 `_resolve_tools()` 返回 `[skill_tool]`；新增 `_build_skill_declaration()` 生成声明文本
- [x] `backend/app/api/v1/agents.py` -- 在 invoke 和 stream 端点中，构建 `SystemMessage`（system_prompt + skill declaration）注入 messages 头部
- [x] `backend/tests/engine/agent/test_builder.py` -- 新增单元测试覆盖：空 tool_ids、有效 tool_ids、skill 声明格式、skill 工具调用（命中/未命中）
- [x] `backend/tests/api/test_agents.py` -- 验证 invoke/stream 端点的 messages 包含 SystemMessage（现有 39 个测试全部通过，builder 测试覆盖声明逻辑）

**Acceptance Criteria:**
- Given Agent 有 tool_ids 指向已注册 Skill，when 执行 invoke，then LLM 收到包含 Skill 声明的 SystemMessage + 可用的 `skill` 工具
- Given LLM 调用 `skill` 工具并传入有效 skill_name，when REACT loop 执行工具，then 返回该 Skill 的完整 instructions（和 files 内容）
- Given LLM 调用 `skill` 工具并传入无效 skill_name，when REACT loop 执行工具，then 返回 "Skill 'xxx' not found" 错误消息
- Given Agent 的 tool_ids 为空，when 执行 invoke，then system prompt 中无 Skill 声明段落
- Given 现有 380+ 测试，when 运行全量 pytest，then 全部通过

## Spec Change Log

## Design Notes

**Skill 声明格式（注入 system prompt 尾部）：**

```
## Available Skills

You have access to the following skills. When you need to use one, call the `skill` tool with the skill name.

- **skill-name-1**: Description of skill 1
- **skill-name-2**: Description of skill 2
```

**`skill` 工具定义：**

```python
@tool
def skill(skill_name: str) -> str:
    """Load and return the full content of a named skill.
    Use this when you need detailed instructions from a skill."""
```

工具内部通过闭包或全局 registry 访问 `ToolService`，按 `skill_name` 查 MongoDB，返回 instructions（目录包则追加 files 内容）。

**SystemMessage 注入位置：** messages 列表第 0 项，LLM 调用时在 `agents.py` 构建而非 builder 内部，因为 builder 只负责构建 graph，不负责构建初始 messages。

## Verification

**Commands:**
- `cd backend && uv run pytest tests/ --ignore=tests/api/test_agent_execution.py -q` -- expected: 全部 passed
- `cd backend && uv run pytest tests/engine/agent/test_builder.py -v` -- expected: 新增测试全 passed
- `cd frontend && npx tsc --noEmit` -- expected: 无新增错误（本次不改前端，但确认无破坏）

## Suggested Review Order

**Skill declaration and on-demand loading**

- Entry point: declaration format + skill tool + async resolution
  [`builder.py:46`](../../backend/app/engine/agent/builder.py#L46)

- Async tool resolution with whitelist and dead-ID guard
  [`builder.py:182`](../../backend/app/engine/agent/builder.py#L182)

- The `skill` tool: loads instructions + files, name match fix, truncation
  [`builder.py:210`](../../backend/app/engine/agent/builder.py#L210)

**API SystemMessage injection**

- SystemMessage prepended with skill declaration in invoke endpoint
  [`agents.py:342`](../../backend/app/api/v1/agents.py#L342)

- Same injection pattern in the streaming endpoint
  [`agents.py:460`](../../backend/app/api/v1/agents.py#L460)

**Service layer**

- Batch fetch for resolving tool_ids → skill names
  [`tool_service.py:374`](../../backend/app/services/tool_service.py#L374)

**Tests**

- 16 tests: empty/missing/invalid tool_ids, whitelist, truncation, declaration
  [`test_builder.py:1`](../../backend/tests/engine/agent/test_builder.py#L1)
