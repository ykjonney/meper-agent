---
status: final
updated: 2026-06-09
brand: Agent Flow
style: professional-engineering-restrained, modern-saas
---

# Agent Flow — DESIGN.md

> Visual identity for Agent Flow, the AI Agent orchestration platform.
> Inherits from **Ant Design 6.x** with brand-level customizations on color, shape, and typography.
> Design reference: **Linear** (surface ladder, single accent, restraint), **Notion** (content-first), **Height** (modern task management).
> Spine: `Brand & Style` · `Colors` · `Typography` · `Layout & Spacing` · `Elevation & Depth` · `Shapes` · `Components` · `Do's and Don'ts`.
> Spines win on conflict with any mock, wireframe, or import.

## Brand & Style

**Personality:** Professional · Engineering · Restrained · AI-augmented · Modern SaaS
**Inspiration:** Linear (surface hierarchy, restrained palette), Notion (neutral content canvas), LangChain LangSmith (engineering depth), Height (task workflow clarity)
**Anti-patterns:** Dify's playful cartoon style (too casual for industrial B 端), Vercel's black-noir (too dramatic for day-long usage), traditional AntD dashboard (老式 B 端感)

**Design principles:**

1. **Function before form** — every visual element must serve a function; no decorative noise
2. **Information density respects attention** — operators scan, devs dive deep; UI must support both
3. **State is always visible** — loading, success, error, empty, disabled — never ambiguous
4. **Defaults reduce decisions** — 80% of users should never need to customize
5. **Engineering over ornament** — code, IDs, logs are first-class content, not afterthoughts
6. **Surface over shadow** — hierarchy expressed via lightness steps and hairline borders, not drop shadows (Linear-inspired)
7. **Restrained accent** — single chromatic accent color (Indigo), no decorative gradients or secondary accent

**Tagline (internal):** _"Build agents that build themselves."_

## Colors

Semantic color tokens, derived from Ant Design 6.x preset + brand override.
**Architecture:** Surface ladder (Lightness steps) + single accent (Indigo). No decorative gradients.

### Primary palette (Indigo accent — single chromatic color)

| Token | Value | Usage |
|-------|-------|-------|
| `color.primary` | `#4F46E5` | 主操作按钮、激活状态、关键链接 |
| `color.primary.hover` | `#6366F1` | 主按钮 hover |
| `color.primary.active` | `#4338CA` | 主按钮 active |
| `color.primary.bg` | `#EEF2FF` | 选中背景、Tag 背景 |
| `color.accent` | `#06B6D4` | AI 标识、生成中状态、模型图标（Cyan 辅色） |
| `color.accent.bg` | `#ECFEFF` | AI 相关提示背景 |

### Neutral palette (Slate-based surface ladder)

Based on Tailwind Slate, optimized for UI hierarchy:

| Token | Value | Usage |
|-------|-------|-------|
| `color.bg.layout` | `#F8FAFC` | **页面画布**（slate-50）— 最底层 |
| `color.bg.container` | `#FFFFFF` | **卡片/面板/弹窗** — 表面层 |
| `color.bg.elevated` | `#F1F5F9` | **hover/选中背景**（slate-100） |
| `color.bg.hover` | `#F8FAFC` | **行/按钮 hover**（slate-50） |
| `color.text.primary` | `#0F172A` | 主要文字（slate-900） |
| `color.text.secondary` | `#475569` | 次要文字、说明（slate-600） |
| `color.text.tertiary` | `#94A3B8` | 辅助文字、placeholder（slate-400） |
| `color.text.disabled` | `#CBD5E1` | 禁用文字（slate-300） |
| `color.border` | `#E2E8F0` | 默认边框、分割线（slate-200）— 发丝线 |
| `color.border.strong` | `#CBD5E1` | 强调边框、输入框 focus 前 |
| `color.border.hairline` | `#F1F5F9` | 卡片内发丝分割线 |

### Sidebar palette (Dark sidebar)

| Token | Value | Usage |
|-------|-------|-------|
| `color.sidebar.bg` | `#0F172A` | 侧边栏背景（slate-900） |
| `color.sidebar.hover` | `#1E293B` | 侧边栏项 hover（slate-800） |
| `color.sidebar.active` | `#4F46E5` | 侧边栏激活指示条 |
| `color.sidebar.text` | `#CBD5E1` | 侧边栏文字（slate-300） |
| `color.sidebar.text.active` | `#FFFFFF` | 侧边栏激活项文字 |
| `color.sidebar.icon` | `#64748B` | 侧边栏图标（slate-500） |
| `color.sidebar.icon.active` | `#FFFFFF` | 侧边栏激活图标 |

