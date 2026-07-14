# Agent Flow Chat Widget 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建一个可嵌入任意前端页面的聊天 Widget，通过 API Key 认证调用 agent-flow 后端 Agent。

**Architecture:** 独立 Preact 项目，使用 Shadow DOM 隔离样式，构建产物为单个 JS 文件，通过 `<script>` 标签引入使用。前端生成 visitor_id 存入 localStorage 实现多访客会话隔离。

**Tech Stack:** Preact, TypeScript, Vite, Shadow DOM, SSE (fetch API)

## Global Constraints

- 产物体积：gzip 后 ≤ 50KB
- 支持现代浏览器（Chrome 90+, Firefox 88+, Safari 14+, Edge 90+）
- 使用 API Key 认证，Header: `X-Api-Key`
- 请求体包含 `visitor_id` 字段用于会话隔离
- 样式必须隔离在 Shadow DOM 内，不污染宿主页面

---

## Task 1: 项目初始化与构建配置

**Files:**
- Create: `agent-flow-widget/package.json`
- Create: `agent-flow-widget/tsconfig.json`
- Create: `agent-flow-widget/vite.config.ts`
- Create: `agent-flow-widget/.gitignore`

**Interfaces:**
- Consumes: 无
- Produces: 可运行的空项目骨架

- [ ] **Step 1: 创建项目目录**

```bash
cd /Users/huyuekai/company/agent-flow
mkdir -p agent-flow-widget/src
cd agent-flow-widget
```

- [ ] **Step 2: 创建 package.json**

```json
// agent-flow-widget/package.json
{
  "name": "agent-flow-widget",
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc && vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "preact": "^10.19.0"
  },
  "devDependencies": {
    "@preact/preset-vite": "^2.8.0",
    "typescript": "^5.3.0",
    "vite": "^5.0.0"
  }
}
```

- [ ] **Step 3: 创建 tsconfig.json**

```json
// agent-flow-widget/tsconfig.json
{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx",
    "jsxImportSource": "preact",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true
  },
  "include": ["src"]
}
```

- [ ] **Step 4: 创建 vite.config.ts**

```typescript
// agent-flow-widget/vite.config.ts
import { defineConfig } from 'vite';
import preact from '@preact/preset-vite';

export default defineConfig({
  plugins: [preact()],
  build: {
    lib: {
      entry: 'src/index.tsx',
      name: 'AgentChat',
      fileName: 'agent-chat',
      formats: ['iife'],
    },
    outDir: 'dist',
    sourcemap: false,
    minify: 'terser',
    terserOptions: {
      compress: {
        drop_console: true,
      },
    },
  },
});
```

- [ ] **Step 5: 创建 .gitignore**

```
# agent-flow-widget/.gitignore
node_modules
dist
.DS_Store
*.local
```

- [ ] **Step 6: 创建入口文件占位**

```typescript
// agent-flow-widget/src/index.tsx
console.log('Agent Chat Widget loaded');

// 暴露全局 API
(window as any).AgentChat = {
  init: (config: any) => {
    console.log('AgentChat.init called with:', config);
  },
};
```

- [ ] **Step 7: 安装依赖并验证构建**

```bash
cd agent-flow-widget
npm install
npm run build
```

Expected: 构建成功，生成 `dist/agent-chat.js`

- [ ] **Step 8: 提交**

```bash
cd /Users/huyuekai/company/agent-flow
git add agent-flow-widget/
git commit -m "feat(widget): init project skeleton with Vite + Preact + TypeScript"
```

---

## Task 2: 类型定义

**Files:**
- Create: `agent-flow-widget/src/types/index.ts`

**Interfaces:**
- Consumes: 无
- Produces: `WidgetConfig`, `Message`, `StreamEvent` 等类型

- [ ] **Step 1: 创建类型定义文件**

