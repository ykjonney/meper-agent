# Agent Flow Chat Widget

可嵌入任意前端页面的聊天插件，通过 API Key 认证调用 agent-flow 后端 Agent。

## 特性

- 轻量级（gzip 后 ~13KB）
- Shadow DOM 样式隔离
- 响应式设计，支持拖拽调整窗口大小
- API Key 认证
- 多访客会话隔离
- 历史会话管理与删除
- 预定义引导问题

## 快速开始

### 1. 引入 JS

```html
<!-- 从后端服务器加载（后端通过 /static/ 托管） -->
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
    suggestedQuestions: ['问题1', '问题2'],  // 可选：覆盖默认预定义问题
  });
</script>
```

## 配置项

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| apiKey | string | 是 | API Key |
| agentId | string | 是 | Agent ID |
| apiBaseUrl | string | 是 | 后端 API 地址 |
| title | string | 否 | 聊天窗口标题，默认 "AI 助手" |
| position | string | 否 | 浮窗位置：`bottom-right` / `bottom-left` |
| suggestedQuestions | string[] | 否 | 预定义引导问题，覆盖内置默认值 |

## 预定义问题

Widget 内置 6 条默认引导问题，在聊天窗口空白状态显示：

1. 搭建工艺路线
2. 追溯SN条码的过站信息
3. 创建自定义表
4. 导入物料
5. 建模工厂数据
6. 查看工单生产状态

通过 `suggestedQuestions` 配置项可完全覆盖。

## 开发

```bash
# 安装依赖
npm install

# 开发模式
npm run dev

# 构建（输出 dist/agent-chat.js）
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
- Vite（IIFE 格式输出）
- Shadow DOM
