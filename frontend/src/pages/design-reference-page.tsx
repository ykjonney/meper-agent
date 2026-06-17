/**
 * Design Reference Page — 改进后的设计规范参考实现。
 *
 * Route: /design-reference (standalone, no AppLayout shell)
 *
 * 展示与 DESIGN.md 对齐的视觉系统：
 * - Inter 字体 + 严格 type scale
 * - Indigo #4F46E5 主色
 * - 4px 基础圆角（容器 8px）
 * - 8px spacing scale
 * - Surface ladder（无阴影卡片）
 * - 重新设计的 Agent 列表和 Dashboard 区域
 */
import { useState } from 'react'
import {
  RobotOutlined,
  BranchesOutlined,
  ThunderboltOutlined,
  CheckCircleOutlined,
  SearchOutlined,
  FilterOutlined,
  PlusOutlined,
  CloudUploadOutlined,
  CopyOutlined,
  DeleteOutlined,
  ArrowLeftOutlined,
  MoreOutlined,
  InboxOutlined,
  ArrowUpOutlined,
  ArrowDownOutlined,
  StopOutlined,
} from '@ant-design/icons'

/* ─── Design tokens (DESIGN.md aligned) ─── */
const T = {
  primary: '#4F46E5',
  primaryHover: '#6366F1',
  primaryBg: '#EEF2FF',
  accent: '#06B6D4',
  accentBg: '#ECFEFF',

  // Surface ladder
  canvas: '#F8FAFC',
  container: '#FFFFFF',
  elevated: '#F1F5F9',

  // Text
  txt: '#0F172A',
  txt2: '#475569',
  txt3: '#64748B',
  muted: '#94A3B8',

  // Borders
  line: '#E2E8F0',
  line2: '#F1F5F9',

  // Semantic
  success: '#10B981',
  successBg: '#D1FAE5',
  warning: '#F59E0B',
  warningBg: '#FEF3C7',
  error: '#EF4444',
  errorBg: '#FEE2E2',
} as const

/* ─── Mock data ─── */
const AGENTS = [
  { id: '1', name: '客服助手 Pro', desc: '基于 GPT-4 的多轮对话客服 Agent，支持工单创建和知识库查询', model: 'GPT-4o', status: 'published', skills: 3, mcp: 2, updated: '2 小时前' },
  { id: '2', name: '代码审查 Agent', desc: '自动化代码审查，支持 Python / TypeScript / Go 三种语言', model: 'Claude 3.5', status: 'published', skills: 1, mcp: 0, updated: '5 小时前' },
  { id: '3', name: '数据分析 Pipeline', desc: '端到端数据分析：数据清洗 → 特征工程 → 模型训练 → 报告生成', model: 'GPT-4o', status: 'draft', skills: 5, mcp: 1, updated: '1 天前' },
  { id: '4', name: '邮件摘要生成器', desc: '每日自动汇总未读邮件，生成结构化摘要并推送到飞书', model: 'Claude 3 Haiku', status: 'published', skills: 0, mcp: 3, updated: '3 天前' },
  { id: '5', name: '竞品监控 Agent', desc: '定时抓取竞品网站变更，生成对比分析报告', model: 'GPT-4o Mini', status: 'archived', skills: 2, mcp: 0, updated: '1 周前' },
  { id: '6', name: '内部知识库问答', desc: '接入 Confluence 和飞书文档，回答内部知识相关问题', model: 'Claude 3.5', status: 'draft', skills: 1, mcp: 1, updated: '2 周前' },
]

const STATS = [
  { label: '全部 Agent', value: '24' },
  { label: '已发布', value: '16' },
  { label: '草稿', value: '5' },
  { label: '已归档', value: '3' },
]

const STATUS_MAP: Record<string, { label: string; color: string; bg: string }> = {
  published: { label: '已发布', color: T.success, bg: T.successBg },
  draft: { label: '草稿', color: T.muted, bg: T.elevated },
  archived: { label: '已归档', color: T.txt3, bg: T.elevated },
}

/* ─── Inline styles (bypass inconsistent Tailwind config) ─── */
const font = "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif"
const mono = "'JetBrains Mono', 'SF Mono', monospace"