```typescript
// agent-flow-widget/src/types/index.ts

/** Widget 初始化配置 */
export interface WidgetConfig {
  /** 必填：API Key */
  apiKey: string;
  /** 必填：Agent ID */
  agentId: string;
  /** 必填：后端 API 地址 */
  apiBaseUrl: string;
  /** 可选：聊天窗口标题 */
  title?: string;
  /** 可选：浮窗位置 */
  position?: 'bottom-right' | 'bottom-left';
}

/** 聊天消息 */
export interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: number;
  /** 是否正在流式输出中 */
  streaming?: boolean;
}

/** 会话 */
export interface Session {
  id: string;
  title: string;
  createdAt: number;
  updatedAt: number;
}

/** SSE 流式事件 */
export type StreamEvent =
  | { type: 'text'; content: string }
  | { type: 'done'; session_id: string }
  | { type: 'error'; message: string };

/** Agent 调用请求 */
export interface InvokeRequest {
  message: string;
  session_id?: string;
  visitor_id: string;
}

/** Agent 调用响应头 */
export interface InvokeResponseHeaders {
  sessionId: string;
  requestId: string;
}
```

- [ ] **Step 2: 提交**

```bash
git add agent-flow-widget/src/types/index.ts
git commit -m "feat(widget): add type definitions"
```

---

## Task 3: Visitor ID 管理

**Files:**
- Create: `agent-flow-widget/src/lib/visitor.ts`

**Interfaces:**
- Consumes: 无
- Produces: `getOrCreateVisitorId(): string`

- [ ] **Step 1: 创建 visitor ID 管理模块**

```typescript
// agent-flow-widget/src/lib/visitor.ts

const STORAGE_KEY = 'agent-chat-visitor-id';

/**
 * 获取或创建 visitor ID
 * 首次调用时生成 UUID 并存入 localStorage
 * 后续调用从 localStorage 读取
 */
export function getOrCreateVisitorId(): string {
  let visitorId = localStorage.getItem(STORAGE_KEY);

  if (!visitorId) {
    visitorId = crypto.randomUUID();
    localStorage.setItem(STORAGE_KEY, visitorId);
  }

  return visitorId;
}

/**
 * 清除 visitor ID（用于调试）
 */
export function clearVisitorId(): void {
  localStorage.removeItem(STORAGE_KEY);
}
```

- [ ] **Step 2: 提交**

```bash
git add agent-flow-widget/src/lib/visitor.ts
git commit -m "feat(widget): add visitor ID management with localStorage"
```

---

## Task 4: API 服务层

**Files:**
- Create: `agent-flow-widget/src/services/api-client.ts`
- Create: `agent-flow-widget/src/services/agent-api.ts`

**Interfaces:**
- Consumes: `WidgetConfig`, `InvokeRequest`, `StreamEvent`
- Produces: `streamAgentMessage()` 函数

- [ ] **Step 1: 创建 API 客户端基础模块**

```typescript
// agent-flow-widget/src/services/api-client.ts

import type { WidgetConfig } from '../types';

let config: WidgetConfig;

/**
 * 初始化 API 客户端配置
 */
export function initApiClient(widgetConfig: WidgetConfig): void {
  config = widgetConfig;
}

/**
 * 获取当前配置
 */
export function getConfig(): WidgetConfig {
  return config;
}

/**
 * 构建请求头
 */
export function buildHeaders(): HeadersInit {
  return {
    'Content-Type': 'application/json',
    'X-Api-Key': config.apiKey,
  };
}

/**
 * 构建完整 URL
 */
export function buildUrl(path: string): string {
  const base = config.apiBaseUrl.replace(/\/$/, '');
  return `${base}${path}`;
}
```

- [ ] **Step 2: 创建 Agent API 模块**

```typescript
// agent-flow-widget/src/services/agent-api.ts

import type { StreamEvent, InvokeRequest } from '../types';
import { buildHeaders, buildUrl, getConfig } from './api-client';

/**
 * 流式调用 Agent
 * 返回异步迭代器，逐条产出 StreamEvent
 */
export async function* streamAgentMessage(
  request: InvokeRequest
): AsyncGenerator<StreamEvent> {
  const { agentId } = getConfig();
  const url = buildUrl(`/api/v1/ext/agents/${agentId}/invoke/stream`);

  const response = await fetch(url, {
    method: 'POST',
    headers: buildHeaders(),
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    const errorText = await response.text();
    yield { type: 'error', message: `请求失败: ${response.status} ${errorText}` };
    return;
  }

  const sessionId = response.headers.get('X-Session-Id');
  if (sessionId) {
    yield { type: 'done', session_id: sessionId };
  }

  const reader = response.body?.getReader();
  if (!reader) {
    yield { type: 'error', message: '无法读取响应流' };
    return;
  }

  const decoder = new TextDecoder();
  let buffer = '';

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          const data = line.slice(6).trim();
          if (data === '[DONE]') continue;

          try {
            const parsed = JSON.parse(data);
            if (parsed.type === 'text' || parsed.content) {
              yield { type: 'text', content: parsed.content || parsed.text || '' };
            }
          } catch {
            // 非 JSON 数据，当作纯文本处理
            if (data && !data.startsWith('event:')) {
              yield { type: 'text', content: data };
            }
          }
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}
```

