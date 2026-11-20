# TodoPanel 重设计实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 todo_write 清单从会话流内快照卡改为顶栏右侧折叠胶囊面板（仅最新快照、随会话恢复、清空即消失）。

**Architecture:** 渲染层过滤（ActivityGroup 入口排除 todo_write）+ timeline 派生（`extractLatestTodos` 倒序扫 `liveMessages`）+ 新组件 TodoPanel（SessionHeader 内渲染）。落库 timeline 保持完整，零后端改动。

**Tech Stack:** React 19 + TypeScript + Tailwind 4（语义 token：`theme-indigo` 机制）+ lucide-react 图标。

**Spec:** `docs/superpowers/specs/2026-11-10-todo-panel-redesign-design.md`

## Global Constraints

- 前端目录：`frontend-studio/`，所有路径相对仓库根
- 验证命令：`cd frontend-studio && npx tsc --noEmit`（lint）与 `npm run build`
- **无测试框架**（package.json 无 test script、无 vitest/jest）：不为本功能引入测试基建（surgical changes），每个任务以 tsc + build + 手测清单收尾
- 只用语义色 token（`bg-panel/border-line/text-ink/text-ink-soft/text-ink-faint/text-brand/text-sig-ok` 等），**禁止裸 hex / 渐变 / emoji 图标**
- 图标用 lucide-react（语义图标），注释语言与既有代码一致（中文为主）
- 自主 commit（memory: auto-commit-policy），每任务一 commit
- 不改动 message-utils.ts / tool-details.tsx 顶部历史遗留的未使用 imports（pre-existing 死代码，不在本任务范围）；**但本改动自己产生的孤儿 import 必须清理**

---

### Task 1: `extractLatestTodos` 派生函数（message-utils.ts）

**Files:**
- Modify: `frontend-studio/src/components/chat/message-utils.ts`（在 `parseOutputAttachments` 之后、`doneTimelineToEntries` 之前插入）

**Interfaces:**
- Consumes: `Message` 类型（`message-utils.ts` 顶部已 import）
- Produces:
  - `export interface TodoItem { content: string; status: string }`
  - `export function parseTodoItems(args: unknown): TodoItem[]`
  - `export function extractLatestTodos(messages: Message[]): TodoItem[] | null`（Task 4 的 ChatHomepage 消费）

- [ ] **Step 1: 在 `parseOutputAttachments` 函数后插入三段代码**

```ts
export interface TodoItem {
  content: string;
  status: string;
}

/** 解析 todo_write 的 args → 清单项（非法项过滤）。
 *  自 ToolEntryCard.parseTodoItems 迁入（会话流内不再渲染 todo 卡）。 */
export function parseTodoItems(args: unknown): TodoItem[] {
  const todos = (args as { todos?: unknown } | undefined)?.todos;
  if (!Array.isArray(todos)) return [];
  return todos
    .filter(
      (t): t is { content?: unknown; status?: unknown } =>
        typeof t === 'object' && t !== null,
    )
    .map((t) => ({
      content: String(t.content ?? ''),
      status: String(t.status ?? 'pending'),
    }));
}

/** 最新任务清单快照（顶栏 TodoPanel 数据源）：倒序找最后一条 todo_write
 *  的 timeline 条目；清空调用（todos=[]，任务闭环）或无记录 → null。
 *  仅扫 tool_call 条目的 args（全量替换语义，最后一次调用即当前清单）。 */
export function extractLatestTodos(messages: Message[]): TodoItem[] | null {
  for (let mi = messages.length - 1; mi >= 0; mi--) {
    const tl = messages[mi].timeline;
    if (!tl) continue;
    for (let i = tl.length - 1; i >= 0; i--) {
      const e = tl[i];
      if (e.type === 'tool' && e.toolName === 'todo_write') {
        const items = parseTodoItems(e.args);
        return items.length ? items : null;
      }
    }
  }
  return null;
}
```

- [ ] **Step 2: 类型检查**

Run: `cd frontend-studio && npx tsc --noEmit`
Expected: 无错误（退出码 0）

- [ ] **Step 3: Commit**

```bash
git add frontend-studio/src/components/chat/message-utils.ts
git commit -m "feat(chat): extractLatestTodos 派生最新任务清单快照(顶栏面板数据源)"
```

---

### Task 2: 会话流内移除 todo_write 渲染

**Files:**
- Modify: `frontend-studio/src/components/chat/ActivityGroup.tsx:175-179`（meaningful 过滤器）
- Modify: `frontend-studio/src/components/chat/ToolEntryCard.tsx:155-160`（todo_write 分支）、`398-473`（parseTodoItems / TODO_GLYPHS / TodoListCard）、`5`（ClipboardList import）