### Semantic palette (state colors)

| Token | Value | Usage |
|-------|-------|-------|
| `color.success` | `#10B981` | 成功状态、Agent 已发布（Emerald） |
| `color.success.bg` | `#D1FAE5` | 成功提示背景 |
| `color.warning` | `#F59E0B` | 警告、嵌套深度 ≥ 2（Amber） |
| `color.warning.bg` | `#FEF3C7` | 警告背景 |
| `color.error` | `#EF4444` | 错误、失败、删除（Red） |
| `color.error.bg` | `#FEE2E2` | 错误背景 |
| `color.info` | `#4F46E5` | 信息提示（= primary 简化） |
| `color.info.bg` | `#EEF2FF` | 信息背景 |

### Role color (RBAC)

| Token | Value | Usage |
|-------|-------|-------|
| `color.role.admin` | `#EF4444` | 管理员角色标识 |
| `color.role.developer` | `#4F46E5` | 开发者角色 |
| `color.role.operator` | `#10B981` | 操作员角色 |
| `color.role.viewer` | `#94A3B8` | 只读角色 |

### Dark mode (deferred)

`[ASSUMPTION]` All tokens above have dark-mode counterparts reserved but not implemented in MVP. Token names will switch to CSS variable lookup so a future dark theme can override without code changes.

## Typography

Inheriting Ant Design 6.x typography with brand-level adjustments.
Modern SaaS approach: **clean system-native stack** with **Inter** for English UI text (via Google Fonts), **PingFang SC** for Chinese.

| Token | Value | Usage |
|-------|-------|-------|
| `font.family.primary` | `"Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif` | 全局 UI 字体（Inter 优先，中文 fallback 系统字体） |
| `font.family.mono` | `"JetBrains Mono", "SF Mono", "Menlo", "Consolas", monospace` | 代码、ID、日志、API key（JetBrains Mono 优先） |
| `font.size.h1` | 24px / 600 / -0.5px | 页面主标题（负 tracking 增强紧凑感） |
| `font.size.h2` | 20px / 600 / -0.3px | 区块标题 |
| `font.size.h3` | 16px / 600 / 0 | 卡片/弹窗标题 |
| `font.size.body` | 14px / 400 / 0 | 正文（AntD 默认） |
| `font.size.small` | 12px / 400 / 0 | 辅助说明 |
| `font.size.code` | 13px / 400 / 0 | 代码块（mono） |
| `font.weight.regular` | 400 | 正文 |
| `font.weight.medium` | 500 | 强调、按钮、Tab |
| `font.weight.semibold` | 600 | 标题 |
| `font.lineheight.tight` | 1.4 | 标题 |
| `font.lineheight.normal` | 1.57 | 正文（AntD 默认） |
| `font.lineheight.relaxed` | 1.7 | 长文本、说明 |

**Font choice rationale:**
- Inter：现代 SaaS 标配（Linear、GitHub、Vercel 都用），西文渲染锐利
- PingFang SC + Microsoft YaHei：覆盖中文字符，工业 PC 主流
- JetBrains Mono：现代工程感，比 SF Mono 更清晰，开源免费
- 标题负 tracking：借鉴 Linear，增强标题的紧凑力度

### CSS 引用

```css
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500&display=swap');
```

## Layout & Spacing

### Spacing scale (8px base, AntD-aligned)

| Token | Value | Usage |
|-------|-------|-------|
| `space.xxs` | 4px | Tag 内部、紧凑行内 |
| `space.xs` | 8px | 列表项内元素间距 |
| `space.sm` | 12px | 卡片内 padding（小） |
| `space.md` | 16px | 卡片内 padding（中）、区块间距 |
| `space.lg` | 24px | 页面区块间距、Modal padding |
| `space.xl` | 32px | 主要分区、页面顶部留白 |
| `space.xxl` | 48px | 页面底部、英雄区 |

### Layout grid

- **App shell**：顶部 56px header + 左侧 **240px 深色 sidebar**（可折叠到 64px icon-only）+ 主内容区
- **主内容区**：padding 24px 左右，内容区最大 1440px 居中
- **工作流编辑器**：全屏模式，sidebar 自动折叠为 icon-only，顶部 48px 工具栏
- **对话界面**：左 30% 会话列表 + 右 70% 对话区
- **列表页**：搜索/筛选栏 + DataTable 标准布局
- **栅格**：AntD 24 列 gutter 16px

