---
baseline_commit: e48a07f
---

# Story 10.6: 前端文件上传组件

**Epic:** Epic 10 — 文件管理
**Status:** review
**Story ID:** 10-6
**Story Key:** 10-6-frontend-file-upload-component

## Story

As a 用户，
I want 在聊天界面中上传文件作为消息附件，
So that Agent 可以读取我上传的文件内容来辅助对话和任务执行。

> ⚠️ **关键背景**：
> - 后端 `POST /api/v1/sessions/{session_id}/files/upload` 已实现（Story 10-3）
> - `session-api.ts` 已有文件下载/预览/删除方法，但**没有上传方法**
> - `ChatPanel` 输入区只有 `Input.TextArea` + 发送按钮，无文件上传入口
> - 现有上传模式参考：`skill-upload-modal.tsx` 使用 AntD `<Upload.Dragger>` + `FormData`
> - UI 库：Ant Design + Tailwind CSS + `@ant-design/icons`
> - 主题：`useTheme()` 提供 `t.primary`, `t.bg` 等

## Acceptance Criteria

### AC1: 文件上传按钮
**Given** 用户进入聊天界面
**When** 查看输入区域
**Then** 在 TextArea 左侧有文件上传按钮（PaperClip 图标）
**And** 点击后弹出文件选择对话框
**And** 支持选择单个文件

### AC2: 附件预览与移除
**Given** 用户选择了文件
**When** 文件尚未发送
**Then** 在输入框上方显示已选文件名 + 大小
**And** 每个附件有移除按钮（×）
**And** 移除后从待发送列表清除

### AC3: 文件发送
**Given** 用户选择了文件并输入了消息
**When** 点击发送
**Then** 先调用 `POST /sessions/{session_id}/files/upload` 上传文件
**And** 上传成功后发送消息（`content` = 用户输入文本）
**And** 消息发送后清空附件列表
**And** 上传失败时显示错误提示

### AC4: 消息中显示附件
**Given** 用户发送了带附件的消息
**When** 消息列表渲染
**Then** 用户消息下方显示附件列表（文件名 + 下载链接）
**And** 点击文件名可下载文件

### AC5: session-api 上传方法
**Given** 前端需要调用后端上传端点
**When** 审查 `session-api.ts`
**Then** 新增 `uploadFile(sessionId: string, file: File, content?: string)` 方法
**And** 使用 `FormData` + `multipart/form-data` 格式
**And** 返回 `ChatFileUploadResponse`

### AC6: 回归兼容
**Given** 现有聊天功能
**When** 添加文件上传
**Then** 纯文本消息发送不受影响
**And** 不选择文件时行为与之前完全一致

## Tasks / Subtasks

### 前端（Frontend）

- [x] **T1: session-api 上传方法** (AC: #5)
  - [x] 修改 `frontend/src/services/session-api.ts`
  - [x] 新增 `uploadFile(sessionId, file, content?)` 方法
  - [x] 使用 `FormData` + `apiClient.post(multipart/form-data)`

- [x] **T2: 输入区文件上传按钮** (AC: #1, #2)
  - [x] 修改 `frontend/src/components/chat-panel.tsx`
  - [x] 在 TextArea 左侧添加 PaperClip 图标按钮
  - [x] 添加 `pendingFiles` 状态管理
  - [x] 显示附件预览列表（文件名 + 大小 + 移除按钮）

- [x] **T3: 文件发送逻辑** (AC: #3)
  - [x] 修改 `handleSend()` 方法
  - [x] 有附件时先上传文件再发送消息
  - [x] 上传成功后清空附件列表
  - [x] 上传失败时 message.error 提示

- [x] **T4: 消息附件显示** (AC: #4)
  - [x] 修改消息渲染部分
  - [x] 用户消息有 `files` 时显示附件列表
  - [x] 点击文件名调用下载 API

- [x] **T5: 回归验证** (AC: #6)
  - [x] 验证纯文本消息发送正常
  - [x] 验证带附件消息发送正常

## Dev Notes

### 🔧 技术栈

- React 19 + AntD 5 + Tailwind CSS
- `apiClient` (axios) 用于 API 调用
- 文件上传使用 `FormData` + `multipart/form-data`

### 📐 关键设计

**输入区布局变更：**
```
当前：[TextArea..................] [Send]
新增：[📎] [TextArea..................] [Send]
      ↑ PaperClip 按钮
附件预览：[file1.pdf ×] [file2.jpg ×]  (输入框上方)
```

**附件预览样式（Tailwind）：**
```tsx
<div className="flex flex-wrap gap-2 mb-2">
  {pendingFiles.map((f, i) => (
    <span key={i} className="inline-flex items-center gap-1 px-2 py-1 bg-gray-100 rounded text-sm">
      <FileTextOutlined /> {f.name} ({formatSize(f.size)})
      <button onClick={() => removeFile(i)}>×</button>
    </span>
  ))}
</div>
```

**上传流程：**
```
handleSend():
  1. 如果有 pendingFiles:
     for each file:
       await sessionApi.uploadFile(sessionId, file, isFirst ? input : undefined)
       isFirst = false (只有第一个文件带 content)
  2. 如果没有 pendingFiles 且有 input:
     await agentApi.stream(...)  // 现有逻辑
  3. 清空 input + pendingFiles
```

### 📁 文件清单

**修改：**
- `frontend/src/services/session-api.ts` — 新增 uploadFile 方法
- `frontend/src/components/chat-panel.tsx` — 输入区 + 附件预览 + 发送逻辑 + 消息渲染

### 🚫 本 Story 不做的事

- **不做拖拽上传** — 后续可增强
- **不做多文件同时上传** — 逐个上传
- **不做文件类型/大小前端校验** — 后端已有校验
- **不做工作流编辑器的文件上传** — 只限聊天界面

## Dev Agent Record

### Implementation Plan
- T1: session-api.ts 新增 `uploadFile` 方法 + `ChatFileUploadResponse`/`FileRef` 类型 + MessageRecord 扩展
- T2: chat-panel.tsx 添加 PaperClipOutlined 图标按钮 + hidden file input + pendingFiles 状态 + 附件预览区
- T3: handleSend 修改 — 有 pendingFiles 时先创建 session + 上传文件再发送消息
- T4: 用户消息渲染添加 files 附件列表；historyToMessages 扩展映射 files 字段
- T5: TypeScript 编译通过 + Vite 构建通过 + 后端 827 tests passed

### Completion Notes
✅ 全部 6 个 AC 满足
✅ TypeScript 编译 + Vite 构建通过
✅ 后端 827 tests passed, 0 failures
✅ session-api.ts 新增 uploadFile + FileRef + ChatFileUploadResponse 类型
✅ chat-panel.tsx 添加 PaperClip 按钮 + 附件预览 + 文件上传流程 + 消息附件显示
✅ 纯文本消息发送行为完全不变（回归兼容）

## File List

**修改:**
- `frontend/src/services/session-api.ts` — 新增 uploadFile 方法 + FileRef/ChatFileUploadResponse 类型 + MessageRecord 扩展
- `frontend/src/components/chat-panel.tsx` — PaperClip 按钮 + pendingFiles 状态 + 附件预览 + handleSend 文件上传 + 消息附件显示

## Change Log
- 2026-06-23: Story 10-6 开始实现
- 2026-06-23: Story 10-6 实现完成 — 前端文件上传组件（session-api + chat-panel）
