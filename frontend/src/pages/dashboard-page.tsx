/**
 * Dashboard page — overview with stats, recent executions, and system health.
 */
import { Button, Progress, Tag } from 'antd'
import {
  RobotOutlined,
  BranchesOutlined,
  ThunderboltOutlined,
  CheckCircleOutlined,
  ArrowUpOutlined,
  ArrowDownOutlined,
  SearchOutlined,
  FilterOutlined,
  DownloadOutlined,
  PlusOutlined,
  MoreOutlined,
} from '@ant-design/icons'
import { useTheme } from '../contexts/ThemeContext'

const STATS = [
  { title: '活跃 Agent', value: '12', icon: <RobotOutlined />, change: '+3', up: true },
  { title: '运行工作流', value: '8', icon: <BranchesOutlined />, change: '+2', up: true },
  { title: '今日执行', value: '156', icon: <ThunderboltOutlined />, change: '+12%', up: true },
  { title: '成功率', value: '98.5%', icon: <CheckCircleOutlined />, change: '-0.3%', up: false },
]

const EXECUTIONS = [
  { name: '数据分析工作流', desc: 'GPT-4 · 5 步骤', status: '成功', statusType: 'success', time: '2 分钟前', pct: 100 },
  { name: '客户支持 Agent', desc: 'Claude 3 · 工具调用', status: '运行中', statusType: 'running', time: '15 分钟前', pct: 65 },
  { name: '代码审查流水线', desc: 'Gemini · 3 步骤', status: '成功', statusType: 'success', time: '1 小时前', pct: 100 },
  { name: '数据同步任务', desc: 'GPT-4 · 定时任务', status: '失败', statusType: 'error', time: '3 小时前', pct: 42 },
  { name: '邮件摘要生成', desc: 'Claude 3 · 队列消费', status: '成功', statusType: 'success', time: '5 小时前', pct: 100 },
]

const RESOURCES = [
  { label: 'CPU', pct: 45 },
  { label: '内存', pct: 72 },
  { label: '存储', pct: 38 },
  { label: 'API 配额', pct: 88 },
]

const TAGS = ['GPT-4', 'Claude', '自动化', 'RAG', '工具链', 'Pipeline', 'NLP']