**Interfaces:**
- Consumes: 无（本任务是纯移除）
- Produces: 会话流内不再出现 todo_write 条目；`parseTodoItems` 唯一事实源移至 message-utils.ts（Task 1）

- [ ] **Step 1: ActivityGroup 的 meaningful 过滤器加 todo_write 排除**

`ActivityGroup.tsx` 175-179 行改为：

```ts
  const meaningful = entries.filter((e) => {
    if (e.type === 'thinking' && !(e.content ?? '').trim()) return false;
    // todo_write 走顶栏 TodoPanel（最新快照），会话流内不再渲染——
    // 入口过滤保证组头计数与展开行数自动一致。
    if (e.type === 'tool' && e.toolName === 'todo_write') return false;
    if (e.type === 'tool') return Boolean(e.toolName);
    return true;
  });
```

- [ ] **Step 2: 删除 ToolEntryCard 的 todo_write 分支**

`ToolEntryCard.tsx` 155-160 行整段删除：

```tsx
  // todo_write：任务清单卡片（checkbox 清单快照；全量替换语义下每次调用
  // 展示当次的完整清单）。解析失败落通用工具卡。
  if (entry.toolName === 'todo_write') {
    const todoItems = parseTodoItems(entry.args);
    if (todoItems.length) return <TodoListCard todos={todoItems} theme={theme} />;
  }
```

- [ ] **Step 3: 删除 parseTodoItems / TODO_GLYPHS / TodoListCard**

`ToolEntryCard.tsx` 398-473 行整段删除（三个连续声明：`parseTodoItems` 函数、`TODO_GLYPHS` 常量、`TodoListCard` 组件）。

- [ ] **Step 4: 清理孤儿 import**

`ToolEntryCard.tsx` 第 5 行 lucide imports 中删除 `ClipboardList`（仅 TodoListCard 使用，已随 Step 3 删除；该文件其余组件不使用它）。

- [ ] **Step 5: 类型检查 + 构建**

Run: `cd frontend-studio && npx tsc --noEmit && npm run build`
Expected: 两者均成功退出码 0

- [ ] **Step 6: 手测（dev server）**

Run: `cd frontend-studio && npm run dev`
检查：历史会话（含 todo_write 记录）打开后，会话流执行过程组内**无** todo_write 条目，组头「N 个工具调用」计数与展开行数一致。

- [ ] **Step 7: Commit**

```bash
git add frontend-studio/src/components/chat/ActivityGroup.tsx frontend-studio/src/components/chat/ToolEntryCard.tsx
git commit -m "feat(chat): 会话流内移除 todo_write 渲染(清单改走顶栏面板)"
```

---

### Task 3: TodoPanel 组件

**Files:**
- Create: `frontend-studio/src/components/chat/TodoPanel.tsx`

**Interfaces:**
- Consumes: `TodoItem` 类型（Task 1，`./message-utils`）
- Produces: `export function TodoPanel({ todos }: { todos: TodoItem[] })`（Task 4 的 SessionHeader 消费）

- [ ] **Step 1: 创建 TodoPanel.tsx（完整文件）**

