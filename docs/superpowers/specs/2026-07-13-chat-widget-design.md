# Agent Flow Chat Widget 设计文档

**日期**: 2026-07-13
**状态**: 设计完成，待实施

## 1. 概述

构建一个可嵌入任意前端页面的聊天插件（Widget），利用 agent-flow 后端的 Agent 能力提供对话功能。

### 1.1 目标
- 独立项目，可被任何前端项目通过 `<script>` 标签引入
- 使用 API Key 认证，无需用户登录
- 支持多访客会话隔离
- 轻量级，对宿主页面零影响

### 1.2 非目标（MVP 不含）
- 文件上传
- 思考过程/工具调用展示
- 亮/暗主题切换
- npm 包发布（仅 script 标签引入）

## 2. 技术方案

| 维度 | 选型 | 理由 |
|------|------|------|
| UI 框架 | Preact | 体积小（~3KB），API 与 React 几乎一致 |
| 样式隔离 | Shadow DOM | 完全隔离，不影响宿主页面 |
| 构建工具 | Vite | 与主项目一致，配置简单 |
| 语言 | TypeScript | 类型安全 |
| 状态管理 | Preact hooks | 轻量，无需外部状态库 |

### 2.1 产物体积预期
- gzip 后约 20-30KB
- 单个 JS 文件，包含所有依赖（Preact + 组件 + 样式）

## 3. 架构设计

```
┌─────────────────────────────────────────────────────┐
│  宿主页面（任意前端项目）                              │
│                                                     │
│  <script src="/static/agent-chat.js"></script>      │
│  <script>                                          │
│    AgentChat.init({                                │
│      apiKey: 'sk-xxx',                             │
│      agentId: 'agent-123',                         │
│      apiBaseUrl: 'https://api.example.com'          │
│    });                                              │
│  </script>                                         │
│                                                     │
│  ┌──────────────────────────────┐  ← Shadow DOM    │
│  │  🤖 Agent Chat         [×]  │     完全隔离      │
│  │  ─────────────────────────  │                    │
│  │  [消息列表 - 流式输出]       │                    │
│  │                              │                    │
│  │  [输入框]          [发送 ➤] │                    │
│  └──────────────────────────────┘                    │
└─────────────────────────────────────────────────────┘
                        │
                        │ fetch + SSE (API Key in Header)
                        ▼
            ┌───────────────────────┐
            │  agent-flow 后端      │
            │  /api/v1/ext/agents/* │
            └───────────────────────┘
```

### 3.1 核心流程
1. JS 加载后，在页面创建浮窗按钮（右下角）
2. 用户点击按钮，展开聊天面板（渲染在 Shadow DOM 内）
3. 用户输入消息，通过 SSE 流式调用后端
4. 实时渲染 AI 回复

## 4. 项目结构

```
agent-flow-widget/
├── src/
│   ├── index.tsx          # 入口：AgentChat.init() 全局函数
│   ├── widget.tsx         # Widget 主组件（Shadow DOM 挂载）
│   ├── App.tsx            # 聊天应用主界面
│   ├── components/
│   │   ├── ChatWindow.tsx    # 聊天窗口容器
│   │   ├── MessageList.tsx   # 消息列表（流式渲染）
│   │   ├── MessageBubble.tsx # 单条消息（用户/AI/Markdown）
│   │   ├── InputBar.tsx      # 输入框 + 发送按钮
│   │   ├── FloatingButton.tsx# 右下角浮动按钮
│   │   └── SessionPanel.tsx  # 会话列表侧边栏
│   ├── hooks/
│   │   ├── useStream.ts      # SSE 流式请求 hook
│   │   ├── useSession.ts     # 会话管理 hook
│   │   └── useChat.ts        # 聊天状态管理
│   ├── services/
│   │   ├── api-client.ts     # HTTP 客户端（API Key 注入）
│   │   ├── agent-api.ts      # Agent 流式调用
│   │   └── session-api.ts    # 会话 CRUD
│   ├── types/
│   │   └── index.ts          # 类型定义
│   └── styles/
│       └── widget.css        # 组件样式（隔离在 Shadow DOM 内）
├── package.json
├── tsconfig.json
├── vite.config.ts
└── README.md
```

