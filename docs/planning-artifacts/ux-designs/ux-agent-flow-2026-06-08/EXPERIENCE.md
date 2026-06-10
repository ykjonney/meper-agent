---
status: final
updated: 2026-06-09
brand: Agent Flow
form_factor: web-desktop-primary
---

# Agent Flow — EXPERIENCE.md

> Information architecture, behavior, states, interactions, accessibility, and key flows for Agent Flow.
> Visual identity lives in **DESIGN.md** — this file owns *how it works*.
> Spines win on conflict with any mock, wireframe, or import.

## Foundation

**Form factor:** Web desktop primary (90%), tablet usable (10%), mobile deferred.
**UI system:** Ant Design 6.x with brand customization (see `DESIGN.md`).
**Target users:**
- **Platform developers (30+):** Build, configure, and debug Agents and workflows. High technical background.
- **Business operators (25-40):** Consume Agent capabilities through conversations and triggered workflows. Medium technical background.

**Stakes:** Internal (B-end industrial). Reliability and consistency over delight.

**Stated needs (from PRD/Brief, 11 feature groups):**
1. Create and configure Agents (prompt, tools, knowledge, workflows, model preference)
2. Visual DAG workflow editor with 5 core node types
3. Autonomous Agent execution (REACT / plan-execute-verify)
4. Tool system (Skills + MCP)
5. Knowledge base (vector search)
6. External API/SDK for system integration
7. Web conversation interface (streaming)
8. Execution logs and trace
9. RBAC (4 roles)
10. Context management (compression, cross-node data flow)
11. Nested depth protection (Agent → workflow → Agent ≤ 2)

## Information Architecture

### App shell (always present)

```
┌─────────────────────────────────────────────────────────────┐
│  [Logo]  Agent Flow    [Search]              [User] [Help]   │  56px Header
├──────┬──────────────────────────────────────────────────────┤
│      │                                                       │
│  S   │                                                       │
│  I   │              Main Content Area                        │
│  D   │              (max-width 1440px, centered)             │
│  E   │                                                       │
│  B   │                                                       │
│  A   │                                                       │
│  R   │                                                       │
│  240 │                                                       │
│      │                                                       │
└──────┴──────────────────────────────────────────────────────┘
```

### Sidebar navigation (left, 240px, collapsible to 64px)

Items ordered by user flow frequency:

| Icon | Label | Route | Roles |
|------|-------|-------|-------|
| `DashboardOutlined` | 工作台 | `/dashboard` | All |
| `MessageOutlined` | 对话 | `/conversations` | All |
| `RobotOutlined` | Agent 管理 | `/agents` | Developer+ |
| `ShrinkOutlined` | 工作流 | `/workflows` | Developer+ |
| `ToolOutlined` | 工具中心 | `/tools` | Developer+ |
| `BookOutlined` | 知识库 | `/knowledge` | Developer+ |
| `FileTextOutlined` | 执行日志 | `/executions` | All (own only) |
| `KeyOutlined` | API Key | `/api-keys` | Admin |
| `TeamOutlined` | 用户管理 | `/users` | Admin |
| `SettingOutlined` | 系统设置 | `/settings` | Admin |

Sidebar filtered by role (RBAC). Items hidden for unauthorized roles, not just disabled.

### Top header (56px)

- **Left:** Logo + product name
- **Center:** Global search (Cmd+K palette) — searches Agents, workflows, executions
- **Right:** Notifications · Help (?) · User avatar dropdown (Profile, Settings, Logout)

### Main content area

- Padding: 24px (page-level)
- Title: h1 (24px) + breadcrumb (12px tertiary) on top
- Right side: page actions (e.g., "新建 Agent" 按钮)

## Voice and Tone

**Brand voice:** Professional · Engineering · Direct · Helpful

**Microcopy principles:**

- **直接说事** — "保存失败" not "哎呀，出了点问题"
- **给可执行建议** — "保存失败：网络断开。请检查连接后重试" not just "Error 500"
- **避免感叹号** — 不用 "欢迎使用！" 用 "Agent Flow · 工作台"（常规提示场景）
- **代码/ID 用等宽字体** — `agent_01HXYZ` 而不是斜体
- **状态文字简短** — "执行中" not "正在为您执行 Agent..."

**Terminology consistency (zh-CN):**