### Breakpoints

| Token | Width | Usage |
|-------|-------|-------|
| `breakpoint.sm` | 576px | 极简（仅对话） |
| `breakpoint.md` | 768px | 平板，简化导航 |
| `breakpoint.lg` | 992px | **主力断点**（工位屏） |
| `breakpoint.xl` | 1200px | 工作流编辑器舒适区 |
| `breakpoint.xxl` | 1600px | 大屏，3 列布局 |

## Elevation & Depth

**原则：** Surface ladder 为主，阴影为辅。层级通过背景色逐层变亮来区分（Linear 风格），阴影仅用于浮层（Modal/Drawer/Popover）。

### Surface ladder

| Level | Token | Light value | Usage |
|-------|-------|-------------|-------|
| 0 — Canvas | `color.bg.layout` | `#F8FAFC` | 页面画布 |
| 1 — Container | `color.bg.container` | `#FFFFFF` | 卡片、面板 |
| 2 — Elevated | `color.bg.elevated` | `#F1F5F9` | Dropdown、hover 选中态 |
| 3 — Overlay | `color.bg.overlay` | `#FFFFFF` | Modal、Drawer |

层级靠"从背景中浮起"来体现，而不是靠边框或阴影。

### Shadows (仅用于浮层)

| Token | Value | Usage |
|-------|-------|-------|
| `shadow.none` | `none` | Surface 层内元素 |
| `shadow.sm` | `0 1px 2px 0 rgba(0, 0, 0, 0.04)` | 输入框、Tag |
| `shadow.md` | `0 2px 8px 0 rgba(0, 0, 0, 0.06)` | Popover、Select 下拉、Tooltip |
| `shadow.lg` | `0 6px 16px 0 rgba(0, 0, 0, 0.10)` | Modal、Drawer |
| `shadow.xl` | `0 12px 32px 0 rgba(0, 0, 0, 0.12)` | 关键操作确认弹窗 |

**AntD shadow token mapping:**
- 卡片：`shadow.none`（纯白 + 发丝边框 `#E2E8F0` = 无阴影卡片）
- 弹窗：`shadow.lg`
- Drawer：`shadow.xl`（侧边滑出）
- Tooltip/Popover：`shadow.md`

## Shapes

**圆角克制**（工程感 vs 友好的关键差异）：
交互元素稍大（6px），容器元素克制（4px）。

| Token | Value | Usage |
|-------|-------|-------|
| `radius.none` | 0 | 工作流节点内部、状态点、Tag 装饰 |
| `radius.sm` | 4px | Card、Modal、输入框、按钮（统一基础圆角） |
| `radius.md` | 6px | 主按钮、Primary 操作元素 |
| `radius.lg` | 8px | Drawer、大卡片 |
| `radius.xl` | 12px | 弹窗、强调容器 |
| `radius.round` | 50% | 头像、状态点、Loading spinner |

**对比参考：**
- 传统 AntD 风格：圆角 2px，偏锐利
- 现代 SaaS 风格（本设计）：圆角 4-6px 为主，柔和但不圆滑
- 活泼风格（不用）：圆角 8-16px，偏卡通

## Components

> Visual specs only. Behavior (click handlers, keyboard nav, states) lives in EXPERIENCE.md.

### Buttons

| 变体 | 视觉 | 用途 |
|------|------|------|
| **Primary** | 实心 `#4F46E5` 白字，hover `#6366F1` | 主操作（保存、发布、调用） |
| **Default** | 白底 `#E2E8F0` 边框，hover `#F1F5F9` 灰底 | 次操作（取消、返回） |
| **Danger** | 白底 `#EF4444` 边框，hover `#FEE2E2` 红底 | 删除、终止执行 |
| **Text** | 无边框透明，hover `#F1F5F9` 灰底 | 表格行操作、辅助链接 |
| **Disabled** | 灰底 `#F1F5F9` + 灰字 `#CBD5E1` + cursor-not-allowed | 不可用状态 |
| **Loading** | 按钮 disabled + AntD Spin 替代图标，文字变为"处理中..." | 异步操作期间 |

**尺寸：** large 40px / middle 32px / small 24px

### Inputs

- 默认边框 1px `#E5E6EB`，hover `#C9CDD4`，focus `#1E5EFF`（2px 蓝色光环）
- 错误：边框 `#F53F3F` + 下方红字说明
- 占位符：tertiary 灰色
- 前缀/后缀 icon：tertiary 灰色，hover/active 变 primary