- [ ] **Step 3: 提交**

```bash
git add agent-flow-widget/src/services/
git commit -m "feat(widget): add API client and agent streaming service"
```

---

## Task 5: 聊天状态管理 Hook

**Files:**
- Create: `agent-flow-widget/src/hooks/useChat.ts`

**Interfaces:**
- Consumes: `streamAgentMessage()`, `getOrCreateVisitorId()`
- Produces: `useChat()` hook 返回 `{ messages, input, setInput, sendMessage, isLoading, error, sessionId }`

- [ ] **Step 1: 创建 useChat hook**

```typescript
// agent-flow-widget/src/hooks/useChat.ts

import { useState, useCallback, useRef } from 'preact/hooks';
import type { Message } from '../types';
import { streamAgentMessage } from '../services/agent-api';
import { getOrCreateVisitorId } from '../lib/visitor';

interface UseChatReturn {
  messages: Message[];
  input: string;
  setInput: (value: string) => void;
  sendMessage: () => Promise<void>;
  isLoading: boolean;
  error: string | null;
  sessionId: string | null;
  clearMessages: () => void;
}

export function useChat(): UseChatReturn {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);

  const visitorId = useRef(getOrCreateVisitorId());
  const abortRef = useRef<AbortController | null>(null);

  const sendMessage = useCallback(async () => {
    if (!input.trim() || isLoading) return;

    const userMessage: Message = {
      id: crypto.randomUUID(),
      role: 'user',
      content: input.trim(),
      timestamp: Date.now(),
    };

    const assistantMessage: Message = {
      id: crypto.randomUUID(),
      role: 'assistant',
      content: '',
      timestamp: Date.now(),
      streaming: true,
    };

    setMessages(prev => [...prev, userMessage, assistantMessage]);
    setInput('');
    setIsLoading(true);
    setError(null);

    try {
      const stream = streamAgentMessage({
        message: userMessage.content,
        session_id: sessionId || undefined,
        visitor_id: visitorId.current,
      });

      for await (const event of stream) {
        if (event.type === 'text') {
          setMessages(prev => {
            const updated = [...prev];
            const last = updated[updated.length - 1];
            if (last && last.role === 'assistant') {
              updated[updated.length - 1] = {
                ...last,
                content: last.content + event.content,
              };
            }
            return updated;
          });
        } else if (event.type === 'done') {
          setSessionId(event.session_id);
          setMessages(prev => {
            const updated = [...prev];
            const last = updated[updated.length - 1];
            if (last && last.role === 'assistant') {
              updated[updated.length - 1] = { ...last, streaming: false };
            }
            return updated;
          });
        } else if (event.type === 'error') {
          setError(event.message);
          setMessages(prev => prev.slice(0, -1)); // 移除空的 assistant 消息
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '未知错误');
      setMessages(prev => prev.slice(0, -1));
    } finally {
      setIsLoading(false);
    }
  }, [input, isLoading, sessionId]);

  const clearMessages = useCallback(() => {
    setMessages([]);
    setSessionId(null);
    setError(null);
  }, []);

  return {
    messages,
    input,
    setInput,
    sendMessage,
    isLoading,
    error,
    sessionId,
    clearMessages,
  };
}
```

- [ ] **Step 2: 提交**

```bash
git add agent-flow-widget/src/hooks/useChat.ts
git commit -m "feat(widget): add useChat hook for state management"
```

---

## Task 6: UI 组件 - FloatingButton

**Files:**
- Create: `agent-flow-widget/src/components/FloatingButton.tsx`