export default function DesignReferencePage() {
  const [search, setSearch] = useState('')

  const filtered = AGENTS.filter(a =>
    a.name.toLowerCase().includes(search.toLowerCase()) ||
    a.desc.toLowerCase().includes(search.toLowerCase())
  )

  return (
    <div style={{ fontFamily: font, background: T.canvas, minHeight: '100vh', color: T.txt }}>
      {/* ─── Top bar ─── */}
      <header style={{
        height: 48, background: T.container, borderBottom: `1px solid ${T.line}`,
        display: 'flex', alignItems: 'center', padding: '0 24px', gap: 16,
      }}>
        <a href="/" style={{ display: 'flex', alignItems: 'center', gap: 6, color: T.txt3, fontSize: 13, textDecoration: 'none' }}>
          <ArrowLeftOutlined style={{ fontSize: 12 }} />
          返回应用
        </a>
        <div style={{ width: 1, height: 20, background: T.line }} />
        <span style={{ fontSize: 13, fontWeight: 600, color: T.txt, letterSpacing: '-0.01em' }}>
          设计参考页
        </span>
        <span style={{ fontSize: 12, color: T.muted, fontWeight: 400 }}>
          DESIGN.md 对齐实现
        </span>
      </header>

      <div style={{ maxWidth: 1200, margin: '0 auto', padding: '32px 24px' }}>

        {/* ═══════════════ Section 1: Typography Scale ═══════════════ */}
        <section style={{ marginBottom: 48 }}>
          <SectionTitle>排版层次（Type Scale）</SectionTitle>
          <p style={{ fontSize: 13, color: T.txt2, marginBottom: 20, lineHeight: 1.6 }}>
            每级 ratio ≥ 1.2，标题使用负 letter-spacing 增强紧凑感。全局使用 Inter + 系统中文字体。
          </p>

          <div style={{ background: T.container, border: `1px solid ${T.line}`, borderRadius: 8, padding: 24 }}>
            {/* H1 - Page title */}
            <div style={{ marginBottom: 24, paddingBottom: 24, borderBottom: `1px solid ${T.line2}` }}>
              <div style={{ fontSize: 11, color: T.muted, marginBottom: 4, fontFamily: mono }}>24px / 600 / -0.02em — 页面主标题</div>
              <h1 style={{ fontSize: 24, fontWeight: 600, letterSpacing: '-0.02em', margin: 0, color: T.txt }}>
                Agent 管理
              </h1>
            </div>

            {/* H2 - Section title */}
            <div style={{ marginBottom: 24, paddingBottom: 24, borderBottom: `1px solid ${T.line2}` }}>
              <div style={{ fontSize: 11, color: T.muted, marginBottom: 4, fontFamily: mono }}>18px / 600 / -0.01em — 区块标题</div>
              <h2 style={{ fontSize: 18, fontWeight: 600, letterSpacing: '-0.01em', margin: 0, color: T.txt }}>
                最近执行的工作流
              </h2>
            </div>

            {/* H3 - Card title */}
            <div style={{ marginBottom: 24, paddingBottom: 24, borderBottom: `1px solid ${T.line2}` }}>
              <div style={{ fontSize: 11, color: T.muted, marginBottom: 4, fontFamily: mono }}>15px / 500 / 0 — 卡片标题</div>
              <h3 style={{ fontSize: 15, fontWeight: 500, margin: 0, color: T.txt }}>
                客服助手 Pro
              </h3>
            </div>

            {/* Body */}
            <div style={{ marginBottom: 24, paddingBottom: 24, borderBottom: `1px solid ${T.line2}` }}>
              <div style={{ fontSize: 11, color: T.muted, marginBottom: 4, fontFamily: mono }}>14px / 400 / 1.57 — 正文</div>
              <p style={{ fontSize: 14, margin: 0, color: T.txt, lineHeight: 1.57 }}>
                基于 GPT-4 的多轮对话客服 Agent，支持工单创建和知识库查询。接入 MCP 工具后，Agent 可以直接操作数据库和调用内部 API。
              </p>
            </div>

            {/* Small / secondary */}
            <div style={{ marginBottom: 24, paddingBottom: 24, borderBottom: `1px solid ${T.line2}` }}>
              <div style={{ fontSize: 11, color: T.muted, marginBottom: 4, fontFamily: mono }}>13px / 400 — 次要文字</div>
              <p style={{ fontSize: 13, margin: 0, color: T.txt2, lineHeight: 1.5 }}>
                上次更新于 2 小时前 · 由 Admin 创建
              </p>
            </div>

            {/* Caption / muted */}
            <div style={{ marginBottom: 24, paddingBottom: 24, borderBottom: `1px solid ${T.line2}` }}>
              <div style={{ fontSize: 11, color: T.muted, marginBottom: 4, fontFamily: mono }}>12px / 400 — 辅助说明</div>
              <p style={{ fontSize: 12, margin: 0, color: T.txt3, lineHeight: 1.5 }}>
                共 24 个 Agent · 16 个已发布 · 5 个草稿 · 3 个已归档
              </p>
            </div>

            {/* Code / mono */}
            <div>
              <div style={{ fontSize: 11, color: T.muted, marginBottom: 4, fontFamily: mono }}>13px / JetBrains Mono — 代码 / ID</div>
              <code style={{ fontSize: 13, fontFamily: mono, color: T.txt, background: T.elevated, padding: '2px 6px', borderRadius: 4 }}>
                agent_8f3k2m1n
              </code>
            </div>
          </div>
        </section>

        {/* ═══════════════ Section 2: Spacing & Surface ═══════════════ */}
        <section style={{ marginBottom: 48 }}>
          <SectionTitle>间距与表面（Spacing & Surface Ladder）</SectionTitle>
          <p style={{ fontSize: 13, color: T.txt2, marginBottom: 20, lineHeight: 1.6 }}>
            8px base scale: 4 / 8 / 12 / 16 / 24 / 32 / 48px。卡片无阴影，层级靠底色差异（Surface ladder）。
          </p>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
            {/* Surface ladder demo */}
            <div style={{ background: T.canvas, border: `1px solid ${T.line}`, borderRadius: 8, padding: 20 }}>
              <div style={{ fontSize: 13, fontWeight: 500, marginBottom: 16, color: T.txt }}>Surface Ladder</div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                <SurfaceDemo label="Level 0 — Canvas" color={T.canvas} desc="#F8FAFC 页面画布" bordered />
                <SurfaceDemo label="Level 1 — Container" color={T.container} desc="#FFFFFF 卡片 / 面板" />
                <SurfaceDemo label="Level 2 — Elevated" color={T.elevated} desc="#F1F5F9 hover / 选中态" />
              </div>
            </div>

            {/* Spacing scale demo */}
            <div style={{ background: T.container, border: `1px solid ${T.line}`, borderRadius: 8, padding: 20 }}>
              <div style={{ fontSize: 13, fontWeight: 500, marginBottom: 16, color: T.txt }}>Spacing Scale (8px base)</div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                {[4, 8, 12, 16, 24, 32, 48].map(v => (
                  <div key={v} style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                    <span style={{ fontSize: 12, fontFamily: mono, color: T.txt3, width: 36, textAlign: 'right' }}>{v}px</span>
                    <div style={{ width: v * 2, height: 8, background: T.primary, borderRadius: 2, opacity: 0.15 + (v / 48) * 0.85 }} />
                  </div>
                ))}
              </div>
            </div>
          </div>
        </section>

        {/* ═══════════════ Section 3: Color Palette ═══════════════ */}
        <section style={{ marginBottom: 48 }}>
          <SectionTitle>颜色系统（Color System）</SectionTitle>
          <p style={{ fontSize: 13, color: T.txt2, marginBottom: 20, lineHeight: 1.6 }}>
            单一主色 Indigo + 语义色点缀。不引入额外装饰色。所有颜色通过语义 token 引用，禁止硬编码 hex。
          </p>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12 }}>
            <ColorSwatch name="Primary" value={T.primary} usage="主操作 / 激活态" />
            <ColorSwatch name="Primary BG" value={T.primaryBg} usage="选中背景 / Tag" dark />
            <ColorSwatch name="Accent (AI)" value={T.accent} usage="AI 标识 / 生成中" />
            <ColorSwatch name="Success" value={T.success} usage="已发布 / 成功" />
            <ColorSwatch name="Warning" value={T.warning} usage="警告 / 注意" />
            <ColorSwatch name="Error" value={T.error} usage="错误 / 删除" />
            <ColorSwatch name="Text Primary" value={T.txt} usage="主要文字" />
            <ColorSwatch name="Text Secondary" value={T.txt2} usage="次要文字" />
          </div>
        </section>

        {/* ═══════════════ Section 4: Redesigned Agent List ═══════════════ */}
        <section style={{ marginBottom: 48 }}>
          <SectionTitle>重新设计的 Agent 列表</SectionTitle>
          <p style={{ fontSize: 13, color: T.txt2, marginBottom: 20, lineHeight: 1.6 }}>
            对比原版：统一 4px 圆角（容器 8px）、Inter 字体、Indigo 主色、Surface ladder 无阴影卡片、严格 type scale、24px 页面间距。
          </p>

          {/* Stats row — 紧凑统计，不用大卡片 */}
          <div style={{ display: 'flex', gap: 24, marginBottom: 20 }}>
            {STATS.map((s, i) => (
              <div key={s.label} style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
                <span style={{ fontSize: 18, fontWeight: 600, color: T.txt, letterSpacing: '-0.01em' }}>{s.value}</span>
                <span style={{ fontSize: 13, color: T.txt3 }}>{s.label}</span>
                {i < STATS.length - 1 && (
                  <div style={{ width: 1, height: 16, background: T.line, marginLeft: 18 }} />
                )}
              </div>
            ))}
          </div>

          {/* Action bar */}
          <div style={{
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            marginBottom: 16, gap: 12,
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              {/* Search */}
              <div style={{ position: 'relative' }}>
                <SearchOutlined style={{ position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)', color: T.muted, fontSize: 13 }} />
                <input
                  type="text"
                  value={search}
                  onChange={e => setSearch(e.target.value)}
                  placeholder="搜索 Agent..."
                  style={{
                    paddingLeft: 32, paddingRight: 12, paddingTop: 6, paddingBottom: 6,
                    fontSize: 13, border: `1px solid ${T.line}`, borderRadius: 6,
                    outline: 'none', width: 220, color: T.txt, background: T.container,
                    fontFamily: font,
                  }}
                />
              </div>
              {/* Filter */}
              <button style={{
                display: 'flex', alignItems: 'center', gap: 4,
                padding: '6px 12px', fontSize: 13, border: `1px solid ${T.line}`,
                borderRadius: 6, background: T.container, color: T.txt2, cursor: 'pointer',
                fontFamily: font,
              }}>
                <FilterOutlined style={{ fontSize: 12 }} />
                全部状态
              </button>
            </div>
            <button style={{
              display: 'flex', alignItems: 'center', gap: 6,
              padding: '6px 16px', fontSize: 13, fontWeight: 500,
              border: 'none', borderRadius: 6, background: T.primary,
              color: '#fff', cursor: 'pointer', fontFamily: font,
            }}>
              <PlusOutlined style={{ fontSize: 12 }} />
              新建 Agent
            </button>
          </div>

          {/* Agent list — table-like cards, not grid of boxes */}
          <div style={{
            background: T.container, border: `1px solid ${T.line}`, borderRadius: 8,
            overflow: 'hidden',
          }}>
            {/* Table header */}
            <div style={{
              display: 'grid',
              gridTemplateColumns: '1fr 100px 100px 80px 100px 80px',
              padding: '0 20px', height: 40, alignItems: 'center',
              background: T.elevated, borderBottom: `1px solid ${T.line}`,
            }}>
              <span style={{ fontSize: 12, fontWeight: 500, color: T.txt3 }}>名称</span>
              <span style={{ fontSize: 12, fontWeight: 500, color: T.txt3 }}>模型</span>
              <span style={{ fontSize: 12, fontWeight: 500, color: T.txt3 }}>状态</span>
              <span style={{ fontSize: 12, fontWeight: 500, color: T.txt3 }}>工具</span>
              <span style={{ fontSize: 12, fontWeight: 500, color: T.txt3 }}>更新时间</span>
              <span style={{ fontSize: 12, fontWeight: 500, color: T.txt3, textAlign: 'right' }}>操作</span>
            </div>

            {/* Rows */}
            {filtered.map((agent, i) => {
              const st = STATUS_MAP[agent.status] || STATUS_MAP.draft
              return (
                <div
                  key={agent.id}
                  style={{
                    display: 'grid',
                    gridTemplateColumns: '1fr 100px 100px 80px 100px 80px',
                    padding: '0 20px', height: 52, alignItems: 'center',
                    borderBottom: i < filtered.length - 1 ? `1px solid ${T.line2}` : 'none',
                    cursor: 'pointer',
                    transition: 'background 0.15s',
                  }}
                  onMouseEnter={e => (e.currentTarget.style.background = '#F8FAFC')}
                  onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
                >
                  {/* Name + desc */}
                  <div style={{ minWidth: 0 }}>
                    <div style={{ fontSize: 14, fontWeight: 500, color: T.txt, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {agent.name}
                    </div>
                    <div style={{ fontSize: 12, color: T.txt3, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {agent.desc}
                    </div>
                  </div>

                  {/* Model */}
                  <span style={{ fontSize: 13, fontFamily: mono, color: T.txt2 }}>{agent.model}</span>

                  {/* Status badge */}
                  <span style={{
                    display: 'inline-flex', alignItems: 'center',
                    fontSize: 12, fontWeight: 500, color: st.color,
                    background: st.bg, padding: '2px 8px', borderRadius: 4,
                    width: 'fit-content',
                  }}>
                    {st.label}
                  </span>

                  {/* Tools count */}
                  <div style={{ display: 'flex', gap: 4 }}>
                    {agent.skills > 0 && (
                      <span style={{ fontSize: 11, color: T.primary, background: T.primaryBg, padding: '1px 6px', borderRadius: 4 }}>
                        {agent.skills} Skill
                      </span>
                    )}
                    {agent.mcp > 0 && (
                      <span style={{ fontSize: 11, color: T.success, background: T.successBg, padding: '1px 6px', borderRadius: 4 }}>
                        {agent.mcp} MCP
                      </span>
                    )}
                  </div>

                  {/* Time */}
                  <span style={{ fontSize: 12, color: T.txt3 }}>{agent.updated}</span>

                  {/* Actions */}
                  <div style={{ display: 'flex', gap: 2, justifyContent: 'flex-end' }}>
                    {agent.status !== 'published' && (
                      <IconButton icon={<CloudUploadOutlined />} color={T.success} title="发布" />
                    )}
                    {agent.status === 'published' && (
                      <IconButton icon={<StopOutlined />} color={T.warning} title="下架" />
                    )}
                    <IconButton icon={<CopyOutlined />} color={T.txt3} title="复制" />
                    <IconButton icon={<DeleteOutlined />} color={T.txt3} title="删除" hoverColor={T.error} />
                  </div>
                </div>
              )
            })}

            {filtered.length === 0 && (
              <div style={{ padding: '48px 0', textAlign: 'center', color: T.muted }}>
                <InboxOutlined style={{ fontSize: 28, marginBottom: 8 }} />
                <div style={{ fontSize: 14 }}>未找到匹配的 Agent</div>
                <div style={{ fontSize: 12, marginTop: 4 }}>尝试修改搜索关键词或筛选条件</div>
              </div>
            )}
          </div>
        </section>

        {/* ═══════════════ Section 5: Status Tags ═══════════════ */}
        <section style={{ marginBottom: 48 }}>
          <SectionTitle>状态标签（Status Badges）</SectionTitle>
          <p style={{ fontSize: 13, color: T.txt2, marginBottom: 20, lineHeight: 1.6 }}>
            语义色一致映射：已发布 = success、草稿 = muted、执行中 = primary + pulse、失败 = error。圆角统一 4px。
          </p>
          <div style={{ background: T.container, border: `1px solid ${T.line}`, borderRadius: 8, padding: 20 }}>
            <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center' }}>
              <Badge color={T.muted} bg={T.elevated} label="草稿" />
              <Badge color={T.success} bg={T.successBg} label="已发布" />
              <Badge color={T.primary} bg={T.primaryBg} label="执行中..." pulse />
              <Badge color={T.success} bg={T.successBg} label="成功" />
              <Badge color={T.error} bg={T.errorBg} label="失败" />
              <Badge color={T.warning} bg={T.warningBg} label="嵌套警告" />
              <Badge color={T.accent} bg={T.accentBg} label="AI 思考中" pulse />
            </div>
          </div>
        </section>

        {/* ═══════════════ Section 6: Buttons ═══════════════ */}
        <section style={{ marginBottom: 48 }}>
          <SectionTitle>按钮系统（Buttons）</SectionTitle>
          <p style={{ fontSize: 13, color: T.txt2, marginBottom: 20, lineHeight: 1.6 }}>
            圆角 6px，高度 32px（中）/ 28px（小）。Primary = 实心 Indigo，Default = 白底灰框，Danger = 白底红框。
          </p>
          <div style={{ background: T.container, border: `1px solid ${T.line}`, borderRadius: 8, padding: 20 }}>
            <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center' }}>
              <Btn primary>保存</Btn>
              <Btn>取消</Btn>
              <Btn danger>删除</Btn>
              <Btn>
                <PlusOutlined style={{ fontSize: 12, marginRight: 4 }} />
                新建
              </Btn>
              <Btn disabled>禁用</Btn>
            </div>
          </div>
        </section>

        {/* ═══════════════ Section 7: Before/After Comparison ═══════════════ */}
        <section style={{ marginBottom: 48 }}>
          <SectionTitle>对比：改进前 vs 改进后</SectionTitle>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
            {/* Before */}
            <div>
              <div style={{ fontSize: 12, color: T.error, fontWeight: 500, marginBottom: 8 }}>❌ 改进前</div>
              <div style={{
                background: T.container, border: `1px solid ${T.line}`, borderRadius: 16,
                padding: 20, boxShadow: '0 1px 3px rgba(0,0,0,0.06)',
              }}>
                <div style={{ fontSize: 14, fontWeight: 600, color: '#0F172A', marginBottom: 12 }}>
                  客服助手 Pro
                </div>
                <div style={{ display: 'flex', gap: 6, marginBottom: 12, flexWrap: 'wrap' }}>
                  <span style={{ fontSize: 11, color: '#2563EB', background: '#EFF6FF', padding: '2px 8px', borderRadius: 6 }}>GPT-4o</span>
                  <span style={{ fontSize: 11, color: '#10B981', background: '#D1FAE5', padding: '2px 8px', borderRadius: 6 }}>已发布</span>
                  <span style={{ fontSize: 11, color: '#3B82F6', background: '#EFF6FF', padding: '2px 8px', borderRadius: 6 }}>3 Skill</span>
                </div>
                <div style={{ fontSize: 12, color: '#64748B' }}>基于 GPT-4 的多轮对话客服 Agent</div>
              </div>
              <div style={{ fontSize: 11, color: T.txt3, marginTop: 8, lineHeight: 1.6 }}>
                问题：圆角 16px（过大）、Blue 主色（与规范不符）、卡片有阴影（违反 surface ladder）、Tag 圆角 6px（与卡片不协调）、标题和正文 weight 差不足
              </div>
            </div>

            {/* After */}
            <div>
              <div style={{ fontSize: 12, color: T.success, fontWeight: 500, marginBottom: 8 }}>✓ 改进后</div>
              <div style={{
                background: T.container, border: `1px solid ${T.line}`, borderRadius: 8,
                padding: 20,
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
                  <div style={{
                    width: 36, height: 36, borderRadius: 8, background: T.primaryBg,
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    color: T.primary, fontSize: 16,
                  }}>
                    <RobotOutlined />
                  </div>
                  <div>
                    <div style={{ fontSize: 15, fontWeight: 500, color: T.txt }}>
                      客服助手 Pro
                    </div>
                    <div style={{ fontSize: 12, color: T.txt3 }}>GPT-4o · 已发布</div>
                  </div>
                </div>
                <div style={{ fontSize: 13, color: T.txt2, lineHeight: 1.5, marginBottom: 12 }}>
                  基于 GPT-4 的多轮对话客服 Agent，支持工单创建和知识库查询
                </div>
                <div style={{ display: 'flex', gap: 6 }}>
                  <span style={{ fontSize: 11, color: T.primary, background: T.primaryBg, padding: '2px 8px', borderRadius: 4 }}>3 Skill</span>
                  <span style={{ fontSize: 11, color: T.success, background: T.successBg, padding: '2px 8px', borderRadius: 4 }}>2 MCP</span>
                </div>
              </div>
              <div style={{ fontSize: 11, color: T.txt3, marginTop: 8, lineHeight: 1.6 }}>
                改进：圆角 8px（容器）/ 4px（Tag）、Indigo 主色、无阴影卡片（hairline border）、type scale 清晰（15/500 标题 + 13/400 正文）、信息层次通过 icon + 副标题增强
              </div>
            </div>
          </div>
        </section>

        {/* Footer note */}
        <div style={{
          padding: '16px 20px', background: T.primaryBg, borderRadius: 8,
          border: `1px solid ${T.primary}20`, fontSize: 13, color: T.txt2, lineHeight: 1.6,
        }}>
          <strong style={{ color: T.primary }}>💡 如何使用这个参考页：</strong>
          <span style={{ marginLeft: 4 }}>
            这个页面展示了与 DESIGN.md 对齐的视觉系统。确认设计方向后，可以用 <code style={{ fontFamily: mono, fontSize: 12, background: T.container, padding: '1px 4px', borderRadius: 3 }}>/impeccable polish</code> 将改进逐步应用到实际页面。
          </span>
        </div>
      </div>
    </div>
  )
}

/* ─── Helper components ─── */

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h2 style={{
      fontSize: 18, fontWeight: 600, letterSpacing: '-0.01em',
      color: T.txt, marginBottom: 4,
    }}>
      {children}
    </h2>
  )
}

function SurfaceDemo({ label, color, desc, bordered }: { label: string; color: string; desc: string; bordered?: boolean }) {
  return (
    <div style={{
      padding: '10px 14px', borderRadius: 6,
      background: color,
      border: bordered ? `1px solid ${T.line}` : `1px solid ${T.line2}`,
    }}>
      <div style={{ fontSize: 13, fontWeight: 500, color: T.txt }}>{label}</div>
      <div style={{ fontSize: 12, color: T.txt3, fontFamily: mono }}>{desc}</div>
    </div>
  )
}

function ColorSwatch({ name, value, usage, dark }: { name: string; value: string; usage: string; dark?: boolean }) {
  return (
    <div style={{
      background: T.container, border: `1px solid ${T.line}`, borderRadius: 8,
      overflow: 'hidden',
    }}>
      <div style={{ height: 48, background: value }} />
      <div style={{ padding: '8px 12px' }}>
        <div style={{ fontSize: 13, fontWeight: 500, color: T.txt }}>{name}</div>
        <div style={{ fontSize: 11, fontFamily: mono, color: T.txt3 }}>{value}</div>
        <div style={{ fontSize: 11, color: dark ? T.txt3 : T.txt2, marginTop: 2 }}>{usage}</div>
      </div>
    </div>
  )
}

function Badge({ color, bg, label, pulse }: { color: string; bg: string; label: string; pulse?: boolean }) {
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 4,
      fontSize: 12, fontWeight: 500, color, background: bg,
      padding: '2px 10px', borderRadius: 4,
    }}>
      {pulse && (
        <span style={{
          width: 6, height: 6, borderRadius: '50%', background: color,
          animation: 'pulse 1.5s ease-in-out infinite',
        }} />
      )}
      {label}
      <style>{`@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }`}</style>
    </span>
  )
}

function Btn({ children, primary, danger, disabled }: { children: React.ReactNode; primary?: boolean; danger?: boolean; disabled?: boolean }) {
  const bg = disabled ? T.elevated : primary ? T.primary : T.container
  const color = disabled ? T.muted : primary ? '#fff' : danger ? T.error : T.txt
  const border = disabled ? T.line : primary ? 'transparent' : danger ? T.error : T.line

  return (
    <button
      disabled={disabled}
      style={{
        display: 'inline-flex', alignItems: 'center',
        padding: '5px 14px', fontSize: 13, fontWeight: 500,
        background: bg, color, border: `1px solid ${border}`,
        borderRadius: 6, cursor: disabled ? 'not-allowed' : 'pointer',
        fontFamily: font, transition: 'all 0.15s',
      }}
    >
      {children}
    </button>
  )
}

function IconButton({ icon, color, title, hoverColor }: { icon: React.ReactNode; color: string; title: string; hoverColor?: string }) {
  const [hovered, setHovered] = useState(false)
  return (
    <button
      title={title}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        width: 28, height: 28, display: 'flex', alignItems: 'center', justifyContent: 'center',
        border: 'none', background: hovered ? T.elevated : 'transparent',
        borderRadius: 4, cursor: 'pointer', fontSize: 13,
        color: hovered && hoverColor ? hoverColor : color,
        transition: 'all 0.15s',
      }}
    >
      {icon}
    </button>
  )
}