### Cards

- 背景：白色 `color.bg.container`
- 边框：1px `#E2E8F0` 发丝线（不是粗边框）
- 圆角：`radius.sm`（4px）
- 标题：16px semibold，下方 16px 内容区
- 间距：padding 20px（比 AntD 默认 16px 更大，更有呼吸感）
- Hover（可点击卡片）：背景 `#F8FAFC` + 边框 `#CBD5E1`（不靠阴影）
- **无阴影卡片**（Surface ladder 设计）：层级靠底色区分，不靠阴影
- **Loading 卡片**：Skeleton 占位，形状与真实卡片一致

### Tables

- **表头**：灰底 `#F8FAFC`，medium 字重 14px，文字 `#475569`
- **行高**：44px（中密度，比 AntD 默认稍高增加呼吸感）
- **边框**：底部 1px `#F1F5F9` 发丝线，不画竖线（极简风格）
- **Hover**：行背景 `#F8FAFC`
- **选中**：左侧 3px `#4F46E5` 指示条 + 背景 `#EEF2FF`
- **行操作**：hover 时浮现操作按钮（View / Edit / Delete），默认隐藏保持干净
- **空状态**：AntD Empty 组件 + 一句说明 + 可选 CTA
- **加载态**：Skeleton 3-5 行占位
- **分页**：简洁模式，仅显示"上一页/下一页/页码"

### Tags / Status Badges

基于新 Indigo 色板，状态 Tag 使用对应的语义色，保持克制：

| 状态 | 颜色 | 文字示例 |
|------|------|----------|
| Draft | 灰 `color.text.tertiary` (`#94A3B8`) | "草稿" |
| Published | Emerald `color.success` (`#10B981`) | "已发布" |
| Running | Indigo `color.primary` (`#4F46E5`) + 脉冲动画 | "执行中..." |
| Success | Emerald `color.success` (`#10B981`) | "成功" |
| Failed | Red `color.error` (`#EF4444`) | "失败" |
| Warning | Amber `color.warning` (`#F59E0B`) | "嵌套深度警告" |
| AI Processing | Cyan `color.accent` (`#06B6D4`) + spinner | "AI 思考中" |

### Modals / Drawers

- Modal：居中，宽 520px（小）/ 720px（中）/ 960px（大），`shadow.lg`
- Drawer：右侧滑出，宽 480px，`shadow.xl`
- 关闭：右上角 X、Esc 键、点击遮罩（仅确认类弹窗不响应遮罩点击）
- 页脚：右对齐 [取消] [确认] 按钮组合

### Loading states

| 场景 | 视觉 |
|------|------|
| 页面级 | 居中 `<Spin size="large" />` + 白色遮罩 |
| 区块级 | 区块内 `<Spin />` + 半透明遮罩 |
| 按钮内 | 按钮 disabled + 内置 spinner |
| 列表局部 | 骨架屏（Skeleton，3-5 行占位） |
| 流式输出 | 青色脉冲点 + "AI 正在思考" 文字 |

### Empty states

- 居中插图（AntD Empty 组件，108x108px 浅灰插画）
- 主标题：14px medium 灰字
- 副标题：12px tertiary 灰字
- 可选 CTA 按钮（"创建第一个 Agent" 等）

### Error states

- 全局错误页：404 / 403 / 500 独立页面
- 内联错误：组件内红色背景条 + 错误码 + 重试按钮
- Toast：右上角 3 秒自动消失

### Icons

- 库：Ant Design Icons (`@ant-design/icons`)
- 尺寸：16px（小）/ 20px（中）/ 24px（大）
- 颜色：默认 `text.secondary`，交互态用 `primary` 或 `text.primary`

## Do's and Don'ts

### ✅ Do

- **保持视觉一致** — 所有主色按钮/链接用 `#4F46E5`，不引入其他蓝色
- **状态永远可见** — Agent 状态、执行状态、加载状态必须有视觉表达
- **可点击 = 视觉提示** — 链接有下划线/颜色，按钮有边框/填充，可点击卡片有 hover
- **代码/ID 用等宽字体** — API key、Agent ID、日志行用 JetBrains Mono
- **错误给可执行建议** — "保存失败：网络断开" 而不是 "Error 500"
- **中英混排间距** — 中英文之间自动加 0.5 空格（CSS `word-spacing`）
- **行操作 hover 浮现** — 表格行操作按钮默认隐藏，hover 行时浮现，保持界面干净
- **骨架屏优先** — 所有列表/详情优先使用 Skeleton 而非 Spinner

