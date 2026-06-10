---
title: 'Chat 流式输出优化 + LLM 原生推理支持'
type: 'feature'
created: '2026-06-10'
status: 'approved'
baseline_commit: 'NO_VCS'
context: []
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Chat 测试页面的流式输出直接展示 LangGraph 节点的原始 AgentState 数据（messages 数组、step_count 等 JSON 字段），用户看到的是未处理的原始数据而非友好的执行链路。同时缺少「思考模式」开关，无法启用 LLM 原生推理能力（Claude extended thinking / OpenAI reasoning_effort）。

**Approach:** 后端 SSE 事件结构化为语义化类型（thinking/tool_call/tool_result/final_answer），按执行顺序逐个推送，包含所有中间步骤。前端按时间线渲染完整的调用链（思考→工具调用→工具结果→最终回答），让测试时能看清 Agent 的完整行为。新增 thinking 模式支持，按 provider 适配参数，不支持的模型静默降级并提示。

## Boundaries & Constraints

**Always:**
- SSE 推送所有结构化事件（thinking / tool_call / tool_result / final_answer），前端按时间线展示完整调用链
- 每个事件类型有独立的渲染样式（思考=折叠蓝块、工具调用=橙色标签、最终回答=对话气泡）
- 思考模式仅在模型支持时生效（Claude extended thinking / OpenAI o-series reasoning_effort）
- 不支持原生推理的模型静默降级，UI 显示提示文字

**Ask First:**
- 需要变更 `ExecutionRequest` schema 添加 `enable_thinking` 字段

**Never:**
- 不实现自定义推理（不用 REACT 模拟思考）
- 不修改 LangGraph 图拓扑（evaluate → react → END 保持不变）
- 不展示 evaluate 节点的原始 state（无意义的中间数据）

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| 正常对话（无 thinking，无工具） | 用户发消息，模型 gpt-4o-mini | 时间线显示：最终回答气泡 | - |
| REACT 多轮（有工具调用） | Agent 配了工具，LLM 决定调用 | 时间线显示：tool_call → tool_result → 最终回答 | - |
| 启用 thinking（Claude） | enable_thinking=true，claude-sonnet | 时间线显示：思考折叠块 → 最终回答 | - |
| 启用 thinking（o-series） | enable_thinking=true，o3-mini | 时间线显示：最终回答 | - |
| thinking 但模型不支持 | enable_thinking=true，gpt-4o | 静默降级，开关旁提示「当前模型不支持」 | - |
| 流式中断 | 用户点击停止 | 保留已接收的时间线事件 | - |
| 后端错误 | LLM 调用失败 | 红色错误条目 + 重试按钮 | - |

</frozen-after-approval>

## Code Map

- `backend/app/api/v1/agents.py` -- stream_agent 端点，SSE 事件格式化与结构化
- `backend/app/engine/agent/react_executor.py` -- REACT 执行器，产出 messages 含 AIMessage/ToolMessage
- `backend/app/engine/llm_factory.py` -- LLM 客户端构建，需适配 thinking 参数
- `backend/app/schemas/execution.py` -- ExecutionRequest schema，需添加 enable_thinking
- `frontend/src/components/chat-panel.tsx` -- SSE 解析 + 时间线渲染核心
- `frontend/src/services/agent-api.ts` -- stream() 方法 + SSE 事件类型定义

## Tasks & Acceptance

**Execution:**
- [x] `backend/app/schemas/execution.py` -- 添加 `enable_thinking: bool = False` 字段到 ExecutionRequest
- [x] `backend/app/engine/llm_factory.py` -- `get_llm_client` 新增 `enable_thinking` 参数，Anthropic 传 `thinking={"type": "enabled", "budget_tokens": 5000}`，OpenAI o-series 传 `reasoning_effort="high"`，其他忽略
- [x] `backend/app/engine/agent/builder.py` -- `_make_react_node` 透传 enable_thinking 到 llm_factory
- [x] `backend/app/api/v1/agents.py` -- stream 端点 SSE 重构：遍历 react 节点 output 中的 messages 列表，按类型逐条推送结构化事件（thinking/tool_call/tool_result/final_answer），evaluate 节点跳过；invoke 端点同样从 messages 提取结构化结果
- [x] `frontend/src/services/agent-api.ts` -- 新增 SSE 事件类型定义（ThinkingEvent/ToolCallEvent/ToolResultEvent/FinalAnswerEvent），ExecutionRequest 添加 enable_thinking
- [x] `frontend/src/components/chat-panel.tsx` -- SSE 解析支持全部事件类型；消息区改为时间线渲染（思考折叠块 + 工具调用标签 + 工具结果折叠 + 最终回答气泡）；新增 thinking Switch 开关 + 不支持提示
- [x] `backend/tests/engine/test_llm_factory_thinking.py` -- 测试 thinking 参数适配逻辑

**Acceptance Criteria:**
- Given 用户发送消息触发工具调用，when 流式输出，then 时间线按顺序展示 tool_call → tool_result → final_answer
- Given 用户开启 thinking + Claude 模型，when 发送消息，then 时间线展示思考折叠块 → 最终回答
- Given 用户开启 thinking + gpt-4o-mini，when 界面渲染，then 开关旁显示「当前模型不支持推理」提示
- Given 用户点击停止，when 流式中断，then 保留已展示的时间线事件

## Design Notes

### SSE 结构化事件格式

后端遍历 react 节点 output 中的 `messages` 列表，按消息类型推送不同事件：

```
# 思考过程（Claude extended thinking 的 thinking block）
data: {"type": "thinking", "content": "让我分析一下..."}

# AI 发起工具调用
data: {"type": "tool_call", "tool_name": "search_workflow", "args": {"query": "..."}}

# 工具返回结果
data: {"type": "tool_result", "tool_name": "search_workflow", "content": "找到 3 个结果..."}

# 最终回答
data: {"type": "final_answer", "content": "根据分析，建议..."}

# 流结束
data: {"done": true, "request_id": "..."}
```

### 前端时间线渲染

每条用户消息对应一组时间线条目，按顺序垂直排列：
- **thinking**: 蓝色折叠块，默认折叠，点击展开查看推理过程
- **tool_call**: 橙色小标签 `🔧 search_workflow(args...)`
- **tool_result**: 灰色折叠块，默认折叠，展示工具返回内容
- **final_answer**: 正常对话气泡样式
- **error**: 红色提示条

### Thinking 参数适配策略

```python
# Anthropic Claude — 传 thinking 参数到 ChatAnthropic
ChatAnthropic(model="claude-sonnet-4-6", max_tokens=16000,
              thinking={"type": "enabled", "budget_tokens": 5000})

# OpenAI o-series — 传 reasoning_effort
ChatOpenAI(model="o3-mini", reasoning_effort="high")

# 其他模型 → 忽略 thinking，按普通模式调用
```

## Verification

**Commands:**
- `cd backend && uv run pytest tests/ --tb=short -q` -- expected: 全部通过
- `cd frontend && npx tsc --noEmit` -- expected: 零错误

**Manual checks:**
- 在 /chat-test 发消息，确认时间线显示完整调用链（不是原始 JSON）
- 开启 thinking + Claude 模型，确认思考折叠块出现
- 开启 thinking + GPT-4o-mini，确认不支持提示出现
