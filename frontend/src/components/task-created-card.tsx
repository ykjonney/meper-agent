/**
 * TaskCreatedCard — 任务创建成功卡片
 *
 * 当 LLM 调用 dispatch_workflow 后，后端返回 {type: "task_created", ...}
 * 前端检测后渲染此卡片显示创建结果。
 */
import { Tag, Typography } from 'antd'
import { CheckCircleOutlined, SyncOutlined, UserOutlined } from '@ant-design/icons'

const { Text } = Typography

export interface TaskCreated {
  type: 'task_created'
  task_id: string
  workflow_id: string
  workflow_name: string
  workflow_description?: string
  status: string
  has_human_node: boolean
  message: string
}

interface TaskCreatedCardProps {
  data: TaskCreated
}

const STATUS_MAP: Record<string, { color: string; icon: React.ReactNode; label: string }> = {
  pending: { color: 'orange', icon: <SyncOutlined />, label: '等待执行' },
  running: { color: 'processing', icon: <SyncOutlined spin />, label: '执行中' },
  completed: { color: 'success', icon: <CheckCircleOutlined />, label: '已完成' },
  failed: { color: 'error', icon: <></>, label: '失败' },
}

export default function TaskCreatedCard({ data }: TaskCreatedCardProps) {
  const statusInfo = STATUS_MAP[data.status] ?? { color: 'default', icon: null, label: data.status }

  return (
    <div className="rounded-lg border border-green-200 bg-green-50/60 overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-2 px-4 py-3 border-b border-green-100">
        <CheckCircleOutlined className="text-green-500 text-base" />
        <span className="text-sm font-semibold text-green-700">工作流已触发</span>
      </div>

      {/* Body */}
      <div className="px-4 py-3 space-y-2">
        <div className="flex items-center gap-2">
          <Text type="secondary" className="text-xs">工作流:</Text>
          <Tag color="green" className="text-xs">{data.workflow_name}</Tag>
        </div>

        <div className="flex items-center gap-2">
          <Text type="secondary" className="text-xs">Task ID:</Text>
          <Text className="text-xs font-mono text-gray-700">{data.task_id}</Text>
        </div>

        <div className="flex items-center gap-2">
          <Text type="secondary" className="text-xs">状态:</Text>
          <Tag color={statusInfo.color} className="text-xs">
            {statusInfo.icon}
            <span className="ml-1">{statusInfo.label}</span>
          </Tag>
        </div>

        {data.has_human_node && (
          <div className="flex items-center gap-1.5">
            <UserOutlined className="text-amber-500 text-xs" />
            <Text className="text-[10px] text-amber-600">该工作流包含人工审批节点</Text>
          </div>
        )}

        <Text className="text-xs text-gray-500 block">{data.message}</Text>
      </div>
    </div>
  )
}
