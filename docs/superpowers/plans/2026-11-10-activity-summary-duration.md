# 执行过程收起 + 用时统计 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 流结束（done）时全部执行过程组收起为「已完成 · 用时 X」一行（用时仅最后一段显示），最终文本输出保留平铺。

**Architecture:** ActivityGroup 开合驱动信号 `segEnded` → `finished`（流结束即收起）；组头 finished 文案统一「已完成」；MessageItem 从 `msg.usage` 的 `llm_duration + tool_duration` 算执行用时，仅传给最后一段。零后端改动，3 文件。

**Tech Stack:** React 19 + TypeScript + Tailwind 4 语义 token。

**Spec:** `docs/superpowers/specs/2026-11-10-activity-summary-duration-design.md`

## Global Constraints

- 前端目录：`frontend-studio/`，路径相对仓库根；验证 `cd frontend-studio && npx tsc --noEmit` 与 `npm run build` 均退出码 0
- 无测试框架：验证 = tsc + build + Playwright 手测（不引入测试基建）
- 豁免逻辑保持不变：`hasError / interrupted / hasOpenInteractive / isRunning` 时组不收起
- 注释中文、语义 token（`text-ink-faint`/`font-mono`），不用裸 hex

---

### Task 1: 收起判据切换 + 组头「已完成 · 用时 X」

**Files:**
- Modify: `frontend-studio/src/types.ts:124-130`（TokenUsage 补字段）
- Modify: `frontend-studio/src/components/chat/ActivityGroup.tsx`（props / durationLabel 删除 / 收起判据 / 组头文案）
- Modify: `frontend-studio/src/components/chat/MessageItem.tsx`（用时计算 + 最后一段传参）

**Interfaces:**
- Consumes: `formatToolDuration(ms: number): string`（`tool-details.tsx:93` 已导出，输入 ms 输出 `"123 ms"/"2.3s"/"2m 38s"`）；`msg.usage`（`Message['usage']`，TokenUsage）
- Produces: `ActivityGroup` 新 prop `execDurationLabel?: string`（最后一段传入的用时文本；undefined = 不显示用时）

- [ ] **Step 1: types.ts 补 TokenUsage 字段**

`frontend-studio/src/types.ts:124-130` 改为：

```ts
/** Token usage for an agent message (mirrors backend token_usage / SSE done usage). */
export interface TokenUsage {
  total_tokens?: number;
  input_tokens?: number;
  output_tokens?: number;
  llm_calls?: number;
  tool_calls?: number;
  /** 累计执行时长（秒）：LLM 与工具阶段（后端 usage 落库字段，历史消息可用） */
  llm_duration?: number;
  tool_duration?: number;
}
```

- [ ] **Step 2: ActivityGroup props 增加 execDurationLabel**

`ActivityGroup.tsx` 组件参数解构（140-152 行）末尾 `planVersion,` 后加 `execDurationLabel,`；类型（169 行 `planVersion?: number;` 后）加：

```ts
  /** 消息级执行用时文本（llm+tool 累计）——仅最后一段传入，finished 态组头显示 */
  execDurationLabel?: string;
```

- [ ] **Step 3: 删除旧 durationLabel 计算**

`ActivityGroup.tsx` 删除整段（内容锚点定位，约 201-206 行）：

```ts
  // 组耗时：前端流式记录的工具时间跨度（历史数据无时间戳 → 不显示）
  const durationLabel = (() => {
    const timed = toolEntries.filter((e) => e.startedAt != null);
    if (!timed.length) return '';
    const ends = timed.filter((e) => e.endedAt != null);
    if (ends.length < timed.length) return ''; // 仍有工具在跑或数据不全
    const ms = Math.max(...timed.map((e) => e.endedAt!)) - Math.min(...timed.map((e) => e.startedAt!));
    return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)}s`;
  })();