```tsx
import { useEffect, useRef, useState } from 'react';
import { Circle, CircleCheck, CircleDot, ClipboardList } from 'lucide-react';
import type { TodoItem } from './message-utils';

/** TodoPanel — 顶栏右侧任务清单：折叠胶囊(n/m 进度) + 点击展开最新快照卡。
 *  数据由 ChatHomepage 从 timeline 派生（extractLatestTodos）；清单清空
 *  （todos=[]，任务闭环）由调用方整个卸载，本组件不处理空列表。
 *  状态视觉：进行中 text-brand / 完成 text-ink-faint 删除线 / 待办 text-ink-soft；
 *  全语义 token，theme-indigo 明暗自适应，无 theme prop。 */
export function TodoPanel({ todos }: { todos: TodoItem[] }) {
  const [open, setOpen] = useState(false);
  const openRef = useRef(open);
  openRef.current = open;
  const autoTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // 挂载即自动展开一次（让用户注意到清单建立），2.5s 后自动收起；
  // 手动 toggle 取消未触发的定时器（手动操作优先）。
  useEffect(() => {
    setOpen(true);
    autoTimer.current = setTimeout(() => {
      if (openRef.current) setOpen(false);
    }, 2500);
    return () => {
      if (autoTimer.current) clearTimeout(autoTimer.current);
    };
  }, []);

  const toggle = () => {
    if (autoTimer.current) {
      clearTimeout(autoTimer.current);
      autoTimer.current = null;
    }
    setOpen((v) => !v);
  };

  const done = todos.filter((t) => t.status === 'completed').length;
  const doing = todos.some((t) => t.status === 'in_progress');
  const allDone = done === todos.length;
  const accent = allDone ? 'text-sig-ok' : doing ? 'text-brand' : 'text-ink-dim';

  return (
    <div className="relative shrink-0">
      <button
        type="button"
        onClick={toggle}
        className="h-8 flex items-center gap-1.5 px-2.5 bg-panel border border-line rounded-full shadow-[var(--shadow-card)] cursor-pointer transition hover:border-line-strong"
        title="任务清单"
      >
        <ClipboardList className={`w-3.5 h-3.5 ${accent}`} />
        <span className={`text-[11px] font-semibold font-mono tabular-nums ${accent}`}>
          {done}/{todos.length}
        </span>
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={toggle} />
          <div className="absolute right-0 top-full mt-2 z-50 w-72 bg-panel rounded-[10px] shadow-[var(--shadow-pop)] border border-line p-1.5 animate-fade-in">
            <div className="px-2 pt-1 pb-1.5 flex items-center gap-1.5">
              <span className="af-label">任务清单</span>
              <span className={`ml-auto text-[10.5px] font-mono tabular-nums ${allDone ? 'text-sig-ok' : 'text-ink-faint'}`}>
                {done}/{todos.length}
              </span>
            </div>
            <ul className="flex flex-col gap-0.5">
              {todos.map((t, i) => (
                <li key={i} className="flex items-center gap-2 px-2 py-1 rounded-lg">
                  {t.status === 'completed' ? (
                    <CircleCheck className="w-3.5 h-3.5 shrink-0 text-ink-faint" />
                  ) : t.status === 'in_progress' ? (
                    <CircleDot className="w-3.5 h-3.5 shrink-0 text-brand" />
                  ) : (
                    <Circle className="w-3.5 h-3.5 shrink-0 text-ink-soft" />
                  )}
                  <span
                    className={`min-w-0 flex-1 text-[12px] truncate ${
                      t.status === 'completed'
                        ? 'text-ink-faint line-through'
                        : t.status === 'in_progress'
                          ? 'text-ink font-medium'
                          : 'text-ink-soft'
                    }`}
                  >
                    {t.content}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        </>
      )}
    </div>
  );
}
```

- [ ] **Step 2: 类型检查**

Run: `cd frontend-studio && npx tsc --noEmit`
Expected: 无错误

- [ ] **Step 3: Commit**

```bash
git add frontend-studio/src/components/chat/TodoPanel.tsx
git commit -m "feat(chat): TodoPanel 顶栏胶囊组件(折叠 n/m 进度+展开清单快照)"
```

---

### Task 4: 接线（SessionHeader + ChatHomepage）

**Files:**
- Modify: `frontend-studio/src/components/chat/SessionHeader.tsx`（props + 渲染 TodoPanel）
- Modify: `frontend-studio/src/components/ChatHomepage.tsx`（useMemo 派生 + 传 prop；SessionHeader 调用处约 1490 行）

**Interfaces:**
- Consumes: `extractLatestTodos`（Task 1）、`TodoPanel`（Task 3）
- Produces: 完整功能闭环

- [ ] **Step 1: SessionHeader 加 todos prop 并渲染 TodoPanel**

`SessionHeader.tsx` 完整替换为：