**Interfaces:**
- Consumes: `onClick` callback
- Produces: 浮动按钮组件

- [ ] **Step 1: 创建 FloatingButton 组件**

```tsx
// agent-flow-widget/src/components/FloatingButton.tsx

interface FloatingButtonProps {
  onClick: () => void;
  position: 'bottom-right' | 'bottom-left';
}

export function FloatingButton({ onClick, position }: FloatingButtonProps) {
  const style: preact.JSX.CSSProperties = {
    position: 'fixed',
    bottom: '20px',
    [position === 'bottom-right' ? 'right' : 'left']: '20px',
    width: '56px',
    height: '56px',
    borderRadius: '50%',
    backgroundColor: '#4F46E5',
    color: 'white',
    border: 'none',
    cursor: 'pointer',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    boxShadow: '0 4px 12px rgba(0, 0, 0, 0.15)',
    zIndex: 999998,
    transition: 'transform 0.2s, box-shadow 0.2s',
  };

  return (
    <button
      style={style}
      onClick={onClick}
      onMouseEnter={(e) => {
        e.currentTarget.style.transform = 'scale(1.05)';
        e.currentTarget.style.boxShadow = '0 6px 16px rgba(0, 0, 0, 0.2)';
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.transform = 'scale(1)';
        e.currentTarget.style.boxShadow = '0 4px 12px rgba(0, 0, 0, 0.15)';
      }}
      aria-label="打开聊天"
    >
      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
      </svg>
    </button>
  );
}
```

- [ ] **Step 2: 提交**

```bash
git add agent-flow-widget/src/components/FloatingButton.tsx
git commit -m "feat(widget): add FloatingButton component"
```

---

## Task 7: UI 组件 - MessageBubble

**Files:**
- Create: `agent-flow-widget/src/components/MessageBubble.tsx`

**Interfaces:**
- Consumes: `Message`
- Produces: 消息气泡组件（支持 Markdown 基础渲染）

- [ ] **Step 1: 创建 MessageBubble 组件**

```tsx
// agent-flow-widget/src/components/MessageBubble.tsx

import type { Message } from '../types';

interface MessageBubbleProps {
  message: Message;
}

/**
 * 简单的 Markdown 渲染
 * 处理基础的 **bold**, *italic*, `code`, 换行
 */
function renderMarkdown(text: string): string {
  return text
    // 转义 HTML
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    // 粗体
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    // 斜体
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    // 行内代码
    .replace(/`(.+?)`/g, '<code style="background:#f3f4f6;padding:2px 4px;border-radius:3px;font-size:0.9em;">$1</code>')
    // 换行
    .replace(/\n/g, '<br>');
}

export function MessageBubble({ message }: MessageBubbleProps) {
  const isUser = message.role === 'user';

  const containerStyle: preact.JSX.CSSProperties = {
    display: 'flex',
    justifyContent: isUser ? 'flex-end' : 'flex-start',
    marginBottom: '12px',
    padding: '0 16px',
  };

  const bubbleStyle: preact.JSX.CSSProperties = {
    maxWidth: '80%',
    padding: '10px 14px',
    borderRadius: isUser ? '16px 16px 4px 16px' : '16px 16px 16px 4px',
    backgroundColor: isUser ? '#4F46E5' : '#F3F4F6',
    color: isUser ? 'white' : '#1F2937',
    fontSize: '14px',
    lineHeight: '1.5',
    wordBreak: 'break-word',
  };

  return (
    <div style={containerStyle}>
      <div style={bubbleStyle}>
        <div
          dangerouslySetInnerHTML={{ __html: renderMarkdown(message.content) }}
        />
        {message.streaming && (
          <span style={{ display: 'inline-block', marginLeft: '4px' }}>▊</span>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: 提交**

```bash
git add agent-flow-widget/src/components/MessageBubble.tsx
git commit -m "feat(widget): add MessageBubble component with basic Markdown"
```

---

## Task 8: UI 组件 - InputBar

**Files:**
- Create: `agent-flow-widget/src/components/InputBar.tsx`

**Interfaces:**
- Consumes: `value`, `onChange`, `onSubmit`, `disabled`
- Produces: 输入框组件

- [ ] **Step 1: 创建 InputBar 组件**

```tsx
// agent-flow-widget/src/components/InputBar.tsx

