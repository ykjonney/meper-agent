/**
 * Workflows page — visual workflow card grid with execution status & version info.
 */
import { Button, Progress, Tag, Tooltip } from 'antd'
import { PlusOutlined, SearchOutlined, BranchesOutlined, MoreOutlined, PlayCircleOutlined, EditOutlined, HistoryOutlined, UserOutlined } from '@ant-design/icons'
import { useTheme } from '../contexts/ThemeContext'

const WORKFLOWS = [
  { id: 'wf_01HXYZ', name: '数据分析流水线', stages: 5, nodes: 8, model: 'gpt-4', status: 'active', version: 3, runs: 42, lastRun: '2 分钟前', pct: 100, editor: '张明', type: 'data' },
  { id: 'wf_02HABC', name: '客户意图分类', stages: 3, nodes: 5, model: 'claude-3', status: 'active', version: 2, runs: 128, lastRun: '5 分钟前', pct: 100, editor: '李华', type: 'nlp' },
  { id: 'wf_03HDEF', name: '文档摘要生成', stages: 4, nodes: 6, model: 'gemini', status: 'inactive', version: 1, runs: 18, lastRun: '1 天前', pct: 65, editor: '王芳', type: 'nlp' },
  { id: 'wf_04HGHI', name: '代码审查流水线', stages: 6, nodes: 10, model: 'gpt-4', status: 'active', version: 5, runs: 89, lastRun: '1 小时前', pct: 100, editor: '陈静', type: 'code' },
  { id: 'wf_05HJKL', name: '数据同步 ETL', stages: 3, nodes: 4, model: 'claude-3', status: 'error', version: 2, runs: 7, lastRun: '3 小时前', pct: 42, editor: '赵磊', type: 'data' },
  { id: 'wf_06HMNO', name: '邮件分类处理', stages: 4, nodes: 7, model: 'gpt-4', status: 'active', version: 4, runs: 256, lastRun: '10 分钟前', pct: 100, editor: '刘洋', type: 'nlp' },
]

const TYPE_LABELS: Record<string, string> = {
  data: '数据处理',
  nlp: 'NLP',
  code: '代码分析',
}

const MODEL_LABELS: Record<string, string> = {
  'gpt-4': 'GPT-4',
  'claude-3': 'Claude 3',
  'gemini': 'Gemini',
}

const STATUS_STYLES: Record<string, { label: string; color: string; bg: string }> = {
  active: { label: '活跃', color: '#10B981', bg: '#D1FAE5' },
  inactive: { label: '未激活', color: '#94A3B8', bg: '#F1F5F9' },
  error: { label: '异常', color: '#EF4444', bg: '#FEE2E2' },
}

export default function WorkflowsPage() {
  const { t } = useTheme()

  return (
    <div className="animate-[fadeIn_0.3s_ease-out]">
      {/* Stats */}
      <div className="grid grid-cols-4 gap-4 mb-6">
        {[
          { label: '工作流总数', value: WORKFLOWS.length.toString() },
          { label: '活跃中', value: WORKFLOWS.filter(w => w.status === 'active').length.toString() },
          { label: '累计运行', value: WORKFLOWS.reduce((s, w) => s + w.runs, 0).toLocaleString() },
          { label: '总节点数', value: WORKFLOWS.reduce((s, w) => s + w.nodes, 0).toString() },
        ].map((s) => (
          <div key={s.label} className="rounded-xl border border-gray-200 bg-white p-4">
            <div className="text-2xl font-semibold text-[#0F172A] mb-0.5">{s.value}</div>
            <div className="text-xs text-[#64748B]">{s.label}</div>
          </div>
        ))}
      </div>

      {/* Header actions */}
      <div className="flex items-center justify-between gap-4 mb-6">
        <div className="flex items-center gap-3">
          <div className="relative">
            <SearchOutlined className="absolute left-3 top-1/2 -translate-y-1/2 text-[#94A3B8] text-sm" />
            <input type="text" placeholder="搜索工作流..." className="pl-9 pr-4 py-2 rounded-lg border border-gray-200 text-sm focus:outline-none focus:ring-2 w-64" style={{ '--tw-ring-color': t.bg } as React.CSSProperties} />
          </div>
        </div>
        <Button type="primary" icon={<PlusOutlined />}>新建工作流</Button>
      </div>

      {/* Workflow cards */}
      <div className="grid grid-cols-3 gap-4">
        {WORKFLOWS.map((wf) => {
          const st = STATUS_STYLES[wf.status]
          return (
            <div key={wf.id} className="rounded-xl border border-gray-200 bg-white p-5 hover:shadow-sm transition-all duration-200">
              <div className="flex items-start justify-between mb-3">
                <div className="flex items-center gap-3 min-w-0">
                  <div className="w-10 h-10 rounded-lg flex items-center justify-center text-base shrink-0" style={{ background: t.bg, color: t.primary }}>
                    <BranchesOutlined />
                  </div>
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium text-[#0F172A] truncate">{wf.name}</span>
                      <Tooltip title={`v${wf.version}`}>
                        <span className="text-[10px] font-mono text-[#94A3B8] border border-gray-200 rounded px-1 leading-none py-0.5">v{wf.version}</span>
                      </Tooltip>
                    </div>
                    <div className="text-xs text-[#64748B]">{MODEL_LABELS[wf.model]} · {wf.nodes} 节点 · {TYPE_LABELS[wf.type]}</div>
                  </div>
                </div>
                <button className="border-0 bg-transparent w-8 h-8 flex items-center justify-center rounded-md text-[#64748B] hover:text-[#0F172A] hover:bg-gray-50 transition-colors duration-150 shrink-0"><MoreOutlined /></button>
              </div>

              {/* Progress */}
              <div className="mb-3">
                <Progress percent={wf.pct} size="small" showInfo={false}
                  strokeColor={wf.status === 'error' ? '#EF4444' : wf.status === 'inactive' ? '#94A3B8' : t.primary}
                  railColor="#F1F5F9"
                />
              </div>

              {/* Footer */}
              <div className="flex items-center justify-between pt-3 border-t border-gray-50">
                <div className="flex items-center gap-3 text-xs text-[#64748B]">
                  <span className="flex items-center gap-1"><UserOutlined className="text-[10px]" />{wf.editor}</span>
                  <span>·</span>
                  <span>{wf.lastRun}</span>
                </div>
                <div className="flex items-center gap-1">
                  <Tag className="!m-0 !px-2 !py-0.5 !text-xs !rounded" style={{ color: st.color, background: st.bg, borderColor: 'transparent' }}>
                    {st.label}
                  </Tag>
                  <Tooltip title="运行">
                    <button className="border-0 bg-transparent w-7 h-7 flex items-center justify-center rounded text-[#94A3B8] hover:text-[#0F172A] hover:bg-gray-50 transition-colors duration-150 text-xs"><PlayCircleOutlined /></button>
                  </Tooltip>
                  <Tooltip title="编辑">
                    <button className="border-0 bg-transparent w-7 h-7 flex items-center justify-center rounded text-[#94A3B8] hover:text-[#0F172A] hover:bg-gray-50 transition-colors duration-150 text-xs"><EditOutlined /></button>
                  </Tooltip>
                </div>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
