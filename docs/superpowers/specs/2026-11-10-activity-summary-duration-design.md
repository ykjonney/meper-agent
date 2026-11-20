# 执行过程收起 + 用时统计设计

- 日期：2026-11-10
- 状态：已批准（用户逐项确认）
- 范围：frontend-studio（零后端改动）

## 1. 背景与需求

用户需求：**任务结束时收起整个执行过程，最终文本输出保留，收起行只显示「已完成 · 用时X」**。

用户心智模型：一条 agent 回复 = 过程（全部收起）+ 最终文本输出。中间的模型过渡说明（如「视觉方案已确定，我开始动手实现」）是正文文本、保持平铺，不收起。

现状三个问题（`ActivityGroup.tsx`）：

1. 组头无用时：`durationLabel`（工具时间跨度）显示条件苛刻——任一工具缺 `endedAt` 即消失，且时间戳仅流式路径记录，**历史会话永远为空**
2. 口径窄：只算工具时间，不含思考/LLM 时间
3. 收起不全：流结束（done）时最后一组保持展开——当初为防「塌缩+动效消失+操作区出现」叠加闪屏而刻意不收

数据基础：后端落库 `token_usage` 已有 `llm_duration` / `tool_duration`（秒，累计执行时间，历史会话可用）；前端 `TokenUsage` 类型缺这两个字段（需补）。

## 2. 需求决策记录

| 决策点 | 结论 |
|---|---|
| 用时口径 | `llm_duration + tool_duration`（后端 usage，历史可用，零后端改动；不含轮间间隙） |
| 收起态文案 | 「已完成 · 用时 X」（不再显示工具数量） |
| 收起时机 | 流结束（done）→ 全部过程组收起，包括最后一段（反转当初防闪屏决策，由 300ms grid-rows 过渡兜底平滑） |
| 用时显示位置 | 仅最后一段显示消息级总用时；中间段只显示「已完成」 |

## 3. 设计

### 3.1 收起逻辑（ActivityGroup.tsx）

开合 useEffect 的驱动信号从 `segEnded` 换成 `finished`（213 行已有：`hasOwnText || !msgStreaming`）：

- 流式中 `finished=false` → 展开
- 流结束 `finished=true` 且无工具在跑 → 收起（`hasError / interrupted / hasOpenInteractive` 豁免保持不变）
- 历史加载 `finished=true` → 初始即收起（`useState(!finished || hasOpenInteractive)` 不变，与现状一致）

`prevSegEnded` ref 相应改名 `prevFinished`。

### 3.2 组头文案（ActivityGroup.tsx）

finished 态文案统一为 **「已完成」**（删除 `执行了 N 个工具` / `思考完成` 分支）；running 态（正在执行工具/思考中）与出错态不变。

旧 `durationLabel` 计算（工具跨度，199-206 行）整体删除，其渲染位（355-357 行）改为新用时：`finished && execDurationLabel` 时渲染 ` · 用时 {execDurationLabel}`。

### 3.3 单组合并形态（MessageItem.tsx，实施期修正 ⭐）

初版 spec 假设「中间小结平铺、按段收起」，实施实测暴露缺口：纯思考段走 `plain` 分支无组壳（页面上 9 个思考卡散落 + 仅 1 行已完成），不满足用户「**除最终文本输出外都是过程**」的模型。经用户确认修正为：

**最终回答（最后一个 text entry）之前的全部条目（thinking / 工具 / 中间小结 text）合并为单个 ActivityGroup：**

- 流式中组自动展开（进度与中间小结实时可见——ActivityGroup 的卡内 text 渲染分支现成支持）
- 最终回答 text 出现（`lastTextIdx >= 0`）或流结束 → `finished` → 收起为「已完成 · 用时 X」一行
- 同一种 DOM 形态只变 open 状态——原「流结束形态重建闪屏」从根上消失（仅 300ms grid-rows 过渡）
- 用时 = 消息级总用时，合并组即唯一组，天然就是「最后一段」
- 原 MessageItem 的分段 flush 逻辑整体删除

### 3.4 用时数据流（MessageItem.tsx + types.ts）

```
msg.usage.llm_duration + tool_duration（秒）→ 合计 ×1000 → formatToolDuration（tool-details.tsx 现有，复用）
→ MessageItem 向合并过程组传 execDurationLabel
→ 组头渲染「已完成 · 用时 2.3s」/「用时 2m 38s」
```

- `types.ts` 的 `TokenUsage` 补 `llm_duration?: number; tool_duration?: number`
- usage 缺失或两项合计为 0（老消息）→ `execDurationLabel` 不传 → 组头只显示「已完成」

### 3.5 最终形态示例

```
[✓ 已完成 · 用时 2m 38s]   ← 唯一过程组收起行（thinking/工具/中间小结全在组内）
最终回答正文……              ← 平铺
```

边界：无工具的纯思考消息组内 realTools ≤ 1 走 `plain` 平铺（无组头行），现状保留；出错/中断组豁免不收起。

## 4. 错误处理与边界

- 纯展示派生、无网络请求；usage 字段缺失全防御（`?? 0`，合计 0 不渲染用时）
- 中断（interrupted）与出错（hasError）组：豁免不收起（现状保留），出错组头仍显示「执行出错」
- 工具仍在跑但流已结束（异常挂起）：`isRunning` 豁免，保持展开

## 5. 验证方式

1. `npx tsc --noEmit` + `npm run build` 退出码 0
2. Playwright 打开多段历史会话（博客会话）：全部过程组收起为「已完成」、最后一段带用时、中间小结与最终回答平铺不动
3. 真实会话（用户下次使用）：流结束瞬间全部过程组平滑收起（300ms 过渡无闪屏）