import { useCallback, KeyboardEvent } from 'preact/compat';

interface InputBarProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  disabled?: boolean;
}

export function InputBar({ value, onChange, onSubmit, disabled }: InputBarProps) {
  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLInputElement>) => {
      if (e.key === 'Enter' && !e.shiftKey && !disabled) {
        e.preventDefault();
        onSubmit();
      }
    },
    [onSubmit, disabled]
  );

  const containerStyle: preact.JSX.CSSProperties = {
    display: 'flex',
    alignItems: 'center',
    padding: '12px 16px',
    borderTop: '1px solid #E5E7EB',
    backgroundColor: 'white',
  };

  const inputStyle: preact.JSX.CSSProperties = {
    flex: 1,
    padding: '10px 14px',
    border: '1px solid #D1D5DB',
    borderRadius: '20px',
    fontSize: '14px',
    outline: 'none',
    transition: 'border-color 0.2s',
  };

  const buttonStyle: preact.JSX.CSSProperties = {
    marginLeft: '8px',
    padding: '10px 16px',
    backgroundColor: disabled ? '#9CA3AF' : '#4F46E5',
    color: 'white',
    border: 'none',
    borderRadius: '20px',
    fontSize: '14px',
    fontWeight: 500,
    cursor: disabled ? 'not-allowed' : 'pointer',
    transition: 'background-color 0.2s',
  };

  return (
    <div style={containerStyle}>
      <input
        type="text"
        value={value}
        onInput={(e) => onChange(e.currentTarget.value)}
        onKeyDown={handleKeyDown}
        onFocus={(e) => { e.currentTarget.style.borderColor = '#4F46E5'; }}
        onBlur={(e) => { e.currentTarget.style.borderColor = '#D1D5DB'; }}
        placeholder="输入消息..."
        disabled={disabled}
        style={inputStyle}
      />
      <button
        onClick={onSubmit}
        disabled={disabled}
        style={buttonStyle}
      >
        发送
      </button>
    </div>
  );
}
```

- [ ] **Step 2: 提交**

```bash
git add agent-flow-widget/src/components/InputBar.tsx
git commit -m "feat(widget): add InputBar component"
```

---

## Task 9: UI 组件 - MessageList

**Files:**
- Create: `agent-flow-widget/src/components/MessageList.tsx`

**Interfaces:**
- Consumes: `Message[]`
- Produces: 消息列表组件（自动滚动到底部）

- [ ] **Step 1: 创建 MessageList 组件**

```tsx
// agent-flow-widget/src/components/MessageList.tsx

import { useEffect, useRef } from 'preact/hooks';
import type { Message } from '../types';
import { MessageBubble } from './MessageBubble';

interface MessageListProps {
  messages: Message[];
}

export function MessageList({ messages }: MessageListProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  // 自动滚动到底部
  useEffect(() => {
    if (containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
    }
  }, [messages]);

  const containerStyle: preact.JSX.CSSProperties = {
    flex: 1,
    overflowY: 'auto',
    padding: '16px 0',
  };

  const emptyStyle: preact.JSX.CSSProperties = {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    height: '100%',
    color: '#6B7280',
    fontSize: '14px',
    textAlign: 'center',
    padding: '20px',
  };

  if (messages.length === 0) {
    return (
      <div style={containerStyle}>
        <div style={emptyStyle}>
          <div style={{ fontSize: '32px', marginBottom: '12px' }}>👋</div>
          <div>你好！有什么我可以帮你的吗？</div>
        </div>
      </div>
    );
  }

  return (
    <div ref={containerRef} style={containerStyle}>
      {messages.map((msg) => (
        <MessageBubble key={msg.id} message={msg} />
      ))}
    </div>
  );
}
```

- [ ] **Step 2: 提交**

```bash
git add agent-flow-widget/src/components/MessageList.tsx
git commit -m "feat(widget): add MessageList component with auto-scroll"
```

---

## Task 10: UI 组件 - ChatWindow

**Files:**
- Create: `agent-flow-widget/src/components/ChatWindow.tsx`

**Interfaces:**
- Consumes: `useChat()` hook, `onClose`, `title`
- Produces: 聊天窗口主组件

- [ ] **Step 1: 创建 ChatWindow 组件**

```tsx
// agent-flow-widget/src/components/ChatWindow.tsx

