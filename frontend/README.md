# Agent Flow — Frontend

基于 React 19 + TypeScript + Vite 的前端应用，提供 Agent 对话、工作流可视化编排、文件管理等交互功能。

## 技术栈

| 类别 | 技术 |
|------|------|
| 框架 | React 19 + TypeScript |
| 构建 | Vite |
| UI 组件 | Ant Design 6 |
| 样式 | Tailwind CSS |
| 工作流画布 | @xyflow/react |
| 状态管理 | Zustand + TanStack React Query |
| HTTP | Axios |

## 目录结构

```
src/
├── components/   # 通用组件（ChatPanel、WorkflowEditor 等）
├── config/       # 环境配置
├── contexts/     # React Context（主题等）
├── features/     # 功能模块（工作流编辑器等）
├── hooks/        # 自定义 Hooks
├── lib/          # 工具函数
├── pages/        # 页面
├── services/     # API 调用层
├── stores/       # Zustand 状态管理
└── types/        # TypeScript 类型定义
```

## 开发

```bash
# 复制环境变量模板
cp .env.example .env

# 安装依赖
npm install

# 启动开发服务器
npm run dev

# 类型检查
npm run type-check

# 代码检查
npm run lint

# 生产构建
npm run build
```

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `VITE_API_BASE_URL` | 后端 API 地址 | `http://localhost:8000` |
| `VITE_WS_BASE_URL` | 后端 WebSocket 地址 | `ws://localhost:8000` |