```

- [ ] **Step 4: 收起判据 segEnded → finished**

`ActivityGroup.tsx` 将（约 212-217 行）：

```ts
  // 收起时机：仅段边界（本段过程后出现 text）。流结束不再触发收起——
  // 结束瞬间「最后一段组塌缩几百 px + 生成中动效消失 + 操作区出现」
  // 多事件叠加 = 页面闪一下；最后一组保持展开（手动可收，历史加载本就是收起态）。
  // finished（含流结束）仅作组头完成态展示判据；segEnded 才驱动开合。
  const finished = !!hasOwnText || !msgStreaming;
  const segEnded = !!hasOwnText;
  const [open, setOpen] = useState(!finished || hasOpenInteractive);
  const prevSegEnded = useRef(segEnded);
```

改为：

```ts
  // 收起时机：finished = 正文已开始 或 流已结束（done）→ 全部过程组收起。
  // 流结束收起覆盖最后一组（用户预期「任务结束只剩已完成摘要行」），
  // 明细区 grid-rows 300ms 过渡兜底平滑，无硬切闪屏。
  const finished = !!hasOwnText || !msgStreaming;
  const [open, setOpen] = useState(!finished || hasOpenInteractive);
  const prevFinished = useRef(finished);
```

并将开合 useEffect（约 234-244 行）：

```ts
  useEffect(() => {
    // 状态跃迁驱动展开/收起（用户手动操作后仅在跃迁时跟随一次）：
    // - 段未结束（正文未开始）或有工具在跑 → 展开（过程=实时进度）
    // - 正文已开始且无工具在跑 → 收起为摘要行（出错/待答交互卡不藏）
    if (prevSegEnded.current !== segEnded || prevRunning.current !== isRunning) {
      prevSegEnded.current = segEnded;
      prevRunning.current = isRunning;
      if (!segEnded || isRunning) setOpen(true);
      else if (!hasError && !interrupted && !hasOpenInteractive) setOpen(false);
    }
  }, [segEnded, isRunning, hasError, interrupted, hasOpenInteractive]);
```

改为：

```ts
  useEffect(() => {
    // 状态跃迁驱动展开/收起（用户手动操作后仅在跃迁时跟随一次）：
    // - 未 finished（正文未开始且流未结束）或有工具在跑 → 展开（过程=实时进度）
    // - finished（正文已开始或流已结束）且无工具在跑 → 收起为「已完成」摘要行
    //   （出错/中断/待答交互卡不藏）
    if (prevFinished.current !== finished || prevRunning.current !== isRunning) {
      prevFinished.current = finished;
      prevRunning.current = isRunning;
      if (!finished || isRunning) setOpen(true);
      else if (!hasError && !interrupted && !hasOpenInteractive) setOpen(false);
    }
  }, [finished, isRunning, hasError, interrupted, hasOpenInteractive]);
```

- [ ] **Step 5: 组头文案统一「已完成」+ 用时渲染**

`ActivityGroup.tsx` 组头（约 344-357 行）：

```tsx
        <span className={`text-xs font-medium shrink-0 leading-none ${hasError || finished ? 'text-ink-dim' : 'text-sig-wait'}`}>
          {hasError
            ? '执行出错'
            : !finished
              ? toolCount > 0
                ? '正在执行工具'
                : '思考中'
              : toolCount > 0
                ? `执行了 ${toolCount} 个工具`
                : '思考完成'}
        </span>
        <span className="text-[11px] text-ink-faint font-mono shrink-0">
          {durationLabel ? ` · ${durationLabel}` : ''}
        </span>
```

改为：

```tsx
        <span className={`text-xs font-medium shrink-0 leading-none ${hasError || finished ? 'text-ink-dim' : 'text-sig-wait'}`}>
          {hasError
            ? '执行出错'
            : !finished
              ? toolCount > 0
                ? '正在执行工具'
                : '思考中'
              : '已完成'}
        </span>
        {finished && execDurationLabel && (
          <span className="text-[11px] text-ink-faint font-mono shrink-0">
            · 用时 {execDurationLabel}
          </span>
        )}