export default function DashboardPage() {
  const { t } = useTheme()

  return (
    <div className="animate-[fadeIn_0.3s_ease-out]">
      {/* Stats */}
      <div className="grid grid-cols-4 gap-4 mb-6">
        {STATS.map((s) => (
          <div
            key={s.title}
            className="rounded-xl border border-gray-200 bg-white p-5 hover:shadow-sm transition-shadow duration-200"
          >
            <div className="flex items-start justify-between mb-3">
              <div className="w-10 h-10 rounded-lg flex items-center justify-center text-base" style={{ background: t.bg, color: t.primary }}>
                {s.icon}
              </div>
              <span className={`text-xs font-medium inline-flex items-center gap-0.5 ${s.up ? 'text-[#10B981]' : 'text-[#EF4444]'}`}>
                {s.up ? <ArrowUpOutlined /> : <ArrowDownOutlined />}
                {s.change}
              </span>
            </div>
            <div className="text-2xl font-semibold text-[#0F172A] mb-0.5" style={{ letterSpacing: '-0.02em' }}>{s.value}</div>
            <div className="text-xs text-[#64748B]">{s.title}</div>
          </div>
        ))}
      </div>

      {/* Action bar */}
      <div className="flex items-center justify-between gap-4 mb-6">
        <div className="flex items-center gap-2">
          <div className="relative">
            <SearchOutlined className="absolute left-3 top-1/2 -translate-y-1/2 text-[#94A3B8] text-sm" />
            <input
              type="text"
              placeholder="搜索 Agent、工作流..."
              className="pl-9 pr-4 py-2 rounded-lg border border-gray-200 text-sm focus:outline-none focus:ring-2 w-72"
              style={{ '--tw-ring-color': t.bg } as React.CSSProperties}
            />
          </div>
          <Button icon={<FilterOutlined />}>筛选</Button>
        </div>
        <div className="flex items-center gap-2">
          <Button icon={<DownloadOutlined />}>导出</Button>
          <Button type="primary" icon={<PlusOutlined />}>新建 Agent</Button>
        </div>
      </div>

      {/* Two columns */}
      <div className="grid grid-cols-3 gap-4">
        {/* Left: Recent executions */}
        <div className="col-span-2 rounded-xl border border-gray-200 bg-white">
          <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between">
            <span className="font-semibold text-[#0F172A]">最近执行</span>
            <button className="border-0 bg-transparent text-xs font-medium cursor-pointer hover:opacity-80 transition-opacity" style={{ color: t.primary }}>查看全部 →</button>
          </div>
          {EXECUTIONS.map((item, i) => (
            <div
              key={i}
              className={`flex items-center justify-between px-5 py-3 hover:bg-[#F8FAFC] transition-colors duration-150 cursor-pointer ${i > 0 ? 'border-t border-gray-50' : ''}`}
            >
              <div className="flex items-center gap-3 min-w-0 flex-1">
                <div className="w-9 h-9 rounded-lg bg-[#F1F5F9] flex items-center justify-center text-[#475569] shrink-0">
                  <BranchesOutlined />
                </div>
                <div className="min-w-0">
                  <div className="text-sm font-medium text-[#0F172A] truncate">{item.name}</div>
                  <div className="text-xs text-[#64748B] truncate">{item.desc}</div>
                </div>
              </div>
              <div className="flex items-center gap-4 ml-3">
                <Progress percent={item.pct} size="small" className="!w-16 hidden sm:block" showInfo={false}
                  strokeColor={item.statusType === 'success' ? '#10B981' : item.statusType === 'error' ? '#EF4444' : t.primary}
                  railColor="#F1F5F9"
                />
                <span className="text-xs text-[#94A3B8] w-16 text-right hidden md:inline">{item.time}</span>
                <span
                  className={`text-xs font-medium px-2 py-0.5 rounded w-14 text-center ${
                    item.statusType === 'success' ? 'text-[#10B981] bg-[#D1FAE5]'
                      : item.statusType === 'error' ? 'text-[#EF4444] bg-[#FEE2E2]'
                      : ''
                  }`}
                  style={item.statusType === 'running' ? { color: t.primary, background: t.bg } : undefined}
                >
                  {item.status}
                </span>
                <button className="border-0 bg-transparent w-8 h-8 flex items-center justify-center rounded-md text-[#64748B] hover:text-[#0F172A] hover:bg-gray-50 transition-colors duration-150"><MoreOutlined /></button>
              </div>
            </div>
          ))}
        </div>

        {/* Right column */}
        <div className="space-y-4">
          {/* System resources */}
          <div className="rounded-xl border border-gray-200 bg-white">
            <div className="px-5 py-4 border-b border-gray-100">
              <span className="font-semibold text-[#0F172A]">系统资源</span>
            </div>
            <div className="p-5 space-y-5">
              {RESOURCES.map((r) => (
                <div key={r.label}>
                  <div className="flex justify-between text-sm mb-1.5">
                    <span className="text-[#475569]">{r.label}</span>
                    <span className="font-medium text-[#0F172A] font-mono text-xs">{r.pct}%</span>
                  </div>
                  <div className="h-1.5 bg-[#F1F5F9] rounded-full overflow-hidden">
                    <div className="h-full rounded-full transition-all duration-500" style={{ width: `${r.pct}%`, background: t.primary }} />
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Quick actions */}
          <div className="rounded-xl border border-gray-200 bg-white">
            <div className="px-5 py-4 border-b border-gray-100">
              <span className="font-semibold text-[#0F172A]">快捷操作</span>
            </div>
            <div className="p-4 space-y-2">
              <Button type="primary" icon={<PlusOutlined />} block>创建 Agent</Button>
              <Button icon={<BranchesOutlined />} block>新建工作流</Button>
              <Button icon={<SearchOutlined />} block>查看日志</Button>
            </div>
          </div>

          {/* Tags */}
          <div className="rounded-xl border border-gray-200 bg-white p-5">
            <div className="text-sm font-semibold text-[#0F172A] mb-3">活跃标签</div>
            <div className="flex flex-wrap gap-1.5">
              {TAGS.map((tag) => (
                <Tag key={tag} color={t.primary}>{tag}</Tag>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