import { useChat } from '../hooks/useChat';
import { MessageList } from './MessageList';
import { InputBar } from './InputBar';

interface ChatWindowProps {
  title: string;
  onClose: () => void;
}

export function ChatWindow({ title, onClose }: ChatWindowProps) {
  const { messages, input, setInput, sendMessage, isLoading, error, clearMessages } = useChat();

  const windowStyle: preact.JSX.CSSProperties = {
    position: 'fixed',
    bottom: '90px',
    right: '20px',
    width: '380px',
    height: '560px',
    backgroundColor: 'white',
    borderRadius: '16px',
    boxShadow: '0 8px 32px rgba(0, 0, 0, 0.12)',
    display: 'flex',
    flexDirection: 'column',
    overflow: 'hidden',
    zIndex: 999999,
    animation: 'slideUp 0.2s ease-out',
  };

  const headerStyle: preact.JSX.CSSProperties = {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '16px 20px',
    backgroundColor: '#4F46E5',
    color: 'white',
  };

  const titleStyle: preact.JSX.CSSProperties = {
    fontSize: '16px',
    fontWeight: 600,
  };

  const closeButtonStyle: preact.JSX.CSSProperties = {
    background: 'none',
    border: 'none',
    color: 'white',
    fontSize: '20px',
    cursor: 'pointer',
    padding: '0',
    lineHeight: 1,
    opacity: 0.8,
  };

  const errorStyle: preact.JSX.CSSProperties = {
    padding: '8px 16px',
    backgroundColor: '#FEE2E2',
    color: '#991B1B',
    fontSize: '12px',
    textAlign: 'center',
  };

  return (
    <div style={windowStyle}>
      <div style={headerStyle}>
        <span style={titleStyle}>{title}</span>
        <div>
          {messages.length > 0 && (
            <button
              onClick={clearMessages}
              style={{ ...closeButtonStyle, marginRight: '12px', fontSize: '14px' }}
              title="新建对话"
            >
              +
            </button>
          )}
          <button onClick={onClose} style={closeButtonStyle}>×</button>
        </div>
      </div>

      {error && <div style={errorStyle}>{error}</div>}

      <MessageList messages={messages} />

      <InputBar
        value={input}
        onChange={setInput}
        onSubmit={sendMessage}
        disabled={isLoading}
      />
    </div>
  );
}
```

- [ ] **Step 2: 提交**

```bash
git add agent-flow-widget/src/components/ChatWindow.tsx
git commit -m "feat(widget): add ChatWindow component"
```

---

## Task 11: Widget 主组件与 Shadow DOM

**Files:**
- Create: `agent-flow-widget/src/widget.tsx`

**Interfaces:**
- Consumes: `WidgetConfig`, `ChatWindow`, `FloatingButton`
- Produces: `mountWidget()` 函数

- [ ] **Step 1: 创建 widget 主组件**

```tsx
// agent-flow-widget/src/widget.tsx

import { render } from 'preact';
import { useState } from 'preact/hooks';
import type { WidgetConfig } from './types';
import { FloatingButton } from './components/FloatingButton';
import { ChatWindow } from './components/ChatWindow';

interface WidgetProps {
  config: WidgetConfig;
}

function Widget({ config }: WidgetProps) {
  const [isOpen, setIsOpen] = useState(false);

  return (
    <>
      <FloatingButton
        onClick={() => setIsOpen(true)}
        position={config.position || 'bottom-right'}
      />
      {isOpen && (
        <ChatWindow
          title={config.title || 'AI 助手'}
          onClose={() => setIsOpen(false)}
        />
      )}
    </>
  );
}

/**
 * 挂载 Widget 到 Shadow DOM
 */