| Concept | Canonical | Forbidden Alternatives |
|---------|-----------|------------------------|
| Agent | "Agent" (大写) | "智能体", "机器人" |
| Workflow | "工作流" | "流程", "管线" |
| Tool | "工具" | "插件", "能力" |
| Knowledge Base | "知识库" | "文档库", "资料" |
| Skill | "Skill" | "技能", "脚本" |
| MCP | "MCP" | "协议", "连接器" |
| Conversation | "对话" | "聊天", "会话" |
| Execution Log | "执行日志" | "运行记录" |
| API Key | "API Key" | "密钥", "凭据" |
| RAG / Vector Search | "向量检索" | "语义搜索" |

**Empty/loading/error copy patterns (zh-CN):**

- Empty: 居中 icon + "还没有 Agent" + "创建第一个 Agent" 按钮
- Loading: "加载中..." (page) / "AI 正在思考..." (streaming) / spinner only (button)
- Error: "保存失败" + 简短原因 + [重试] [取消]
- Success: Toast "已保存" 3 秒自动消失

## Component Patterns

> Behavior only. Visual specs: `DESIGN.md.Components.*`

### Buttons

- **Primary action** (rightmost position): Save, Publish, Invoke, Confirm
- **Default action** (left of primary): Cancel, Back, Reset
- **Danger action** (only in confirmation modals): Delete, Terminate execution
- **Text link** (inline in tables/cards): View, Edit, Copy ID, Export
- **Loading state:** Button disabled, spinner replaces icon, text becomes "处理中..."
- **Keyboard:** Enter triggers focused button; Esc triggers focused Cancel

### Inputs

- **Validation timing:** On blur (not on every keystroke) for non-required; on submit for required
- **Required indicator:** Red asterisk `*` after label
- **Error display:** Below input, red text, with hint (e.g., "请输入 1-50 个字符")
- **Disabled:** Background gray + cursor not-allowed + tooltip explaining why on hover
- **Autocomplete:** Agent names, tool names use AntD AutoComplete with backend search
- **Code/ID inputs:** Monospace font, no auto-capitalize

### Cards

- **Static card:** No hover effect. Used for display-only info.
- **Interactive card:** Hover background + subtle shadow. Click → navigate. Used for Agent/workflow tiles.
- **Loading card:** Skeleton placeholder with same shape. Used for list pages during fetch.

### Tables

- **Pagination:** Server-side, default page size 20, options [10, 20, 50, 100]
- **Sorting:** Click column header to sort; indicator on active column
- **Filtering:** Column header filter icon → dropdown filter
- **Selection:** Checkbox column; bulk action bar appears at top
- **Row actions:** Rightmost column, 2-3 text actions + overflow menu
- **Empty:** AntD Empty component, centered
- **Loading:** AntD Skeleton, 5 rows

### Modals / Drawers

- **Confirm modal:** Title + body + [Cancel] [Confirm] (default focus on Cancel for safety)
- **Form modal:** Title + scrollable form + [Cancel] [Save] (Save disabled until valid)
- **Detail drawer:** Title + content (read-only) + [Close]
- **Create drawer:** Title + form (multi-section, vertical) + [Cancel] [Create]
- **Focus trap:** Tab cycles within modal; Shift+Tab cycles backward
- **Esc:** Closes modal (except confirm-danger which requires explicit click)
- **Click outside:** Closes for non-danger modals; ignored for danger confirms

### Notifications / Toasts

- **Success:** Top-right, green border, 3s auto-dismiss
- **Error:** Top-right, red border, sticky (manual dismiss)
- **Info:** Top-right, blue border, 4s auto-dismiss
- **Warning:** Top-right, orange border, 5s auto-dismiss
- **Stacking:** Max 3 visible; oldest gets dismissed on overflow

## State Patterns

### Universal state matrix

Every async-driven component must handle 5 states:

| State | Visual | Behavior |
|-------|--------|----------|
| **Loading** (initial) | Skeleton or Spinner | Disable interaction |
| **Loading** (background refetch) | Subtle spinner in corner | Keep showing stale data |
| **Empty** | AntD Empty + CTA | Provide next action |
| **Error** | Inline error component | Show message + [Retry] |
| **Success** | Component normal state | Default |

### Streaming / Live states

- **AI thinking:** Cyan pulsing dot + "AI 正在思考..." text in chat bubble
- **Token streaming:** Incremental text append, cursor blinks
- **Workflow executing:** Active node pulses (cyan glow), executed nodes turn green
- **Long task (async):** Progress bar in toast; redirect to execution log on click

### Agent / Workflow lifecycle states

