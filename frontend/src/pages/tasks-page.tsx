/**
 * Tasks page — manage workflow tasks and executions.
 *
 * Provides an overview of all task runs, their status, duration,
 * and allows retry/cancel operations on failed or running tasks.
 */
import { useState } from 'react'
import { Button, Tag, Select, Tooltip } from 'antd'
import {
  PlusOutlined,
  SearchOutlined,
  PlayCircleOutlined,
  PauseCircleOutlined,
  CloseCircleOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  RedoOutlined,
  StopOutlined,
  DeleteOutlined,
  FileTextOutlined,
} from '@ant-design/icons'
import { useTheme } from '../contexts/ThemeContext'

/* ─── Mock data ─── */
const TASKS = [
  { id: 'TASK-20260601', name: '数据日报生成', workflow: '日报自动生成', status: 'completed', duration: '1m 23s', model: 'GPT-4', startTime: '2026-06-01 09:00', endTime: '2026-06-01 09:01' },
  { id: 'TASK-20260602', name: '客户投诉分类', workflow: '工单处理', status: 'running', duration: '2m 15s', model: 'Claude 3', startTime: '2026-06-01 09:30', endTime: '-' },
  { id: 'TASK-20260603', name: '代码质量扫描', workflow: 'CI 代码审查', status: 'failed', duration: '45s', model: 'Gemini', startTime: '2026-06-01 08:45', endTime: '2026-06-01 08:46' },
  { id: 'TASK-20260604', name: '周报摘要生成', workflow: '报告生成', status: 'completed', duration: '3m 10s', model: 'GPT-4', startTime: '2026-06-01 10:00', endTime: '2026-06-01 10:03' },
  { id: 'TASK-20260605', name: '邮件批量回复', workflow: '邮件处理', status: 'pending', duration: '-', model: 'GPT-4o', startTime: '-', endTime: '-' },
  { id: 'TASK-20260606', name: '销售数据分析', workflow: '数据分析', status: 'cancelled', duration: '12s', model: 'GPT-4', startTime: '2026-05-31 16:00', endTime: '2026-05-31 16:00' },
]

/* ─── Status mappings ─── */
const STATUS_STYLES: Record<string, { label: string; color: string; bg: string; icon: React.ReactNode }> = {
  completed: { label: '已完成', color: '#10B981', bg: '#D1FAE5', icon: <CheckCircleOutlined /> },
  running: { label: '运行中', color: '#2563EB', bg: '#DBEAFE', icon: <PlayCircleOutlined /> },
  failed: { label: '失败', color: '#EF4444', bg: '#FEE2E2', icon: <CloseCircleOutlined /> },
  pending: { label: '等待中', color: '#F59E0B', bg: '#FEF3C7', icon: <ClockCircleOutlined /> },
  cancelled: { label: '已取消', color: '#94A3B8', bg: '#F1F5F9', icon: <PauseCircleOutlined /> },
}

