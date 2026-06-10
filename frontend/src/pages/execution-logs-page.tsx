/**
 * Execution Logs page — detailed log viewer with log level filtering & expandable details.
 *
 * Aligned with Story 9-4: Execution log list and detail page UI (minimal viable).
 */
import { useState } from 'react'
import { Button, Tag, Select, Tooltip } from 'antd'
import { SearchOutlined, FilterOutlined, DownloadOutlined, FileTextOutlined, CheckCircleOutlined, CloseCircleOutlined, WarningOutlined, MoreOutlined, ClockCircleOutlined, GithubOutlined, NodeIndexOutlined } from '@ant-design/icons'
import { useTheme } from '../contexts/ThemeContext'

const LOGS = [
  { id: 'log_001', task: '数据分析工作流', step: '步骤 3/5 — 数据清洗', agent: '数据分析助手', status: 'success', duration: '2.3s', time: '2026-06-09 10:23:15', tokens: 847, model: 'gpt-4', trace_id: 'trace_abc123' },
  { id: 'log_002', task: '客户支持', step: '意图识别', agent: '客户支持 Bot', status: 'success', duration: '1.1s', time: '2026-06-09 10:22:01', tokens: 432, model: 'claude-3', trace_id: 'trace_def456' },
  { id: 'log_003', task: '代码审查', step: '安全扫描', agent: '代码审查 Agent', status: 'warning', duration: '4.7s', time: '2026-06-09 10:20:45', tokens: 1523, model: 'gemini', trace_id: 'trace_ghi789' },
  { id: 'log_004', task: '数据同步', step: '写入数据库', agent: '数据同步 Agent', status: 'error', duration: '12.5s', time: '2026-06-09 10:18:30', tokens: 0, model: 'claude-3', trace_id: 'trace_jkl012' },
  { id: 'log_005', task: '邮件摘要', step: '内容生成', agent: '邮件处理助手', status: 'success', duration: '3.2s', time: '2026-06-09 10:15:00', tokens: 654, model: 'gpt-4', trace_id: 'trace_mno345' },
  { id: 'log_006', task: '报告生成', step: '图表渲染', agent: '报告生成器', status: 'running', duration: '--', time: '2026-06-09 10:30:22', tokens: 0, model: 'gpt-4', trace_id: 'trace_pqr678' },
  { id: 'log_007', task: '客户支持', step: '情绪分析', agent: '客户支持 Bot', status: 'success', duration: '0.8s', time: '2026-06-09 10:12:18', tokens: 321, model: 'claude-3', trace_id: 'trace_stu901' },
  { id: 'log_008', task: '数据分析', step: '数据清洗', agent: '数据分析助手', status: 'success', duration: '5.1s', time: '2026-06-09 10:08:44', tokens: 1098, model: 'gpt-4', trace_id: 'trace_vwx234' },
  { id: 'log_009', task: '数据分析', step: '异常检测', agent: '数据分析助手', status: 'error', duration: '8.3s', time: '2026-06-09 10:05:00', tokens: 0, model: 'gpt-4', trace_id: 'trace_yz5678' },
  { id: 'log_010', task: '代码审查', step: '风格检查', agent: '代码审查 Agent', status: 'success', duration: '1.5s', time: '2026-06-09 09:55:30', tokens: 234, model: 'gemini', trace_id: 'trace_abc901' },
]

const STATUS_STYLES: Record<string, { label: string; color: string; bg: string; icon: React.ReactNode }> = {
  success: { label: '成功', color: '#10B981', bg: '#D1FAE5', icon: <CheckCircleOutlined /> },
  warning: { label: '警告', color: '#F59E0B', bg: '#FEF3C7', icon: <WarningOutlined /> },
  error: { label: '失败', color: '#EF4444', bg: '#FEE2E2', icon: <CloseCircleOutlined /> },
  running: { label: '运行中', color: '#2563EB', bg: '#EFF6FF', icon: null },
}

const LEVEL_OPTIONS = [
  { value: 'all', label: '全部状态' },
  { value: 'success', label: '成功' },
  { value: 'warning', label: '警告' },
  { value: 'error', label: '失败' },
  { value: 'running', label: '运行中' },
]