| State | Visual | Actionable? |
|-------|--------|-------------|
| **草稿 (Draft)** | Gray tag, dot icon | Edit, Publish, Delete |
| **已发布 (Published)** | Green tag, check icon | Invoke, Edit (creates new version), Archive |
| **执行中 (Running)** | Blue tag with pulse, spinner | View (read-only), Terminate |
| **已归档 (Archived)** | Tertiary gray tag | Restore, Delete (after 30 days) |

### Form states

- **Pristine:** Default styling
- **Dirty (modified):** Slight border tint indicator (optional, post-MVP)
- **Validating:** Spinner next to submit button
- **Invalid (after submit):** Red borders on invalid fields, scroll to first error, focus
- **Submitting:** Form disabled, submit button shows spinner
- **Submitted:** Success toast, modal closes, list refreshes

## Interaction Primitives

### Keyboard shortcuts (global)

| Key | Action | Scope |
|-----|--------|-------|
| `Cmd/Ctrl + K` | Open search palette | Global |
| `Cmd/Ctrl + S` | Save (in editor/form) | Form context |
| `Cmd/Ctrl + Enter` | Submit form / Send message | Form/Chat |
| `Esc` | Close modal/drawer/cancel edit | Modal/Drawer |
| `/` | Focus search | Global (when not in input) |
| `?` | Open keyboard shortcut help | Global |
| `g` then `d` | Go to Dashboard | Global (vim-style) |
| `g` then `a` | Go to Agents | Global |
| `g` then `w` | Go to Workflows | Global |

### Search palette (Cmd+K)

- Triggered from any page
- Type to filter: Agents, workflows, recent items
- Arrow keys to navigate, Enter to open
- Esc to close
- Recent items shown when input empty

### Drag-and-drop (workflow editor)

- **Source:** Left node palette (5 core types: Agent, Tool, Condition, Code, LLM)
- **Target:** Canvas (workspace)
- **Visual feedback:** Node ghost follows cursor; valid drop zones highlighted
- **Connection drawing:** Drag from output handle to input handle of another node
- **Multi-select:** Shift+click or drag-rectangle
- **Copy/paste:** Cmd+C / Cmd+V (paste with offset)
- **Undo/redo:** Cmd+Z / Cmd+Shift+Z (history depth 50)

### Form patterns

- **Multi-step form (Agent creation):**
  1. Basic info (name, description, model)
  2. Capability selection (tools, knowledge bases, workflows)
  3. Prompt template
  4. Test & publish
- **Wizard pattern:** AntD Steps component, [上一步] [下一步] [保存草稿]
- **Save draft:** Available on every step; preserves entered data

## Accessibility Floor

> Behavior only. Visual contrast: `DESIGN.md.Colors` (all text/bg pairs ≥ 4.5:1)

### Keyboard navigation

- **Tab order:** Top-to-bottom, left-to-right, follows visual order
- **Skip links:** "Skip to main content" hidden until focused
- **Focus indicators:** Always visible 2px primary outline (never `outline: none`)
- **No keyboard traps:** All interactive elements reachable and exit-able by keyboard

### Screen reader support

- **Semantic HTML:** `<button>` not `<div onClick>`, `<nav>` for navigation, `<main>` for content
- **ARIA labels:** All icon-only buttons have `aria-label` (AntD handles this for known icons)
- **Live regions:** Toasts use `aria-live="polite"`; errors use `aria-live="assertive"`
- **Form labels:** All inputs have associated `<label>` (AntD Form handles this)

### Workflow editor accessibility (challenging)

- **Keyboard alternative:** Tab to navigate nodes; Enter to "open" node; arrow keys to move focus between nodes
- **Screen reader:** Each node has `aria-label` with name + type + status
- **Connections:** Edges described as "connects [from node] to [to node]"

### Color independence

- **Status never relies on color alone:** Tags always include text + icon, not just colored background
- **Required fields:** Red asterisk + "required" word, not just color

## Key Flows

### Flow 1: Mary (developer) creates her first Agent

> **Protagonist:** Mary, 32, backend developer at manufacturing company. First time using Agent Flow.

1. **Entry:** Mary logs in → lands on empty Dashboard with "创建第一个 Agent" CTA
2. **Click CTA:** Navigates to `/agents/new` → wizard step 1 (Basic info)
3. **Step 1:** Enters name "质量分析助手" + description + selects LLM model (Claude Sonnet) → [下一步]
4. **Step 2:** Adds 2 Skills (file_search, code_exec) + 1 MCP server (MES query) → [下一步]
5. **Step 3:** Writes system prompt (large textarea with template hints) → [下一步]
6. **Step 4:** Tests with sample input in side panel → sees successful response → [发布]
7. **Success:** Toast "Agent 已发布" + redirect to Agent detail page
8. **Continue:** Mary invites operator (Step 9) or starts conversation directly