```

- [ ] **Step 6: MessageItem 计算用时并传最后一段**

`frontend-studio/src/components/chat/MessageItem.tsx`：

1. import 区（第 9 行 `ChatAttachmentCard` 之后）加：

```ts
import { formatToolDuration } from './tool-details';
```

2. `hasTimeline` 分支内（约 87 行 `const tl = msg.timeline!;` 之前）加：

```ts
          // 消息级执行用时（LLM+工具累计，秒→ms）：仅最后一段组头显示。
          // 老消息 usage 无 duration 字段 → 0 → 不显示用时。
          const execMs =
            ((msg.usage?.llm_duration ?? 0) + (msg.usage?.tool_duration ?? 0)) * 1000;
          const execDurationLabel = execMs > 0 ? formatToolDuration(execMs) : '';
```

3. flush 函数（约 93 行）加 isLast 参数并透传：

```tsx
          const flush = (hasTextAfter: boolean, isLast = false) => {
            if (!cur.length) return;
            const seg = cur;
            cur = [];
            pieces.push(
              <ActivityGroup
                key={`seg-${segIdx++}`}
                entries={seg}
                msgId={msg.id}
                pinnedRef={pinnedRef}
                interrupted={!!msg.isInterrupted}
                theme={theme}
                thinkingActive={msg.status === 'thinking'}
                /* 段后出现 text → 该段过程确定结束 → 收起为摘要行 */
                hasOwnText={hasTextAfter}
                msgStreaming={inFlight}
                execDurationLabel={isLast ? execDurationLabel : undefined}
                onAnswer={onAnswer}
                onDismiss={() => onDismissInterrupt(msg.id)}
                onApprovePlan={(plan) => onApprovePlan(msg.id, plan)}
                planVersion={undefined}
              />,
            );
          };
```

4. forEach 之后的收尾调用（约 143 行）`flush(false);` 改为 `flush(false, true);`

- [ ] **Step 7: 类型检查 + 构建**

Run: `cd frontend-studio && npx tsc --noEmit && npm run build`
Expected: 均退出码 0

- [ ] **Step 8: Playwright 手测（多段历史会话）**

打开 http://localhost:3000 进入「科技感个人博客」会话（多段过程 + 中间小结），验证：
- 全部过程组收起为一行
- finished 组头显示「已完成」（无「执行了 N 个工具」字样）
- 最后一段组头带「· 用时 X」（该消息 usage llm_duration≈158s+tool_duration≈120s → 预期「用时 4m 38s」左右），中间段无用时
- 中间小结文本与最终回答仍平铺
- 点击收起行可展开明细、再点收起（手动交互不变）

- [ ] **Step 9: Commit**

```bash
git add frontend-studio/src/types.ts frontend-studio/src/components/chat/ActivityGroup.tsx frontend-studio/src/components/chat/MessageItem.tsx
git commit -m "feat(chat): 流结束收起全部过程组,组头「已完成 · 用时X」(usage 执行用时,仅最后一段)"
```

---

## Self-Review 记录

1. **Spec 覆盖**：§3.1 收起逻辑 → Step 4；§3.2 组头文案+删旧 durationLabel → Step 3/5；§3.3 数据流 → Step 1/2/6；§4 边界（豁免/缺字段防御）→ Step 4 分支保留 + Step 6 `?? 0`；§5 验证 → Step 7/8。无缺口。
2. **占位符**：无 TBD；全部步骤含完整代码。
3. **类型一致性**：`execDurationLabel?: string`（Step 2 定义）↔ Step 5 消费 ↔ Step 6 传参一致；`formatToolDuration` 既有导出签名吻合；`TokenUsage.llm_duration/tool_duration`（Step 1）↔ `msg.usage?.llm_duration`（Step 6）一致。
