# Todo 独立展示区（TodoPanel）重设计

- 日期：2026-11-10
- 状态：已批准（用户逐节确认）
- 范围：frontend-studio（零后端改动）

## 1. 背景与问题

`todo_write` 工具（后端三层机制：state.todos 持久化 / TodoSalienceMiddleware 重注入 / todo_final_gate 门控）的展示现状：

- 每次调用渲染一张 `TodoListCard` 快照卡，嵌在消息流的 `ActivityGroup`（执行过程组）内
- 正文开始输出 → 整组自动收起 → **清单被工具收起掩盖，用户看不到当前任务进度**
- 摘要行无 todo_write 人话分支（`toolSummary` 兜底显示裸工具名、detail 为空），展开易被误读为「参数是空的」

实证（MongoDB 落库核查）：模型参数从未丢失——6 条 `todo_write` 记录中 5 条 `args.todos` 完整，唯一空的是合法清空调用 `{"todos": []}`。「参数为空」是展示层现象，非数据 bug。

## 2. 需求决策记录

| 决策点 | 结论 |
|---|---|
| 会话流内 todo_write 条目 | **完全移除**（不留摘要行） |
| 面板内容 | **仅最新快照**（新版本覆盖，不做变更历史） |
| 历史会话打开/刷新 | **随会话恢复**最后清单（已被清空则不显示） |
| 面板形态 | **折叠胶囊**（点击展开下拉清单卡） |

## 3. 方案选择

**采用：渲染层隐藏 + timeline 派生面板（方案一）**

- 数据：`liveMessages` 已含全量 timeline（`getDetail` 全量加载已确认，分页仅针对会话列表）→ `useMemo` 派生最新清单。流式 `tool_call` 事件现有逻辑本就写入 timeline（`ChatHomepage.tsx:1055`），派生值自动跟上——**零新增状态通道**
- 过滤：只在 `ActivityGroup` 渲染层隐藏 todo_write；**落库 timeline 保持完整**（详情视图 / 压缩服务 / 执行日志等下游消费者不受影响）

**否决的备选**：

- 方案二（转换层过滤 + 面板独立 state）：改动点 3 处、双状态通道易漂移、会话内存丢 todo 数据
- 方案三（后端 session.latest_todos 冗余字段）：后端改动 + 写放大；唯一消费端是前端而 timeline 已有全数据，YAGNI

## 4. 详细设计

### 4.1 数据流

```
流式中:  SSE tool_call(todo_write, args 完整) → 现有逻辑写入 timeline
         → useMemo 派生 → 胶囊自动更新（无新增代码路径）
打开/刷新: getDetail(全量) → liveMessages → 同一 useMemo → 随会话恢复
done 后:  getDetail 重载 → 派生值接管 → 与刷新后展示天然一致
```

派生函数（新增，`message-utils.ts`）：

```ts
/** 倒序找最后一条 todo_write 的清单快照；无记录或已清空(todos=[]) → null。 */
export function extractLatestTodos(messages: Message[]): TodoItem[] | null
```

- 复用现有 `parseTodoItems`（非法项过滤已内建）
- `todos=[]` 是合法清空调用（任务闭环语义）→ 返回 `null` → 面板隐藏

### 4.2 会话流内移除（一处过滤）

`ActivityGroup.tsx` 的 `meaningful` 过滤器（`ActivityGroup.tsx:175`）追加：

```ts
if (e.type === 'tool' && e.toolName === 'todo_write') return false;
```

组头计数（`realTools`）、明细行数自动一致，与 `isInteractiveTool` 同模式。
渲染路径已核实唯一：`MessageItem:98 → ActivityGroup → ToolEntryCard(118/287)`，入口过滤即全覆盖。

同步删除：
- `ToolEntryCard.tsx` 的 todo_write 分支（155-160 行）与 `TodoListCard` 组件、`TODO_GLYPHS`；`parseTodoItems` 迁往 `message-utils.ts`（`extractLatestTodos` 的依赖，`ToolEntryCard` 删除后此处已无消费者）
- **不给 `toolSummary` 加 todo_write 分支**——会话流已无此条目，加了是死代码

### 4.3 TodoPanel 组件（新文件 `components/chat/TodoPanel.tsx`）

**挂载**：`SessionHeader` 新增 `todos?: TodoItem[] | null` prop，在顶栏右侧功能区开关按钮左边直接渲染 `<TodoPanel todos={todos} />`（内部 import，无需 children 透传）。无清单 → 不渲染，顶栏零变化。

**折叠态胶囊**：
- `ClipboardList` 图标 + `n/m` 进度，`bg-panel + border-line + shadow-card`，圆角胶囊，高度随 h-12 顶栏
- 有 `in_progress` 项 → 数字 `text-brand` 强调；hover `bg-raise` 微亮

**展开态清单卡**：
- `absolute` 于胶囊下方右对齐（复用 AgentPicker 下拉定位模式），`.af-card` + `shadow-pop`，宽 ~280px
- 每行 = lucide 语义图标 + 内容：进行中 `CircleDot text-brand` / 完成 `CircleCheck text-ink-faint` + 删除线 / 待办 `Circle text-ink-soft`
- 内容单行截断（`truncate`），卡片骨架不滚（卡片高度治理约定）

**交互矩阵**：

| 场景 | 行为 |
|---|---|
| 点击胶囊 | 展开/收起；手动操作即取消未触发的自动收起定时器（手动优先） |
| 清单首次出现 | 自动展开一次，2.5s 后自动收起（期间手动操作按上行规则接管） |
| 流式更新后续版本 | 不强制展开，胶囊进度即时变化 |
| 全部完成 | 胶囊 ✓ 态（`sig-ok`），可展开回看 |
| 清空调用（todos=[]） | 面板整体消失（任务闭环） |
| 切换会话 | 派生重算，随新会话清单 |

**样式约束**：全语义类名（`bg-panel/border-line/text-ink/text-brand/sig-ok`…），`theme-indigo` 机制自动适配明暗——**不需要 theme prop**。动效仅 fade-in（白名单内），`prefers-reduced-motion` 由全局规则兜底。

### 4.4 ChatHomepage 接线

```tsx
const currentTodos = useMemo(() => extractLatestTodos(liveMessages), [liveMessages]);
// 传入 SessionHeader → TodoPanel
```

## 5. 错误处理与边界

- 纯前端派生、无网络请求，错误面极小；`parseTodoItems` 已防御脏数据
- 子代理内的 todo_write 若出现在主 timeline，同样走过滤 + 派生（行为一致，无需特判）
- 中断恢复（resume）路径的 timeline 与落库同源，派生行为一致

## 6. 验证方式

1. `npm run build` 通过
2. 手动实测：a) 新任务首次建清单自动展开→自动收起；b) 中途更新进度跳数、流内无 todo 条目；c) 清空调用后面板消失；d) 历史会话打开恢复最后清单；e) 清空过的会话打开无面板
3. 组头计数自洽：含 todo_write 的执行过程组收起后计数与展开行数一致
