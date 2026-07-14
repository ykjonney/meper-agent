# Task 23: SSE 事件解析与时间线渲染

## 背景
当前 widget 只处理 text 事件，需要支持所有 SSE 事件类型。后端发送的事件类型包括：
- `thinking_delta`: 增量推理 token
- `thinking`: 完整推理文本
- `text_delta`: 增量文本 token
- `text`: 完整文本块
- `tool_call_start`: 工具调用开始（无名称/参数）
- `tool_call`: 已解析的工具调用（name/args/id）
- `tool_result`: 工具结果（name/content）
- `interrupt`: Agent 暂停等待用户回答
- `error`: 终端错误

## 需要修改的文件

### 1. `src/types/index.ts`
添加时间线条目类型：
```typescript
/** 时间线条目类型 */
export type TimelineEntryType = 'thinking' | 'text' | 'tool_call' | 'tool_result' | 'error' | 'interrupt';

/** 工具调用状态 */
export type ToolStatus = 'pending' | 'running' | 'success' | 'error';

/** 时间线条目 */
export interface TimelineEntry {
  id: string;
  type: TimelineEntryType;
  content: string;
  timestamp: number;
  // tool_call 专用字段
  toolName?: string;
  toolArgs?: Record<string, any>;
  toolStatus?: ToolStatus;
  // thinking 专用字段
  collapsed?: boolean;
}

/** SSE 流式事件 - 扩展支持所有事件类型 */
export type StreamEvent =
  | { type: 'text_delta'; content: string }
  | { type: 'text'; content: string }
  | { type: 'thinking_delta'; content: string }
  | { type: 'thinking'; content: string }
  | { type: 'tool_call_start' }
  | { type: 'tool_call'; tool_name: string; args: Record<string, any>; id: string }
  | { type: 'tool_result'; tool_name: string; content: string }
  | { type: 'interrupt'; question: string; clarification_type?: string; context?: string; options?: string[]; interrupt_id?: string }
  | { type: 'error'; message: string; source?: string }
  | { type: 'done'; session_id: string };
```

### 2. `src/services/agent-api.ts`
更新 SSE 解析器，支持所有事件类型。当前实现只处理 text 和 content 字段。需要改为根据 `parsed.type` 分发：
```typescript
// 根据 parsed.type 返回对应的 StreamEvent
const typeMap = {
  'text_delta': (p: any) => ({ type: 'text_delta' as const, content: p.content || '' }),
  'text': (p: any) => ({ type: 'text' as const, content: p.content || '' }),
  'thinking_delta': (p: any) => ({ type: 'thinking_delta' as const, content: p.content || '' }),
  'thinking': (p: any) => ({ type: 'thinking' as const, content: p.content || '' }),
  'tool_call_start': () => ({ type: 'tool_call_start' as const }),
  'tool_call': (p: any) => ({ type: 'tool_call' as const, tool_name: p.tool_name || '', args: p.args || {}, id: p.id || '' }),
  'tool_result': (p: any) => ({ type: 'tool_result' as const, tool_name: p.tool_name || '', content: p.content || '' }),
  'interrupt': (p: any) => ({ type: 'interrupt' as const, question: p.question || '', clarification_type: p.clarification_type, context: p.context, options: p.options, interrupt_id: p.interrupt_id }),
  'error': (p: any) => ({ type: 'error' as const, message: p.message || '', source: p.source }),
};

const handler = typeMap[parsed.type as keyof typeof typeMap];
if (handler) {
  yield handler(parsed);
}
// 未知类型忽略
```

### 3. `src/hooks/useChat.ts`
更新 hook 以维护时间线条目：
```typescript
interface UseChatReturn {
  messages: Message[];  // 用户消息
  timeline: TimelineEntry[];  // assistant 回复的时间线
  input: string;
  setInput: (value: string) => void;
  sendMessage: () => Promise<void>;
  isLoading: boolean;
  error: string | null;
  sessionId: string | null;
  clearMessages: () => void;
  // interrupt 相关
  pendingInterrupt: InterruptData | null;
  resumeWithAnswer: (answer: string) => Promise<void>;
}
```

在 sendMessage 中，根据事件类型更新 timeline：
- `text_delta` / `text`: 追加到最后一个 text 条目（若无则创建）
- `thinking_delta` / `thinking`: 追加到最后一个 thinking 条目（若无则创建）
- `tool_call_start`: 创建 pending 状态的 tool_call 条目
- `tool_call`: 更新 pending 条目的名称和参数
- `tool_result`: 更新对应 tool_call 条目的结果和状态
- `error`: 创建 error 条目
- `interrupt`: 设置 pendingInterrupt 状态

### 4. 新组件

#### `src/components/TimelineRenderer.tsx`
渲染时间线条目的主组件：
```typescript
interface TimelineRendererProps {
  timeline: TimelineEntry[];
}
```
根据 entry.type 渲染不同组件：
- `thinking`: ThinkingBlock
- `text`: 使用 MessageBubble 的 markdown 渲染
- `tool_call`: ToolCallBlock
- `error`: ErrorBlock
- `interrupt`: InterruptBlock

#### `src/components/ThinkingBlock.tsx`
可折叠的思考块：
- 标题："思考过程"
- 可展开/折叠
- 内容显示 reasoning 文本

#### `src/components/ToolCallBlock.tsx`
工具调用块：
- 显示工具名称和状态图标
- 可展开查看参数和结果
- 状态：pending(旋转), running(旋转), success(✓), error(✗)

#### `src/components/InterruptBlock.tsx`
中断提示块：
- 显示问题文本
- 如果有 options，显示为按钮
- 提供输入框让用户回答

## 需要更新 MessageList.tsx
MessageList 需要同时渲染用户消息和 assistant 的时间线：
```typescript
interface MessageListProps {
  messages: Message[];  // 包含用户消息
  timeline: TimelineEntry[];  // assistant 回复
}
```
渲染逻辑：遍历 messages，对于用户消息用 MessageBubble，对于 assistant 消息用 TimelineRenderer。

## 需要更新 ChatWindow.tsx
- 从 useChat 获取 timeline 和 pendingInterrupt
- 传递 timeline 给 MessageList
- 如果有 pendingInterrupt，显示 InterruptBlock

## 测试验证
- 构建应成功：`npm run build`
- TypeScript 无错误：`npx tsc --noEmit`
- 事件类型正确解析

## 约束
- 保持与现有 Message 类型的兼容性
- 使用内联样式（Shadow DOM 隔离）
- 遵循 Preact JSX 类型
- 文件保持小巧，职责单一