## 5. 会话隔离方案

### 5.1 问题
同一个 API Key 可能被多个访客使用，需要隔离各自的会话。

### 5.2 方案：Visitor ID + localStorage

```typescript
// Widget 首次加载时
function getOrCreateVisitorId(): string {
  const STORAGE_KEY = 'agent-chat-visitor-id';
  let visitorId = localStorage.getItem(STORAGE_KEY);
  if (!visitorId) {
    visitorId = crypto.randomUUID();
    localStorage.setItem(STORAGE_KEY, visitorId);
  }
  return visitorId;
}
```

### 5.3 效果

| 场景 | 结果 |
|------|------|
| 张三首次访问 | 生成 visitor_id=AAA，新会话 |
| 张三刷新页面 | 读取到同一个 AAA，历史消息保留 |
| 李四用另一个浏览器 | 生成 visitor_id=BBB，会话完全隔离 |

### 5.4 后端配合
后端 ext API 需小改一处，支持 `visitor_id` 字段：

```python
# 方案 A：拼接 user_id（最简单）
user_id = f"{principal.owner_user_id}:{visitor_id}" if visitor_id else principal.owner_user_id

# 方案 B：在 ExecutionRequest 里加 visitor_id 字段，Service 层处理
```

## 6. 后端 API

### 6.1 现有接口（/api/v1/ext/）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/agents` | 列出可访问的 Agent |
| GET | `/agents/{id}` | 获取 Agent 详情 |
| POST | `/agents/{id}/invoke` | 同步调用 |
| POST | `/agents/{id}/invoke/stream` | SSE 流式调用 ✅ |
| POST | `/agents/{id}/invoke/resume` | 恢复中断的对话 |

### 6.2 请求格式

```typescript
// 流式调用
POST /api/v1/ext/agents/{agentId}/invoke/stream
Headers:
  X-Api-Key: sk-xxx
  Content-Type: application/json
Body:
{
  "message": "你好",
  "session_id": "xxx",     // 首次为空，后端返回后保存
  "visitor_id": "550e8400" // 前端生成
}
Response Headers:
  X-Session-Id: new-session-id
```

## 7. 用户接入方式

```html
<!-- 1. 引入 JS -->
<script src="https://your-agent-flow.com/static/agent-chat.js"></script>

<!-- 2. 初始化 -->
<script>
  AgentChat.init({
    apiKey: 'sk-xxx',           // 必填：API Key
    agentId: 'agent-123',       // 必填：Agent ID
    apiBaseUrl: 'https://your-agent-flow.com',  // 必填：后端地址
    title: '智能助手',           // 可选：聊天窗口标题（默认"AI 助手"）
    position: 'bottom-right',   // 可选：位置（默认 bottom-right）
  });
</script>
```

## 8. MVP 功能清单

- [x] SSE 流式输出
- [x] Markdown 渲染
- [x] 新建会话
- [x] 会话历史保留（基于 visitor_id）
- [x] 浮窗按钮（可展开/收起）
- [x] 错误提示（网络错误、认证失败等）

## 9. 后续迭代（非 MVP）

- 文件上传
- 思考过程 / 工具调用展示
- 亮/暗主题切换
- npm 包发布
- 自定义样式（主题色、Logo）
- 多 Agent 切换

## 10. 风险与缓解

| 风险 | 缓解措施 |
|------|----------|
| 后端需要改动支持 visitor_id | 小改一处，影响可控 |
| localStorage 被清除导致会话丢失 | 可接受，MVP 范围内 |
| 第三方脚本被拦截 | 提供 npm 包作为备选（后续迭代） |

## 11. 部署

构建产物 `agent-chat.js` 托管方式：
1. 上传到 agent-flow 后端的 `/static/` 目录
2. 用户通过 `https://your-agent-flow.com/static/agent-chat.js` 引入