export default function TasksPage() {
  const { t } = useTheme()
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('all')

  const filtered = TASKS.filter((task) => {
    const matchSearch = task.name.toLowerCase().includes(search.toLowerCase()) || task.id.toLowerCase().includes(search.toLowerCase())
    const matchStatus = statusFilter === 'all' || task.status === statusFilter
    return matchSearch && matchStatus
  })

  return (
    <div className="animate-[fadeIn_0.3s_ease-out]">
      {/* Stats row */}
      <div className="grid grid-cols-4 gap-4 mb-6">
        {[
          { label: '任务总数', value: TASKS.length.toString() },
          { label: '运行中', value: TASKS.filter(t => t.status === 'running').length.toString() },
          { label: '今日完成', value: TASKS.filter(t => t.status === 'completed').length.toString() },
          { label: '失败率', value: `${Math.round((TASKS.filter(t => t.status === 'failed').length / TASKS.length) * 100)}%` },
        ].map((s) => (
          <div key={s.label} className="rounded-xl border border-gray-200 bg-white p-4">
            <div className="text-2xl font-semibold text-[#0F172A] mb-0.5">{s.value}</div>
            <div className="text-xs text-[#64748B]">{s.label}</div>
          </div>
        ))}
      </div>

      {/* Search / action bar */}
      <div className="flex items-center justify-between gap-4 mb-6">
        <div className="flex items-center gap-3">
          <div className="relative">
            <SearchOutlined className="absolute left-3 top-1/2 -translate-y-1/2 text-[#94A3B8] text-sm" />
            <input
              type="text"
              placeholder="搜索任务 ID 或名称..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-9 pr-4 py-2 rounded-lg border border-gray-200 text-sm focus:outline-none focus:ring-2 w-64"
              style={{ '--tw-ring-color': t.bg } as React.CSSProperties}
            />
          </div>
          <Select
            value={statusFilter}
            onChange={setStatusFilter}
            className="w-28"
            options={[
              { value: 'all', label: '全部状态' },
              { value: 'completed', label: '已完成' },
              { value: 'running', label: '运行中' },
              { value: 'failed', label: '失败' },
              { value: 'pending', label: '等待中' },
              { value: 'cancelled', label: '已取消' },
            ]}
          />
        </div>
        <div className="flex items-center gap-2">
          <Button icon={<RedoOutlined />}>刷新</Button>
          <Button type="primary" icon={<PlusOutlined />}>新建任务</Button>
        </div>
      </div>

      {/* Task rows (table-panel) */}
      <div className="rounded-xl border border-gray-200 bg-white">
        {/* Table header */}
        <div className="grid grid-cols-[1fr_1fr_100px_90px_150px_80px] gap-4 px-5 py-3 bg-[#F8FAFC] border-b border-gray-100 text-xs font-medium text-[#64748B] items-center">
          <span>任务 / ID</span>
          <span>工作流</span>
          <span>状态</span>
          <span>耗时</span>
          <span>执行时间</span>
          <span>操作</span>
        </div>

        {filtered.map((task, i) => {
          const ss = STATUS_STYLES[task.status]
          return (
            <div
              key={task.id}
              className={`grid grid-cols-[1fr_1fr_100px_90px_150px_80px] gap-4 px-5 py-3.5 items-center hover:bg-[#F8FAFC] transition-colors duration-150 ${i > 0 ? 'border-t border-gray-50' : ''}`}
            >
              {/* Name + ID */}
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <FileTextOutlined className="text-[#94A3B8] text-xs" />
                  <span className="text-sm font-medium text-[#0F172A] truncate">{task.name}</span>
                </div>
                <div className="text-[11px] font-mono text-[#94A3B8] mt-0.5">{task.id}</div>
              </div>

              {/* Workflow */}
              <div className="flex items-center gap-2">
                <span className="text-sm text-[#64748B]">{task.workflow}</span>
                <Tag className="!m-0 !px-1.5 !py-0 !text-[10px] !rounded" style={{ color: '#64748B', background: '#F1F5F9', borderColor: 'transparent' }}>{task.model}</Tag>
              </div>

              {/* Status */}
              <Tag className="!m-0 !inline-flex !items-center !gap-1 !px-2 !py-0.5 !text-[11px] !rounded !w-fit" style={{ color: ss.color, background: ss.bg, borderColor: 'transparent' }}>
                {ss.icon}
                {ss.label}
              </Tag>

              {/* Duration */}
              <span className="text-sm text-[#64748B]">{task.duration}</span>

              {/* Execution time */}
              <div>
                <div className="text-xs text-[#64748B]">{task.startTime}</div>
                {task.endTime !== '-' && (
                  <div className="text-[10px] text-[#94A3B8]">{task.endTime}</div>
                )}
              </div>

              {/* Actions */}
              <div className="flex items-center gap-1">
                {task.status === 'running' && (
                  <Tooltip title="取消">
                    <button className="border-0 bg-transparent w-7 h-7 flex items-center justify-center rounded text-[#94A3B8] hover:text-[#EF4444] hover:bg-gray-50 transition-colors duration-150 text-xs"><StopOutlined /></button>
                  </Tooltip>
                )}
                {task.status === 'failed' && (
                  <Tooltip title="重试">
                    <button className="border-0 bg-transparent w-7 h-7 flex items-center justify-center rounded text-[#94A3B8] hover:text-[#2563EB] hover:bg-gray-50 transition-colors duration-150 text-xs"><RedoOutlined /></button>
                  </Tooltip>
                )}
                {task.status === 'completed' && (
                  <Tooltip title="查看">
                    <button className="border-0 bg-transparent w-7 h-7 flex items-center justify-center rounded text-[#94A3B8] hover:text-[#0F172A] hover:bg-gray-50 transition-colors duration-150 text-xs"><FileTextOutlined /></button>
                  </Tooltip>
                )}
                <Tooltip title="删除">
                  <button className="border-0 bg-transparent w-7 h-7 flex items-center justify-center rounded text-[#94A3B8] hover:text-[#EF4444] hover:bg-gray-50 transition-colors duration-150 text-xs"><DeleteOutlined /></button>
                </Tooltip>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