export function mountWidget(config: WidgetConfig, container: HTMLElement): void {
  // 创建 Shadow DOM
  const shadow = container.attachShadow({ mode: 'open' });

  // 创建样式容器
  const style = document.createElement('style');
  style.textContent = `
    @keyframes slideUp {
      from { opacity: 0; transform: translateY(10px); }
      to { opacity: 1; transform: translateY(0); }
    }
    * {
      box-sizing: border-box;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
    }
  `;
  shadow.appendChild(style);

  // 创建挂载点
  const mountPoint = document.createElement('div');
  shadow.appendChild(mountPoint);

  // 渲染 Preact 应用
  render(<Widget config={config} />, mountPoint);
}
```

- [ ] **Step 2: 提交**

```bash
git add agent-flow-widget/src/widget.tsx
git commit -m "feat(widget): add widget main component with Shadow DOM"
```

---

## Task 12: 入口文件与全局 API

**Files:**
- Modify: `agent-flow-widget/src/index.tsx`

**Interfaces:**
- Consumes: `mountWidget()`, `initApiClient()`
- Produces: `window.AgentChat.init()` 全局 API

- [ ] **Step 1: 更新入口文件**

```tsx
// agent-flow-widget/src/index.tsx

import type { WidgetConfig } from './types';
import { mountWidget } from './widget';
import { initApiClient } from './services/api-client';

/**
 * 初始化 Agent Chat Widget
 */
function init(config: WidgetConfig): void {
  // 验证必填参数
  if (!config.apiKey) throw new Error('apiKey is required');
  if (!config.agentId) throw new Error('agentId is required');
  if (!config.apiBaseUrl) throw new Error('apiBaseUrl is required');

  // 初始化 API 客户端
  initApiClient(config);

  // 创建容器
  const container = document.createElement('div');
  container.id = 'agent-chat-widget';
  document.body.appendChild(container);

  // 挂载 Widget
  mountWidget(config, container);
}

// 暴露全局 API
(window as any).AgentChat = { init };
```

- [ ] **Step 2: 构建并验证**

```bash
cd agent-flow-widget
npm run build
```

Expected: 构建成功，生成 `dist/agent-chat.js`

- [ ] **Step 3: 提交**

```bash
git add agent-flow-widget/src/index.tsx
git commit -m "feat(widget): complete entry point with global AgentChat.init() API"
```

---

## Task 13: 后端改动 - 支持 visitor_id

**Files:**
- Modify: `backend/app/schemas/ext_api.py` (添加 visitor_id 字段)
- Modify: `backend/app/api/v1/ext/agents.py` (使用 visitor_id)

**Interfaces:**
- Consumes: `ApiKeyPrincipal`
- Produces: API 支持 visitor_id 区分访客

- [ ] **Step 1: 查看当前 ext_api schema**

```bash
cat backend/app/schemas/ext_api.py
```

- [ ] **Step 2: 添加 visitor_id 到 ExtInvokeRequest**

找到 `ExtInvokeRequest` 类，添加 `visitor_id` 字段：

```python
# 在 ExtInvokeRequest 中添加
visitor_id: str | None = Field(default=None, description="前端生成的访客 ID，用于会话隔离")
```

- [ ] **Step 3: 修改 agents.py 使用 visitor_id**

在 `invoke_agent` 和 `stream_agent` 函数中，修改 user_id 计算逻辑：

```python
# 原代码
user_id=principal.owner_user_id,