```tsx
import { PanelRight } from 'lucide-react';
import type { Dispatch, SetStateAction } from 'react';
import type { Agent } from '../../types';
import type { Session } from '../../services/session-api';
import { AgentPicker } from './AgentPicker';
import { TodoPanel } from './TodoPanel';
import type { TodoItem } from './message-utils';

interface SessionHeaderProps {
  activeSession: Session | null;
  agents: Agent[];
  activeAgent: Agent | null;
  agentMenuOpen: boolean;
  setAgentMenuOpen: Dispatch<SetStateAction<boolean>>;
  onSelectAgent: (ag: Agent) => void;
  panelOpen: boolean;
  onTogglePanel: () => void;
  modelLabel: (id?: string) => string;
  /** 当前任务清单（timeline 派生）；null/undefined = 无清单，面板不渲染。 */
  todos?: TodoItem[] | null;
}

/** 2a. 会话顶栏：执行者切换 + 衬线会话标题 + 任务清单胶囊 + 功能区开关 */
export function SessionHeader({
  activeSession, agents, activeAgent, agentMenuOpen, setAgentMenuOpen, onSelectAgent,
  panelOpen, onTogglePanel, modelLabel, todos,
}: SessionHeaderProps) {
  return (
    <div className="px-5 h-12 shrink-0 flex items-center gap-3 border-b border-line">
      <AgentPicker
        agents={agents} activeAgent={activeAgent}
        open={agentMenuOpen} onToggle={() => setAgentMenuOpen(v => !v)} onClose={() => setAgentMenuOpen(false)}
        onSelect={onSelectAgent} modelLabel={modelLabel}
        menuClassName="absolute left-5 top-12"
      />
      <span className="text-[13.5px] font-bold text-ink truncate flex-1" style={{ fontFamily: 'var(--font-serif)' }}>
        {activeSession?.title || '未命名会话'}
      </span>
      {/* 任务清单：仅最新快照（Timeline 派生），清空后不渲染 */}
      {todos && todos.length > 0 && <TodoPanel todos={todos} />}
      {/* 功能区开关：产物与后续扩展面板 */}
      <button
        onClick={onTogglePanel}
        className={`w-8 h-8 rounded-lg flex items-center justify-center shrink-0 transition cursor-pointer ${
          panelOpen ? 'bg-brand-soft text-brand' : 'text-ink-dim hover:bg-raise hover:text-ink'
        }`}
        title={panelOpen ? '关闭功能区' : '打开功能区（产物）'}
      >
        <PanelRight className="w-4 h-4" />
      </button>
    </div>
  );
}
```

- [ ] **Step 2: ChatHomepage 派生并传 prop**

`ChatHomepage.tsx`：

1. import 区（`message-utils` 相关 import 处）加入 `extractLatestTodos`、`parseTodoItems` 无需——只加：
```ts
import { extractLatestTodos, INTERRUPT_TOOLS, isInterruptTool, parseOutputAttachments, agentMessageToDisplay, doneTimelineToEntries, userMessageToDisplay, updateMsg, fileRefToAttachment, formatSessionTime, clamp } from './chat/message-utils';
```
（以文件中现有 import 语句为准——在该条 import 的成员列表中追加 `extractLatestTodos` 即可，不要重写整条。）

2. `liveMessages` state 声明（约 240 行）之后加派生：
```ts
// 顶栏任务清单：timeline 派生最新快照（流式 tool_call 写入 timeline 后自动更新，
// done 后 getDetail 重载自然接管——单数据源，无独立状态通道）。
const currentTodos = useMemo(() => extractLatestTodos(liveMessages), [liveMessages]);
```

3. `<SessionHeader` 调用处（约 1490 行）追加 prop：
```tsx
todos={currentTodos}
```

- [ ] **Step 3: 类型检查 + 构建**

Run: `cd frontend-studio && npx tsc --noEmit && npm run build`
Expected: 均成功退出码 0

- [ ] **Step 4: 手测全场景（dev server + 真实会话）**

| 场景 | 预期 |
|---|---|
| 新会话触发 agent 建清单（3 步以上任务） | 面板胶囊出现并自动展开，2.5s 后收起 |
| agent 中途更新清单 | 胶囊 n/m 即时变化；会话流内无 todo 条目 |
| 全部完成（agent 传空列表清空） | 面板整体消失 |
| 刷新页面 / 切走再切回该会话 | 胶囊恢复显示最后清单 |
| 清空过的会话打开 | 无面板 |
| 含 todo_write 的执行过程组 | 组头计数与展开行数一致 |

- [ ] **Step 5: Commit**

```bash
git add frontend-studio/src/components/chat/SessionHeader.tsx frontend-studio/src/components/ChatHomepage.tsx
git commit -m "feat(chat): 顶栏 TodoPanel 接线——timeline 派生最新清单随会话恢复"
```

---

## Self-Review 记录

1. **Spec 覆盖**：§4.1 派生函数 → Task 1；§4.2 过滤与删除 → Task 2；§4.3 TodoPanel → Task 3；§4.4 接线 → Task 4。§2 四条需求决策全部落进 Task 3/4 行为与手测清单。无缺口。
2. **占位符**：无 TBD/TODO；所有代码步骤给全量代码。
3. **类型一致性**：`TodoItem`（Task 1 定义）→ Task 3 import `./message-utils` → Task 4 SessionHeader prop 类型一致；`TodoPanel({ todos }: { todos: TodoItem[] })` 与 SessionHeader 的 `{todos && todos.length > 0 && <TodoPanel todos={todos} />}` 匹配；`extractLatestTodos(messages: Message[]): TodoItem[] | null` 与 ChatHomepage 的 `currentTodos` 用法匹配。
