# Agent Flow Chat Widget

可嵌入任意前端页面的聊天插件，通过 API Key 认证调用 agent-flow 后端 Agent。

## 特性

- 轻量级（gzip 后 ~10KB）
- Shadow DOM 样式隔离
- 响应式设计
- API Key 认证
- 多访客会话隔离

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
| apiKey | string | 是 | API Key |
| agentId | string | 是 | Agent ID |
| apiBaseUrl | string | 是 | 后端 API 地址 |
| title | string | 否 | 聊天窗口标题 |
| position | string | 否 | 浮窗位置：`bottom-right` / `bottom-left` |

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