# 改为
user_id=f"{principal.owner_user_id}:{body.visitor_id}" if body.visitor_id else principal.owner_user_id,
```

- [ ] **Step 4: 验证后端启动**

```bash
cd backend
uv run python -c "from app.schemas.ext_api import ExtInvokeRequest; print('OK')"
```

- [ ] **Step 5: 提交**

```bash
cd /Users/huyuekai/company/agent-flow
git add backend/app/schemas/ext_api.py backend/app/api/v1/ext/agents.py
git commit -m "feat(api): add visitor_id support for multi-tenant session isolation"
```

---

## Task 14: 测试页面

**Files:**
- Create: `agent-flow-widget/test/index.html`

**Interfaces:**
- Consumes: 构建产物 `dist/agent-chat.js`
- Produces: 可本地测试的 HTML 页面

- [ ] **Step 1: 创建测试页面**

```html
<!-- agent-flow-widget/test/index.html -->
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Agent Chat Widget Test</title>
  <style>
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      max-width: 800px;
      margin: 0 auto;
      padding: 40px 20px;
      background: #f5f5f5;
    }
    h1 { color: #333; }
    .info {
      background: white;
      padding: 20px;
      border-radius: 8px;
      margin: 20px 0;
      box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }
    code {
      background: #f3f4f6;
      padding: 2px 6px;
      border-radius: 4px;
      font-size: 14px;
    }
  </style>
</head>
<body>
  <h1>🤖 Agent Chat Widget 测试页面</h1>

  <div class="info">
    <h3>测试说明</h3>
    <p>这是一个测试页面，用于验证 Agent Chat Widget 的功能。</p>
    <p>右下角应该有一个聊天按钮，点击即可开始对话。</p>
  </div>

  <div class="info">
    <h3>配置信息</h3>
    <p>API Key: <code>sk-test-xxx</code></p>
    <p>Agent ID: <code>agent-test-123</code></p>
    <p>API Base URL: <code>http://localhost:8000</code></p>
  </div>

  <!-- 引入 Widget JS -->
  <script src="../dist/agent-chat.js"></script>

  <!-- 初始化 Widget -->
  <script>
    AgentChat.init({
      apiKey: 'sk-test-xxx',
      agentId: 'agent-test-123',
      apiBaseUrl: 'http://localhost:8000',
      title: '测试助手',
      position: 'bottom-right',
    });
  </script>
</body>
</html>
```

- [ ] **Step 2: 测试**

```bash
# 在浏览器打开测试页面
open agent-flow-widget/test/index.html
```

- [ ] **Step 3: 提交**

```bash
git add agent-flow-widget/test/index.html
git commit -m "feat(widget): add test page for local development"
```

---

## Task 15: README 文档

**Files:**
- Create: `agent-flow-widget/README.md`

- [ ] **Step 1: 创建 README**

```markdown
# Agent Flow Chat Widget

可嵌入任意前端页面的聊天插件，通过 API Key 认证调用 agent-flow 后端 Agent。

## 特性

- 🚀 轻量级（gzip 后 ~20KB）
- 🔒 Shadow DOM 样式隔离
- 📱 响应式设计
- 🔑 API Key 认证
- 👥 多访客会话隔离

## 快速开始

### 1. 引入 JS

```html
<script src="https://your-agent-flow.com/static/agent-chat.js"></script>
```

### 2. 初始化

```html
<script>
  AgentChat.init({
    apiKey: 'sk-xxx',           // 必填：API Key
    agentId: 'agent-123',       // 必填：Agent ID
    apiBaseUrl: 'https://your-agent-flow.com',  // 必填：后端地址
    title: '智能助手',           // 可选：默认 "AI 助手"
    position: 'bottom-right',   // 可选：默认 "bottom-right"
  });
</script>
```

## 配置项

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| apiKey | string | ✅ | API Key |
| agentId | string | ✅ | Agent ID |
| apiBaseUrl | string | ✅ | 后端 API 地址 |
| title | string | ❌ | 聊天窗口标题 |
| position | string | ❌ | 浮窗位置：`bottom-right` / `bottom-left` |

## 开发

```bash
# 安装依赖
npm install

# 开发模式
npm run dev

# 构建
npm run build
```

## 会话隔离

Widget 使用 `visitor_id` 实现多访客会话隔离：

- 首次加载时生成 UUID 并存入 `localStorage`
- 同一浏览器的访客共享同一个 `visitor_id`
- 不同浏览器的访客有独立的会话

## 技术栈

- Preact
- TypeScript
- Vite
- Shadow DOM
```

- [ ] **Step 2: 提交**

```bash
git add agent-flow-widget/README.md
git commit -m "docs(widget): add README with usage instructions"
```

---

## 完成检查清单

- [ ] 项目可以正常构建 (`npm run build`)
- [ ] 测试页面可以加载 Widget
- [ ] 浮窗按钮显示正常，点击可展开聊天窗口
- [ ] 输入消息后可以看到请求发送（即使后端未启动）
- [ ] 后端支持 visitor_id 参数
- [ ] 代码已提交

---

## 后续优化（非 MVP）

- [ ] 文件上传功能
- [ ] 思考过程 / 工具调用展示
- [ ] 亮/暗主题切换
- [ ] 自定义样式（主题色、Logo）
- [ ] npm 包发布
- [ ] 单元测试
