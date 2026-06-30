/**
 * TaskResultCard — 任务结果卡片
 *
 * 当 LLM 调用 task_query 后，后端返回 {type: "task_result", status, output, error}
 * 前端检测后渲染此卡片显示任务执行结果。
 */
import { useEffect, useState } from 'react'
import { Button, Tag, Typography } from 'antd'
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  EyeOutlined,
  FileOutlined,
  SyncOutlined,
  ClockCircleOutlined,
} from '@ant-design/icons'
import { tasksApi, type TaskOutputFile } from '../services/tasks-api'
import FileDownloadButton from './file-download-button'
import FilePreview from './file-preview'
import { getPreviewKind } from '../lib/file-preview'

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

        {/* Story 4-15-UI: 输出文件列表（Agent 节点产物） */}
        {data.status === 'completed' && (
          <TaskOutputFiles taskId={data.task_id} />
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

/**
 * TaskOutputFiles — 列出 task 的输出文件，每项支持就地折叠预览。
 *
 * 仅在 status === 'completed' 时由父组件渲染（此处不重复判断）。
 * Story 4-15-UI
 */
export function TaskOutputFiles({ taskId }: { taskId: string }) {
  const [files, setFiles] = useState<TaskOutputFile[]>([])
  const [loading, setLoading] = useState(true)
  const [expandedId, setExpandedId] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    const run = async () => {
      try {
        const list = await tasksApi.listOutputs(taskId)
        if (!cancelled) setFiles(list)
      } catch (err) {
        console.error('[list_task_outputs]', err)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    void run()
    return () => {
      cancelled = true
    }
  }, [taskId])

  // loading 中不渲染（避免空白闪烁）；列表为空也不渲染（避免视觉噪音）
  if (loading) {
    return (
      <div className="mt-1">
        <Text type="secondary" className="text-xs">
          <SyncOutlined spin className="mr-1" />
          加载输出文件…
        </Text>
      </div>
    )
  }

  if (files.length === 0) return null

  return (
    <div className="mt-1">
      <Text type="secondary" className="text-xs">
        输出文件 ({files.length}):
      </Text>
      <ul className="mt-1 space-y-1">
        {files.map(f => {
          const previewable = getPreviewKind(f.mime_type) !== 'none'
          const expanded = expandedId === f._id
          return (
            <li
              key={f._id}
              className="bg-white/70 rounded p-1.5 border"
              style={{ borderColor: '#E5E7EB' }}
            >
              <div className="flex items-center gap-2 text-xs">
                <FileOutlined style={{ color: '#6B7280' }} />
                <span
                  className="flex-1 truncate text-gray-700"
                  title={f.name}
                >
                  {f.name}
                </span>
                <span className="text-gray-400">{formatSize(f.size)}</span>
                {previewable && (
                  <Button
                    size="small"
                    type="text"
                    icon={<EyeOutlined />}
                    onClick={() =>
                      setExpandedId(expanded ? null : f._id)
                    }
                  >
                    {expanded ? '收起' : '预览'}
                  </Button>
                )}
                <FileDownloadButton fileId={f._id} filename={f.name} />
              </div>
              {expanded && (
                <div className="mt-1">
                  <FilePreview
                    fileId={f._id}
                    filename={f.name}
                    mime={f.mime_type}
                  />
                </div>
              )}
            </li>
          )
        })}
      </ul>
    </div>
  )
}

/** 本地小工具 — 字节数转人类可读字符串 */
function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}
