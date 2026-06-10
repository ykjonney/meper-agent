# Review Diff: 工具分类配置前端对接

## 变更摘要

### 1. `frontend/src/services/agent-api.ts`
- Agent 接口新增 `skill_ids: string[]`, `mcp_connection_ids: string[]`, `builtin_config: string[]`
- AgentCreateInput 和 AgentUpdateInput 新增三个可选字段 + 向后兼容 `tool_ids`（标记 @deprecated）
- 旧 Agent 的 `tool_ids` 仍然保留读取

### 2. `frontend/src/services/tools-api.ts`
- ToolListParams 接口新增 `source?: string` 字段，支持按来源过滤（markdown / mcp / builtin）
- `list()` 方法自动传递 `source` 参数到后端 API

### 3. `frontend/src/components/tool-selector.tsx`（新建）
- 三段式工具选择器组件
  - Built-in 工具：Checkbox 组（bash/read/write），可点击卡片切换
  - Skill 工具：Multi-select，通过 `toolsApi.list({source:'markdown'})` 加载
  - MCP 连接：Multi-select，通过 `mcpApi.list()` 加载
- 受控组件：`value: ToolSelectorValue` / `onChange`
- Loading 态：Skeleton 占位
- Empty 态：Empty 组件提示用户上传/配置
- 内置常量 BUILTIN_TOOLS = [bash, read, write]

### 4. `frontend/src/components/agent-config-form.tsx`
- 新增 `toolConfig` state 管理三类工具配置
- useEffect 支持编辑态回填：旧 Agent 兼容 `agent.skill_ids ?? agent.tool_ids ?? []`
- 新增 Collapse 面板"工具配置"集成 ToolSelector
- 保存时传递 `skill_ids`, `mcp_connection_ids`, `builtin_config`
- defaultActiveKey 包含 'tools' 面板

### 5. `frontend/src/pages/agents-page.tsx`
- Agent 列表卡片工具标签从单标签改为三分组标签：
  - 蓝色 Skill 标签（显示数量）
  - 黄色 Built-in 标签（显示数量）
  - 绿色 MCP 标签（显示数量）
- 仅在对应字段非空时显示

## 设计决策
- ToolSelector 使用 ToolSelectorValue 统一管理三个字段
- 编辑时向后兼容：优先使用 skill_ids，回退至 tool_ids
- 创建时默认值均为空数组
- 保存时不发送旧的 tool_ids 字段（后端自动映射）