### ❌ Don't

- **不引入额外圆角** — 除 shapes 表中定义外不出现新圆角值
- **不用 emoji 装饰** — 工程系统不友好，且多平台渲染不一致。所有图标使用 `@ant-design/icons`
- **不滥用彩色背景** — 灰白为主，彩色仅用于状态/重点
- **不省略占位/禁用态** — 任何 input/button 必须有所有 5 个状态
- **不画蛇添足** — 动效不超过 200ms，不做页面级切换动画
- **不混用字体** — 全局只用一个 sans（Inter + 系统中文字体）一个 mono（JetBrains Mono），不出现第三种
- **卡片不用阴影** — 卡片层级靠 Surface ladder（底色差异）表达，不用 drop shadow
- **不画竖表格线** — 表格只保留底部横线，不画竖线（现代表格风格）

---

## Component Pattern Index

> Cross-references for EXPERIENCE.md to use via `{path.to.token}` syntax.

- **Buttons:** `Components.Buttons.{Primary,Default,Danger,Text,Disabled,Loading}`
- **Inputs:** `Components.Inputs.{Default,Focus,Error,Disabled}`
- **Cards:** `Components.Cards.{Static,Interactive,Loading}`
- **Tables:** `Components.Tables.{Default,Empty,Loading,SelectedRow}`
- **Tags:** `Components.Tags.{Draft,Published,Running,Success,Failed,Warning,AIProcessing}`
- **Modals:** `Components.Modals.{Confirm,Form,Detail}`
- **Drawers:** `Components.Drawers.{Right,Detail}`
- **Loading:** `Components.Loading.{Page,Block,Button,Skeleton,Streaming}`
- **Empty:** `Components.Empty.{Default,Error,NoData,NoPermission}`
- **Error:** `Components.Error.{Inline,Toast,FullPage}`

---

## Token CSS variable mapping (Tailwind config)

```js
// tailwind.config.ts 摘录 — 现代工作流风格（Indigo + Surface ladder）
module.exports = {
  theme: {
    extend: {
      colors: {
        primary: {
          DEFAULT: '#4F46E5',
          hover: '#6366F1',
          active: '#4338CA',
          bg: '#EEF2FF',
        },
        accent: { DEFAULT: '#06B6D4', bg: '#ECFEFF' },
        sidebar: {
          bg: '#0F172A',
          hover: '#1E293B',
          active: '#4F46E5',
          text: '#CBD5E1',
          'text-active': '#FFFFFF',
          icon: '#64748B',
          'icon-active': '#FFFFFF',
        },
        // surface ladder
        surface: {
          layout: '#F8FAFC',
          container: '#FFFFFF',
          elevated: '#F1F5F9',
        },
        // semantic
        success: { DEFAULT: '#10B981', bg: '#D1FAE5' },
        warning: { DEFAULT: '#F59E0B', bg: '#FEF3C7' },
        error: { DEFAULT: '#EF4444', bg: '#FEE2E2' },
      },
      fontFamily: {
        sans: ['Inter', '-apple-system', 'BlinkMacSystemFont', '"PingFang SC"', '"Microsoft YaHei"', 'sans-serif'],
        mono: ['"JetBrains Mono"', '"SF Mono"', '"Menlo"', '"Consolas"', 'monospace'],
      },
      borderRadius: {
        none: '0',
        sm: '4px',
        DEFAULT: '4px',
        md: '6px',
        lg: '8px',
        xl: '12px',
      },
      boxShadow: {
        sm: '0 1px 2px 0 rgba(0, 0, 0, 0.04)',
        DEFAULT: '0 2px 8px 0 rgba(0, 0, 0, 0.06)',
        md: '0 2px 8px 0 rgba(0, 0, 0, 0.06)',
        lg: '0 6px 16px 0 rgba(0, 0, 0, 0.10)',
        xl: '0 12px 32px 0 rgba(0, 0, 0, 0.12)',
      },
    },
  },
};
```

---

## Spine cross-references

- **IA & navigation:** `EXPERIENCE.md.Information Architecture`
- **Behavior (loading/error/empty):** `EXPERIENCE.md.State Patterns`
- **Interaction (modal/drawer/toast):** `EXPERIENCE.md.Interaction Primitives`
- **A11y (contrast/keyboard):** `EXPERIENCE.md.Accessibility Floor`
- **Key flows:** `EXPERIENCE.md.Key Flows`
