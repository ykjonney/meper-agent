/**
 * TaskResultCard — 任务结果卡片
 *
 * 当 LLM 调用 task_query 后，后端返回 {type: "task_result", status, output, error}
 * 前端检测后渲染此卡片显示任务执行结果。
 */
import { Tag, Typography } from 'antd'
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  SyncOutlined,
  ClockCircleOutlined,
} from '@ant-design/icons'

const { Text, Paragraph } = Typography

export interface TaskResult {
  type: 'task_result'
  task_id: string
  status: string
  output?: Record<string, unknown> | string | null
  error?: string | null
  message?: string
}

interface TaskResultCardProps {
  data: TaskResult
}

const STATUS_CONFIG: Record<string, { color: string; bg: string; border: string; icon: React.ReactNode; label: string }> = {
  completed: {
    color: '#16A34A',
    bg: '#F0FDF4',
    border: '#BBF7D0',
    icon: <CheckCircleOutlined />,
    label: '已完成',
  },
  failed: {
    color: '#DC2626',
    bg: '#FEF2F2',
    border: '#FECACA',
    icon: <CloseCircleOutlined />,
    label: '失败',
  },
  running: {
    color: '#2563EB',
    bg: '#EFF6FF',
    border: '#BFDBFE',
    icon: <SyncOutlined spin />,
    label: '执行中',
  },
  pending: {
    color: '#D97706',
    bg: '#FFFBEB',
    border: '#FDE68A',
    icon: <ClockCircleOutlined />,
    label: '等待执行',
  },
}

function formatOutput(output: unknown): string {
  if (output == null) return ''
  if (typeof output === 'string') return output
  try {
    return JSON.stringify(output, null, 2)
  } catch {
    return String(output)
  }
}

export default function TaskResultCard({ data }: TaskResultCardProps) {
  const cfg = STATUS_CONFIG[data.status] ?? STATUS_CONFIG.pending

  return (
    <div className="rounded-lg border overflow-hidden" style={{ borderColor: cfg.border, background: cfg.bg }}>
      {/* Header */}
      <div className="flex items-center gap-2 px-4 py-3 border-b" style={{ borderColor: cfg.border }}>
        <span style={{ color: cfg.color, fontSize: 14 }}>{cfg.icon}</span>
        <span className="text-sm font-semibold" style={{ color: cfg.color }}>任务 {cfg.label}</span>
      </div>

      {/* Body */}
      <div className="px-4 py-3 space-y-2">
        <div className="flex items-center gap-2">
          <Text type="secondary" className="text-xs">Task ID:</Text>
          <Text className="text-xs font-mono text-gray-700">{data.task_id}</Text>
        </div>

        <div className="flex items-center gap-2">
          <Text type="secondary" className="text-xs">状态:</Text>
          <Tag color={cfg.color.replace('#', '')} className="text-xs">{cfg.label}</Tag>
        </div>

        {/* Completed: show output */}
        {data.status === 'completed' && data.output && (
          <div>
            <Text type="secondary" className="text-xs">输出结果:</Text>
            <Paragraph className="text-xs text-gray-700 mt-0.5 mb-0 bg-white/70 rounded p-2 border" style={{ borderColor: cfg.border }}>
              {formatOutput(data.output)}
            </Paragraph>
          </div>
        )}

        {/* Failed: show error */}
        {data.status === 'failed' && data.error && (
          <div>
            <Text type="secondary" className="text-xs">错误信息:</Text>
            <Paragraph className="text-xs text-red-600 mt-0.5 mb-0 bg-red-50 rounded p-2 border" style={{ borderColor: '#FECACA' }}>
              {data.error}
            </Paragraph>
          </div>
        )}
      </div>
    </div>
  )
}