**Climax beat:** Step 4 test response — seeing the Agent actually work in real-time is the "aha" moment that converts Mary to power user.

**UI states covered:** Loading (step transitions), Validation (form), Empty (first-time), Success (toast + redirect)

### Flow 2: Lao Wang (operator) uses Agent via conversation

> **Protagonist:** Lao Wang, 38, factory floor supervisor. Uses Agent to check quality reports.

1. **Entry:** Lao Wang logs in → lands on Dashboard with "最近对话" list
2. **Click new conversation:** Navigates to `/conversations/new` → agent selector
3. **Select Agent:** Picks "质量分析助手" (published by Mary) → conversation starts
4. **Type message:** "本周不良率最高的工序是哪个？"
5. **Streaming:** "AI 正在思考..." → tokens stream in → tool call visible (查 MES 数据) → final answer
6. **Follow-up:** Lao Wang asks "导出 CSV" → workflow triggered (export_csv) → file downloaded
7. **Save:** Auto-saved to history, accessible from sidebar

**Climax beat:** Tool call visualization (Step 5) — operator sees that the Agent is *doing something real*, not just chatting. Builds trust.

**UI states covered:** Streaming, Loading, Tool call display, Workflow trigger, File download

### Flow 3: System integration engineer sets up API key

> **Protagonist:** Xiao Chen, 28, integration engineer. Connects MES system to Agent Flow.

1. **Entry:** Logs in → navigates to `/api-keys` (admin only)
2. **Click "创建 API Key":** Modal with name input + scope selector
3. **Configure:** Names it "MES-Quality" + selects scopes (agents:invoke, executions:read)
4. **Generate:** [生成] → key shown ONCE in modal with copy button + "请妥善保存，不会再次显示" warning
5. **Setup webhook:** Configures callback URL + selects events (agent.completed, agent.failed)
6. **Test:** [发送测试回调] → sees 200 OK response
7. **Save:** Toast "已创建" + key list refreshed

**Climax beat:** One-time key display with copy button (Step 4) — security-critical moment that must be frictionless yet safe.

**UI states covered:** Permission-gated access, Modal (one-time display), Webhook config, Test action

## Responsive & Platform

### Desktop (primary, 90%)

- Full sidebar visible
- Multi-column layouts (3-col for dashboard cards)
- All features fully accessible

### Tablet (10%)

- Sidebar collapsed to icons (64px)
- 2-column layouts where applicable
- Workflow editor: full-width canvas, simplified toolbar
- **Limitation:** Complex forms may require landscape orientation

### Mobile (deferred)

`[ASSUMPTION]` Mobile is not supported in MVP. Show "请使用桌面浏览器" message if accessed on phone-width viewport.

## Open Concerns (per-feature)

| Feature | Concern | Post-MVP? |
|---------|---------|-----------|
| Workflow editor | Performance with >100 nodes (memory, render lag) | Optimization Sprint |
| Conversation | Long context scroll (10K+ tokens) | Virtualization Sprint |
| Logs | Real-time log streaming at high QPS | Pagination + filter |
| Knowledge | Drag-drop upload with progress | Standard |
| API Keys | Key rotation workflow | Add later |

## Notes for Implementation

- **AntD customization:** Use `ConfigProvider` with theme tokens in `app.tsx`
- **Tailwind integration:** Use `tailwindcss-antd` preset for token alignment
- **Routing:** React Router v7 data routes with role guards
- **State boundaries:** See architecture.md (TanStack Query + Zustand + AntD Form)
- **Test coverage:** Every state in the "Universal state matrix" must have a Storybook story

### Mock-first development pattern

Frontend uses a **Mock Adapter layer** approach (not MSW):

1. **Service layer abstraction:** Each feature module has a `services/` directory with type-hinted service interfaces
2. **Mock implementation:** `services/__mock__/` provides fake data with realistic latency simulation (200-800ms random delay)
3. **Toggle mechanism:** A `useMock` flag (env var or zustand store toggle) switches between mock and real API calls
4. **Dev workflow:** All frontend pages are built and tested against mock data first; real API integration comes later
5. **Mock data quality:** Mock data must mirror real API shapes exactly (same fields, types, pagination structure) to prevent integration friction