export default function ExecutionLogsPage() {
  const { t } = useTheme()
  const [levelFilter, setLevelFilter] = useState('all')
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})

  const filtered = levelFilter === 'all' ? LOGS : LOGS.filter((l) => l.status === levelFilter)

  const toggleExpand = (id: string) => setExpanded((prev) => ({ ...prev, [id]: !prev[id] }))

  return (
    <div className="animate-[fadeIn_0.3s_ease-out]">
      {/* Stats */}
      <div className="grid grid-cols-4 gap-4 mb-6">
        {[
          { label: '总执行', value: LOGS.length.toString() },
          { label: '成功', value: LOGS.filter(l => l.status === 'success').length.toString() },
          { label: '失败', value: LOGS.filter(l => l.status === 'error').length.toString() },
          { label: '平均耗时', value: '3.2s' },
        ].map((s) => (
          <div key={s.label} className="rounded-xl border border-gray-200 bg-white p-4">
            <div className="text-2xl font-semibold text-[#0F172A] mb-0.5">{s.value}</div>
            <div className="text-xs text-[#64748B]">{s.label}</div>
          </div>
        ))}
      </div>

      {/* Filters */}
      <div className="flex items-center justify-between gap-4 mb-6">
        <div className="flex items-center gap-3">
          <div className="relative">
            <SearchOutlined className="absolute left-3 top-1/2 -translate-y-1/2 text-[#94A3B8] text-sm" />
            <input type="text" placeholder="搜索日志..." className="pl-9 pr-4 py-2 rounded-lg border border-gray-200 text-sm focus:outline-none focus:ring-2 w-64" style={{ '--tw-ring-color': t.bg } as React.CSSProperties} />
          </div>
          <Select value={levelFilter} onChange={setLevelFilter} className="w-28" options={LEVEL_OPTIONS} />
        </div>
        <Button icon={<DownloadOutlined />}>导出日志</Button>
      </div>

      {/* Log table */}
      <div className="rounded-xl border border-gray-200 bg-white overflow-hidden">
        {/* Table header */}
        <div className="grid grid-cols-[1fr_120px_80px_80px_100px_40px] gap-4 px-5 py-3 bg-[#F8FAFC] border-b border-gray-100 text-xs font-medium text-[#64748B]">
          <span>任务 / 步骤</span>
          <span>Agent</span>
          <span>耗时</span>
          <span>Tokens</span>
          <span>状态</span>
          <span></span>
        </div>

        {/* Rows */}
        {filtered.map((log, i) => {
          const st = STATUS_STYLES[log.status]
          const isExpanded = expanded[log.id]
          return (
            <div key={log.id}>
              <div
                className={`grid grid-cols-[1fr_120px_80px_80px_100px_40px] gap-4 px-5 py-3 items-center hover:bg-[#F8FAFC] transition-colors duration-150 cursor-pointer text-sm ${i > 0 ? 'border-t border-gray-50' : ''}`}
                onClick={() => toggleExpand(log.id)}
              >
                <div className="flex items-center gap-2.5 min-w-0">
                  <FileTextOutlined className="text-[#94A3B8] text-xs shrink-0" />
                  <div className="min-w-0">
                    <div className="text-[#0F172A] truncate text-sm">{log.task}</div>
                    <div className="text-[#94A3B8] truncate text-[11px]">{log.step}</div>
                  </div>
                </div>
                <div className="flex items-center gap-1">
                  <span className="text-[#64748B] text-xs truncate">{log.agent}</span>
                </div>
                <span className="text-[#64748B] text-xs font-mono flex items-center gap-1">
                  <ClockCircleOutlined className="text-[9px]" />
                  {log.duration}
                </span>
                <span className="text-[#64748B] text-xs font-mono">{log.tokens || '--'}</span>
                <div>
                  {st ? (
                    <Tag className="!m-0 !inline-flex !items-center !gap-1 !px-2 !py-0.5 !text-xs !rounded" style={{ color: st.color, background: st.bg, borderColor: 'transparent' }}>
                      {st.icon}{st.label}
                    </Tag>
                  ) : null}
                </div>
                <button className="border-0 bg-transparent w-8 h-8 flex items-center justify-center rounded-md text-[#64748B] hover:text-[#0F172A] hover:bg-gray-50 transition-colors duration-150"><MoreOutlined /></button>
              </div>

              {/* Expanded detail row */}
              {isExpanded && (
                <div className="px-5 py-3 bg-[#FAFBFC] border-t border-gray-50 text-xs space-y-1.5">
                  <div className="flex items-center gap-4 text-[#64748B]">
                    <span className="flex items-center gap-1"><NodeIndexOutlined className="text-[10px]" /> Trace: <code className="font-mono text-[#0F172A]">{log.trace_id}</code></span>
                    <span>模型: <span className="text-[#0F172A]">{log.model}</span></span>
                    <span>时间: <span className="text-[#0F172A]">{log.time}</span></span>
                  </div>
                  <div className="flex items-center gap-2">
                    <Button size="small" type="primary" ghost icon={<GithubOutlined />}>查看详情</Button>
                    <Button size="small" icon={<DownloadOutlined />}>下载日志</Button>
                  </div>
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
