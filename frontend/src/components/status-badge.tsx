/**
 * Status badge component — semantic color tags aligned with DESIGN.md Indigo palette.
 *
 * Usage:
 *   <StatusBadge status="published" />
 *   <StatusBadge status="running" showIcon />
 */
import { Tag, Spin } from 'antd'
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  WarningOutlined,
} from '@ant-design/icons'

export type AgentStatus =
  | 'draft'
  | 'published'
  | 'running'
  | 'success'
  | 'failed'
  | 'warning'
  | 'ai-processing'

const STATUS_CONFIG: Record<
  AgentStatus,
  { label: string; color: string; bg: string; border: string; icon?: React.ReactNode }
> = {
  draft: {
    label: '草稿',
    color: '#94A3B8',
    bg: '#FFFFFF',
    border: '#E2E8F0',
  },
  published: {
    label: '已发布',
    color: '#10B981',
    bg: '#D1FAE5',
    border: '#10B981',
    icon: <CheckCircleOutlined />,
  },
  running: {
    label: '执行中...',
    color: '#4F46E5',
    bg: '#EEF2FF',
    border: '#4F46E5',
  },
  success: {
    label: '成功',
    color: '#10B981',
    bg: '#D1FAE5',
    border: '#10B981',
    icon: <CheckCircleOutlined />,
  },
  failed: {
    label: '失败',
    color: '#EF4444',
    bg: '#FEE2E2',
    border: '#EF4444',
    icon: <CloseCircleOutlined />,
  },
  warning: {
    label: '嵌套深度警告',
    color: '#F59E0B',
    bg: '#FEF3C7',
    border: '#F59E0B',
    icon: <WarningOutlined />,
  },
  'ai-processing': {
    label: 'AI 思考中',
    color: '#06B6D4',
    bg: '#ECFEFF',
    border: '#06B6D4',
  },
}

interface StatusBadgeProps {
  status: AgentStatus | string
  showIcon?: boolean
}

export function StatusBadge({ status, showIcon = true }: StatusBadgeProps) {
  const config = STATUS_CONFIG[status as AgentStatus]

  if (!config) {
    return (
      <Tag className="!text-xs !px-2 !py-0.5 !rounded-sm">
        {status}
      </Tag>
    )
  }

  return (
    <Tag
      className="!text-xs !px-2 !py-0.5 !rounded-sm inline-flex items-center gap-1"
      style={{
        color: config.color,
        backgroundColor: config.bg,
        borderColor: config.border,
      }}
    >
      {status === 'running' || status === 'ai-processing' ? (
        <Spin size="small" className="!mr-0.5" />
      ) : showIcon && config.icon ? (
        <span className="!mr-0.5">{config.icon}</span>
      ) : null}
      {config.label}
    </Tag>
  )
}
