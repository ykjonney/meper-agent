/**
 * Task board page — 6 列并排的全状态看板。
 *
 * 设计要点：
 * - 6 列状态分桶：pending / running / waiting_human / completed / failed / cancelled
 * - 列表查询：useQueries 并发发起 6 次 list（按 status，page=1, page_size=50）
 * - 节点进度：仅对 running / waiting_human 两列拉详情（5 秒轮询，上限 20 个）
 * - 详情查询与详情 Drawer 共用 taskKeys.detail(id) 缓存
 * - 搜索改为纯前端过滤（task.id / workflow_id includes）
 */
import { useState, useMemo, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient, useQueries } from '@tanstack/react-query'
import { Button, Tag, message, Spin, Modal, Drawer, Input, Empty, Alert } from 'antd'
import {
  StopOutlined,
  RedoOutlined,
  DeleteOutlined,
  SearchOutlined,
  PlusOutlined,
  CheckCircleOutlined,
  WarningOutlined,
  ThunderboltOutlined,
  CloseCircleOutlined,
  CheckOutlined,
} from '@ant-design/icons'
import { useTheme } from '../contexts/ThemeContext'
import {
  tasksApi,
  taskKeys,
  type TaskSummary,
  type TaskStatusValue,
  type TaskDetail,
  type NodeProgress,
  BOARD_STATUSES,
  parseNodeProgress,
} from '../services/tasks-api'
import { TASK_STATUS_STYLES } from '../constants/task-status'
import { TaskBoardColumn } from '../components/task-board-column'
import { APPROVAL_ACCENT } from '../components/task-board-card'
import { parseBackendDate } from '../lib/format'

/* ─── helpers ─── */
function useDebouncedValue<T>(value: T, delay: number): T {
  const [debounced, setDebounced] = useState(value)
  useMemo(() => {
    const id = setTimeout(() => setDebounced(value), delay)
    return () => clearTimeout(id)
  }, [value, delay])
  return debounced
}

function formatDateTime(iso: string) {
  if (!iso) return '-'
  return parseBackendDate(iso).toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/* ─── active 状态集合：需要拉详情以展示节点进度 ─── */
const ACTIVE_STATUSES: TaskStatusValue[] = ['running', 'waiting_human']
/* 进度展示的任务上限，避免请求风暴 */
const MAX_PROGRESS_TASKS = 20

export default function TasksPage() {
  const { t } = useTheme()
  const queryClient = useQueryClient()

  /* ─── Search state（纯前端过滤） ─── */
  const [searchInput, setSearchInput] = useState('')
  const debouncedSearch = useDebouncedValue(searchInput.toLowerCase(), 200)

  /* ─── Create modal state ─── */
  const [createOpen, setCreateOpen] = useState(false)
  const [selectedWorkflowId, setSelectedWorkflowId] = useState<string>('')
  const [createInput, setCreateInput] = useState('')
  const [workflowSearch, setWorkflowSearch] = useState('')
  const debouncedWorkflowSearch = useDebouncedValue(workflowSearch, 300)

  /* ─── Detail drawer state ─── */
  const [detailTaskId, setDetailTaskId] = useState<string | null>(null)

  /* ─── Approval modal state ─── */
  const [approvalAction, setApprovalAction] = useState<'approve' | 'reject' | null>(null)
  const [approvalReason, setApprovalReason] = useState('')
  const [approvalTask, setApprovalTask] = useState<TaskSummary | TaskDetail | null>(null)

  /* ─── 6 列并发列表查询（按 status 分桶） ─── */
  const boardQueries = useQueries({
    queries: BOARD_STATUSES.map((status) => ({
      queryKey: taskKeys.list({ status, page: 1, page_size: 50 }),
      queryFn: () => tasksApi.list({ status, page: 1, page_size: 50 }),
      refetchInterval: 5_000,
    })),
  })

  // 按 status 索引结果
  const tasksByStatus = useMemo(() => {
    const map: Record<TaskStatusValue, TaskSummary[]> = {
      pending: [],
      running: [],
      waiting_human: [],
      completed: [],
      failed: [],
      cancelled: [],
    }
    BOARD_STATUSES.forEach((status, idx) => {
      const result = boardQueries[idx]
      map[status] = (result?.data?.items ?? []) as TaskSummary[]
    })
    return map
  }, [boardQueries])

  const boardLoading = boardQueries.some((q) => q.isLoading)

  /* ─── 收集 active 任务，批量拉详情（5s 轮询，上限 20 个） ─── */
  const activeTasksForDetail = useMemo(() => {
    const collected: TaskSummary[] = []
    for (const status of ACTIVE_STATUSES) {
      for (const task of tasksByStatus[status]) {
        if (collected.length >= MAX_PROGRESS_TASKS) break
        collected.push(task)
      }
      if (collected.length >= MAX_PROGRESS_TASKS) break
    }
    return collected
  }, [tasksByStatus])

  const activeDetailQueries = useQueries({
    queries: activeTasksForDetail.map((task) => ({
      queryKey: taskKeys.detail(task.id),
      queryFn: () => tasksApi.get(task.id),
      refetchInterval: 5_000,
      staleTime: 3_000,
    })),
  })

  /* ─── 组装进度 map ─── */
  const progressMap = useMemo(() => {
    const map: Record<string, NodeProgress | null | undefined> = {}
    activeTasksForDetail.forEach((task, idx) => {
      const detail = activeDetailQueries[idx]?.data
      if (detail) {
        map[task.id] = parseNodeProgress(detail.timeline)
      }
    })
    return map
  }, [activeTasksForDetail, activeDetailQueries])

  /* ─── Workflow list query (for create modal) ─── */
  const { data: workflowsData, isLoading: workflowsLoading } = useQuery({
    queryKey: [...taskKeys.workflows(), debouncedWorkflowSearch],
    queryFn: () => tasksApi.listWorkflows(debouncedWorkflowSearch || undefined),
    enabled: createOpen,
  })
  const workflows = workflowsData?.items ?? []

  /* ─── Workflow 名称映射（看板卡片用，始终启用） ─── */
  const { data: allWorkflowsData } = useQuery({
    queryKey: [...taskKeys.workflows(), 'board-map'],
    queryFn: () => tasksApi.listWorkflows(),
    staleTime: 60_000,
  })
  const workflowNameMap = useMemo(() => {
    const map: Record<string, string> = {}
    for (const wf of allWorkflowsData?.items ?? []) {
      map[wf.workflow_id] = wf.name
    }
    return map
  }, [allWorkflowsData])

  /* ─── Detail query（Drawer 使用，与卡片共用 detail 缓存） ─── */
  const { data: taskDetail, isLoading: detailLoading } = useQuery({
    queryKey: taskKeys.detail(detailTaskId ?? ''),
    queryFn: () => tasksApi.get(detailTaskId!),
    enabled: !!detailTaskId,
    refetchInterval: (query) => {
      const task = query.state.data
      if (task?.status === 'running' || task?.status === 'pending' || task?.status === 'waiting_human') {
        return 5_000
      }
      return false
    },
  })

  /* ─── Selected workflow schema ─── */
  const selectedWorkflow = workflows.find((w) => w._id === selectedWorkflowId)
  const inputSchema = selectedWorkflow?.input_schema ?? {}
  const schemaKeys = Object.keys(inputSchema as Record<string, unknown>)

  /* ─── Mutation: create task ─── */
  const createMutation = useMutation({
    mutationFn: (data: { workflow_id: string; input: Record<string, unknown> }) =>
      tasksApi.create(data),
    onSuccess: () => {
      message.success('任务创建成功')
      queryClient.invalidateQueries({ queryKey: taskKeys.lists() })
      setCreateOpen(false)
      setSelectedWorkflowId('')
      setCreateInput('')
    },
    onError: (err: unknown) => {
      const msg = err && typeof err === 'object' && 'message' in err
        ? (err as { message: string }).message : '创建失败'
      message.error(msg)
    },
  })

  /* ─── Mutation: intervene (cancel / retry / approve / reject) ─── */
  const interveneMutation = useMutation({
    mutationFn: ({ taskId, action, version, comment, reason }: { taskId: string; action: string; version: number; comment?: string; reason?: string }) =>
      tasksApi.intervene(taskId, { action, version, comment, reason }),
    onSuccess: () => {
      message.success('操作成功')
      queryClient.invalidateQueries({ queryKey: taskKeys.lists() })
      if (detailTaskId) {
        queryClient.invalidateQueries({ queryKey: taskKeys.detail(detailTaskId) })
      }
    },
    onError: (err: unknown) => {
      const msg = err && typeof err === 'object' && 'message' in err
        ? (err as { message: string }).message : '操作失败'
      message.error(msg)
    },
  })

  /* ─── Mutation: delete task ─── */
  const deleteMutation = useMutation({
    mutationFn: tasksApi.remove,
    onSuccess: () => {
      message.success('任务已删除')
      queryClient.invalidateQueries({ queryKey: taskKeys.lists() })
      if (detailTaskId) {
        queryClient.invalidateQueries({ queryKey: taskKeys.detail(detailTaskId) })
      }
    },
    onError: (err: unknown) => {
      const msg = err && typeof err === 'object' && 'message' in err
        ? (err as { message: string }).message : '删除失败'
      message.error(msg)
    },
  })

  /* ─── Actions ─── */
  const handleCreate = () => {
    setSelectedWorkflowId('')
    setCreateInput('{}')
    setWorkflowSearch('')
    setCreateOpen(true)
  }

  const handleCreateSubmit = () => {
    if (!selectedWorkflowId) {
      message.warning('请选择工作流')
      return
    }
    let parsedInput: Record<string, unknown>
    try {
      parsedInput = JSON.parse(createInput || '{}')
    } catch {
      message.warning('请输入有效的 JSON 格式输入参数')
      return
    }
    createMutation.mutate({ workflow_id: selectedWorkflowId, input: parsedInput })
  }

  const handleCancel = useCallback((task: TaskSummary) => {
    Modal.confirm({
      title: '确认取消',
      content: `确定要取消任务「${task.id}」吗？`,
      okText: '取消任务',
      okButtonProps: { danger: true },
      cancelText: '关闭',
      onOk: () => interveneMutation.mutate({ taskId: task.id, action: 'cancel', version: task.version }),
    })
  }, [interveneMutation])

  const handleRetry = useCallback((task: TaskSummary) => {
    Modal.confirm({
      title: '确认重试',
      content: `确定要重试任务「${task.id}」吗？`,
      okText: '重试',
      cancelText: '关闭',
      onOk: () => interveneMutation.mutate({ taskId: task.id, action: 'retry', version: task.version }),
    })
  }, [interveneMutation])

  const handleApprove = useCallback((task: TaskSummary | TaskDetail) => {
    setApprovalAction('approve')
    setApprovalTask(task)
    setApprovalReason('')
  }, [])

  const handleReject = useCallback((task: TaskSummary | TaskDetail) => {
    setApprovalAction('reject')
    setApprovalTask(task)
    setApprovalReason('')
  }, [])

  const handleApprovalConfirm = useCallback(() => {
    if (!approvalAction || !approvalTask) return
    interveneMutation.mutate({
      taskId: approvalTask.id,
      action: approvalAction,
      version: approvalTask.version,
      comment: approvalReason || undefined,
    })
    setApprovalAction(null)
    setApprovalTask(null)
    setApprovalReason('')
  }, [approvalAction, approvalTask, approvalReason, interveneMutation])

  /**
   * 看板卡片快速审批入口（BOARD_CARD_QUICK_APPROVE / BOARD_CARD_QUICK_REJECT）。
   * 父级统一处理 interveneMutation，TaskBoardCard 不直接调 API。
   */
  const handleBoardApproval = useCallback(
    (task: TaskSummary, action: 'approve' | 'reject', comment: string) => {
      interveneMutation.mutate({
        taskId: task.id,
        action,
        version: task.version,
        comment,
      })
    },
    [interveneMutation],
  )

  const handleApprovalCancel = useCallback(() => {
    setApprovalAction(null)
    setApprovalTask(null)
    setApprovalReason('')
  }, [])

  const handleDelete = useCallback((task: TaskSummary) => {
    Modal.confirm({
      title: '确认删除',
      content: `确定要删除任务「${task.id}」吗？此操作不可恢复。`,
      okText: '删除',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: () => deleteMutation.mutate(task.id),
    })
  }, [deleteMutation])

  const handleCardClick = useCallback((task: TaskSummary) => {
    setDetailTaskId(task.id)
  }, [])

  /* ─── 顶部紧凑统计卡（4 张） ─── */
  const runningCount = tasksByStatus.running.length
  const waitingHumanCount = tasksByStatus.waiting_human.length
  const completedCount = tasksByStatus.completed.length
  const failedCount = tasksByStatus.failed.length

  const statCards = [
    { label: '运行中', value: runningCount, color: '#2563EB', bg: '#DBEAFE', icon: <ThunderboltOutlined /> },
    { label: '等待人工', value: waitingHumanCount, color: '#8B5CF6', bg: '#EDE9FE', icon: <WarningOutlined /> },
    { label: '已完成', value: completedCount, color: '#10B981', bg: '#D1FAE5', icon: <CheckCircleOutlined /> },
    { label: '已失败', value: failedCount, color: '#EF4444', bg: '#FEE2E2', icon: <CloseCircleOutlined /> },
  ]

  /* ─── 过滤函数（前端 includes 匹配） ─── */
  const filterTasks = useCallback((tasks: TaskSummary[]) => {
    if (!debouncedSearch) return tasks
    return tasks.filter(
      (task) =>
        task.id.toLowerCase().includes(debouncedSearch) ||
        task.workflow_id.toLowerCase().includes(debouncedSearch),
    )
  }, [debouncedSearch])

  return (
    <div className="flex flex-col h-full">
      {/* ─── 顶部统计条 ─── */}
      <div className="grid grid-cols-4 gap-3 mb-4">
        {statCards.map((s) => (
          <div
            key={s.label}
            className="bg-white rounded-xl border border-gray-200 p-3 flex items-center gap-3"
          >
            <div
              className="w-9 h-9 rounded-lg flex items-center justify-center text-base"
              style={{ background: s.bg, color: s.color }}
            >
              {s.icon}
            </div>
            <div className="min-w-0">
              <div className="text-xl font-semibold text-[#0F172A] leading-tight">{s.value}</div>
              <div className="text-[11px] text-[#64748B]">{s.label}</div>
            </div>
          </div>
        ))}
      </div>

      {/* ─── 工具栏：搜索 + 新建 ─── */}
      <div className="flex items-center justify-between gap-3 mb-4">
        <div className="relative">
          <SearchOutlined className="absolute left-3 top-1/2 -translate-y-1/2 text-[#94A3B8] text-sm" />
          <input
            type="text"
            placeholder="搜索任务 ID 或工作流 ID..."
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            className="pl-9 pr-4 py-2 rounded-lg border border-gray-200 text-sm focus:outline-none focus:ring-2 w-80"
            style={{ ['--tw-ring-color' as string]: t.bg }}
          />
        </div>
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={handleCreate}
        >
          新建任务
        </Button>
      </div>

      {/* ─── 6 列看板（横向滚动，列内垂直滚动） ─── */}
      {boardLoading ? (
        <div className="flex items-center justify-center py-20">
          <Spin size="large" />
        </div>
      ) : (
        <div className="flex gap-4 overflow-x-auto pb-2 flex-1 min-h-0" style={{ height: 'calc(100vh - 220px)' }}>
          {BOARD_STATUSES.map((status) => {
            const style = TASK_STATUS_STYLES[status]
            const filtered = filterTasks(tasksByStatus[status])
            return (
              <TaskBoardColumn
                key={status}
                style={style}
                tasks={filtered}
                progressMap={progressMap}
                workflowNameMap={workflowNameMap}
                loading={false}
                onCardClick={handleCardClick}
                onCancel={handleCancel}
                onRetry={handleRetry}
                onDelete={handleDelete}
                onApprovalSubmit={handleBoardApproval}
                interveneLoading={interveneMutation.isPending}
                deleteLoading={deleteMutation.isPending}
              />
            )
          })}
        </div>
      )}

      {/* ─── Create Task Modal ─── */}
      <Modal
        title="新建任务"
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        onOk={handleCreateSubmit}
        okText="创建"
        cancelText="取消"
        confirmLoading={createMutation.isPending}
        okButtonProps={{ disabled: !selectedWorkflowId }}
        destroyOnClose
        width={560}
      >
        <div className="flex flex-col gap-4 py-2">
          {/* Workflow selector */}
          <div>
            <label className="block text-sm text-[#0F172A] mb-1.5">
              选择工作流 <span className="text-[#EF4444]">*</span>
            </label>
            <Input
              placeholder="搜索工作流..."
              value={workflowSearch}
              onChange={(e) => setWorkflowSearch(e.target.value)}
              className="mb-2"
              prefix={<SearchOutlined className="text-[#94A3B8]" />}
              allowClear
            />
            <div className="max-h-48 overflow-y-auto border border-gray-200 rounded-lg">
              {workflowsLoading ? (
                <div className="flex items-center justify-center py-8"><Spin size="small" /></div>
              ) : workflows.length === 0 ? (
                <div className="text-center py-8 text-sm text-[#94A3B8]">暂无已发布的工作流</div>
              ) : (
                workflows.map((wf) => (
                  <div
                    key={wf._id}
                    onClick={() => setSelectedWorkflowId(wf._id)}
                    className={`px-3 py-2.5 cursor-pointer border-b border-gray-50 last:border-b-0 transition-colors ${
                      selectedWorkflowId === wf._id ? 'bg-[#EFF6FF]' : 'hover:bg-[#F8FAFC]'
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <span className={`text-sm ${selectedWorkflowId === wf._id ? 'font-medium text-[#1E5EFF]' : 'text-[#0F172A]'}`}>
                        {wf.name}
                      </span>
                      {wf.has_human_node && (
                        <Tag className="!m-0 !text-[10px] !px-1.5 !py-0" color="orange">需审批</Tag>
                      )}
                    </div>
                    <div className="text-[11px] text-[#94A3B8] mt-0.5 truncate">{wf.description}</div>
                  </div>
                ))
              )}
            </div>
          </div>

          {/* Input schema fields */}
          {selectedWorkflow && schemaKeys.length > 0 && (
            <div>
              <label className="block text-sm text-[#0F172A] mb-1.5">
                输入参数 <span className="text-[#94A3B8] font-normal">(JSON)</span>
              </label>
              <div className="mb-2 flex flex-wrap gap-1.5">
                {schemaKeys.map((key) => {
                  const schema = (inputSchema as Record<string, unknown>)[key] as Record<string, unknown> | undefined
                  return (
                    <Tag key={key} className="!m-0 !text-[11px]" color="default">
                      {key}{schema?.required ? <span className="text-[#EF4444] ml-0.5">*</span> : null}
                      <span className="text-[#94A3B8] ml-1">{(schema?.type as string) ?? 'string'}</span>
                    </Tag>
                  )
                })}
              </div>
              <Input.TextArea
                value={createInput}
                onChange={(e) => setCreateInput(e.target.value)}
                placeholder='{"key": "value"}'
                rows={4}
                className="font-mono text-sm"
              />
            </div>
          )}

          {selectedWorkflow && schemaKeys.length === 0 && (
            <div>
              <label className="block text-sm text-[#0F172A] mb-1.5">输入参数</label>
              <Input.TextArea
                value={createInput}
                onChange={(e) => setCreateInput(e.target.value)}
                placeholder='{"key": "value"}（可选）'
                rows={3}
                className="font-mono text-sm"
              />
            </div>
          )}
        </div>
      </Modal>

      {/* ─── Task Detail Drawer ─── */}
      <Drawer
        title={detailLoading ? '加载中...' : `任务详情`}
        open={!!detailTaskId}
        onClose={() => setDetailTaskId(null)}
        width={520}
        extra={
          taskDetail && (
            <Tag className="!m-0" style={{ color: TASK_STATUS_STYLES[taskDetail.status]?.color, background: TASK_STATUS_STYLES[taskDetail.status]?.bg, borderColor: 'transparent' }}>
              {TASK_STATUS_STYLES[taskDetail.status]?.icon} {TASK_STATUS_STYLES[taskDetail.status]?.label}
            </Tag>
          )
        }
      >
        {detailLoading && (
          <div className="flex items-center justify-center py-20"><Spin size="large" /></div>
        )}

        {!detailLoading && taskDetail && (
          <div className="flex flex-col gap-5">
            {/* Basic info */}
            <section>
              <h4 className="text-xs font-medium text-[#94A3B8] uppercase tracking-wider mb-3">基本信息</h4>
              <div className="space-y-2.5">
                <InfoRow label="ID" value={taskDetail.id} mono />
                <InfoRow label="工作流" value={workflowNameMap[taskDetail.workflow_id] ?? taskDetail.workflow_id} />
                <InfoRow label="创建者" value={taskDetail.created_by || '系统'} />
                <InfoRow label="版本" value={`v${taskDetail.version}`} />
                <InfoRow label="创建时间" value={parseBackendDate(taskDetail.created_at).toLocaleString('zh-CN')} />
                <InfoRow label="更新时间" value={parseBackendDate(taskDetail.updated_at).toLocaleString('zh-CN')} />
              </div>
            </section>

            {/* 输入参数 + 错误信息 */}
            <section>
              <h4 className="text-xs font-medium text-[#94A3B8] uppercase tracking-wider mb-3">输入参数</h4>
              <div className="space-y-1.5">
                {(() => {
                  const inp = taskDetail.input ?? {}
                  const entries = Object.entries(inp)
                  if (entries.length === 0) return <div className="text-xs text-[#94A3B8] italic">无</div>
                  return entries.map(([k, v]) => (
                    <div key={k} className="flex gap-2 text-xs">
                      <span className="text-[#64748B] font-medium shrink-0 min-w-[80px]">{k}</span>
                      <span className="text-[#0F172A] break-all">
                        {typeof v === 'string' ? v : JSON.stringify(v)}
                      </span>
                    </div>
                  ))
                })()}
              </div>
              {taskDetail.error && (
                <Alert
                  type="error"
                  showIcon
                  message="执行错误"
                  description={`[${taskDetail.error.error_code}] ${taskDetail.error.error_message}`}
                  className="mt-3"
                />
              )}
            </section>

            {/* 执行流程 */}
            <section>
              <h4 className="text-xs font-medium text-[#94A3B8] uppercase tracking-wider mb-3">
                执行流程 <span className="font-normal">({taskDetail.timeline?.length ?? 0})</span>
              </h4>
              {taskDetail.timeline && taskDetail.timeline.length > 0 ? (
                (() => {
                  const timeline = taskDetail.timeline!
                  // 过滤：如果时间线中存在任何审批完成事件，说明所有 waiting_human 都已解决，全部隐藏
                  const approveTypes = new Set([
                    'approve', 'skip', 'reject', 'cancel', 'resume',  // UI API (tasks.py)
                    'intervene_approve', 'intervene_reject', 'intervene_cancel', 'intervene_resume',  // Agent 工具
                    'human_approved', 'human_rejected',  // 引擎内部
                  ])
                  const hasAnyApproval = timeline.some(e => approveTypes.has(e.event_type))
                  const filtered = timeline.filter(e => {
                    // 审批已完成 → 隐藏所有 waiting_human
                    if (hasAnyApproval && e.event_type === 'waiting_human') return false
                    // 人工审批节点的 node_complete 只是引擎恢复信号，审批事件已覆盖
                    if (e.event_type === 'node_complete' && e.data?.node_type === 'human') return false
                    return true
                  })

                  // 节点类型 → 中文标签
                  const nodeTypeLabel: Record<string, string> = {
                    start: '输入节点', end: '输出节点', agent: 'Agent 节点',
                    tool: '工具节点', gateway: '网关节点', parallel: '并行节点', human: '人工审批节点',
                  }
                  // 事件类型 → 中文标签 + 颜色
                  const eventMeta: Record<string, { label: string; color: string }> = {
                    // ── 生命周期 ──
                    created:           { label: '任务创建',   color: '#1E5EFF' },
                    started:           { label: '开始执行',   color: '#1E5EFF' },
                    auto_scheduled:    { label: '自动调度',   color: '#1E5EFF' },
                    completed:         { label: '任务完成',   color: '#10B981' },
                    failed:            { label: '任务失败',   color: '#EF4444' },
                    task_failed:       { label: '任务失败',   color: '#EF4444' },
                    cancelled:         { label: '任务取消',   color: '#94A3B8' },
                    // ── 节点执行 ──
                    node_start:        { label: '节点开始',   color: '#1E5EFF' },
                    node_complete:     { label: '节点完成',   color: '#10B981' },
                    node_failed:       { label: '节点失败',   color: '#EF4444' },
                    // ── 人工审批（UI API） ──
                    waiting_human:     { label: '等待审批',   color: '#8B5CF6' },
                    human_node_start:  { label: '审批开始',   color: '#8B5CF6' },
                    approve:           { label: '审批通过',   color: '#10B981' },
                    skip:              { label: '审批跳过',   color: '#F59E0B' },
                    reject:            { label: '审批驳回',   color: '#EF4444' },
                    cancel:            { label: '人工取消',   color: '#94A3B8' },
                    resume:            { label: '人工恢复',   color: '#1E5EFF' },
                    // ── 人工干预（Agent 工具） ──
                    human_approved:    { label: '审批通过',   color: '#10B981' },
                    human_rejected:    { label: '审批拒绝',   color: '#EF4444' },
                    intervene_approve: { label: '人工通过',   color: '#10B981' },
                    intervene_reject:  { label: '人工拒绝',   color: '#EF4444' },
                    intervene_cancel:  { label: '人工取消',   color: '#EF4444' },
                    intervene_resume:  { label: '人工恢复',   color: '#1E5EFF' },
                    intervene_retry:    { label: '人工重试',   color: '#F59E0B' },
                  }

                  return (
                    <div className="relative pl-7">
                      {/* 连续连接线 */}
                      <div className="absolute left-[9px] top-2 bottom-2 w-[2px] bg-[#E2E8F0]" />
                      {filtered.map((evt, idx) => {
                        const meta = eventMeta[evt.event_type] ?? { label: evt.event_type, color: '#94A3B8' }

                        // 节点事件：拼接类型前缀 → "Agent 节点开始" / "输入节点完成"
                        const nodeType = evt.data?.node_type as string | undefined
                        const isNodeEvent = !!nodeType && (
                          evt.event_type === 'node_start' ||
                          evt.event_type === 'node_complete' ||
                          evt.event_type === 'node_failed'
                        )
                        const displayLabel = isNodeEvent
                          ? `${nodeTypeLabel[nodeType] ?? nodeType}${meta.label.replace('节点', '')}`
                          : meta.label

                        const hasData = Object.keys(evt.data ?? {}).length > 0

                        return (
                          <div key={idx} className="relative py-2">
                            {/* 时间轴圆点 */}
                            <div
                              className="absolute -left-7 top-2.5 w-[14px] h-[14px] rounded-full border-2 border-white shadow-sm z-10"
                              style={{ backgroundColor: meta.color }}
                            />
                            {/* 事件主体 */}
                            <div className="flex items-baseline gap-2 flex-wrap">
                              <span className="text-xs font-medium" style={{ color: meta.color }}>{displayLabel}</span>
                              <span className="text-[11px] text-[#94A3B8]">{formatDateTime(evt.timestamp)}</span>
                              {evt.actor && <span className="text-[11px] text-[#94A3B8]">· {evt.actor}</span>}
                            </div>
                            {/* 所有数据统一折叠 */}
                            {hasData && (
                              <details className="mt-1">
                                <summary className="text-[10px] text-[#94A3B8] cursor-pointer hover:text-[#1E5EFF] list-none flex items-center gap-1">
                                  <span className="text-[8px]">▶</span>
                                  详细数据
                                </summary>
                                <pre className="text-[10px] text-[#64748B] bg-[#F8FAFC] rounded p-2 mt-1 overflow-x-auto max-h-32">
                                  {JSON.stringify(evt.data, null, 2)}
                                </pre>
                              </details>
                            )}
                          </div>
                        )
                      })}
                    </div>
                  )
                })()
              ) : (
                <Empty description="暂无时间线事件" image={Empty.PRESENTED_IMAGE_SIMPLE} />
              )}
            </section>

            {/* Checkpoint / Human approval info（waiting_human 时显示） */}
            {taskDetail.status === 'waiting_human' && taskDetail.checkpoint && (
              <section>
                <h4 className="text-xs font-medium text-[#94A3B8] uppercase tracking-wider mb-3">
                  <WarningOutlined className="mr-1" style={{ color: '#8B5CF6' }} />
                  审批信息
                </h4>
                <div className="space-y-2.5">
                  {taskDetail.checkpoint.human_context?.title && (
                    <InfoRow label="审批标题" value={taskDetail.checkpoint.human_context.title} />
                  )}
                  {taskDetail.checkpoint.human_context?.description && (
                    <div>
                      <div className="text-xs text-[#64748B] mb-1">审批描述</div>
                      <div className="text-xs text-[#0F172A] bg-[#F8FAFC] rounded-lg p-3">
                        {taskDetail.checkpoint.human_context.description}
                      </div>
                    </div>
                  )}
                  {taskDetail.checkpoint.timeout_deadline && (
                    <InfoRow
                      label="超时截止"
                      value={`${parseBackendDate(taskDetail.checkpoint.timeout_deadline).toLocaleString('zh-CN')} (${taskDetail.checkpoint.timeout_action})`}
                    />
                  )}
                  {/* Upstream node outputs (exclude 'input' and the paused node itself) */}
                  {(() => {
                    const pausedNode = taskDetail.checkpoint.paused_at_node
                    const upstreamVars = Object.entries(taskDetail.variables ?? {})
                      .filter(([key]) => key !== 'input' && key !== pausedNode)
                    if (upstreamVars.length === 0) return null
                    return (
                      <div>
                        <div className="text-xs text-[#64748B] mb-1">上游节点输出</div>
                        <div className="max-h-48 overflow-y-auto space-y-2">
                          {upstreamVars.map(([key, value]) => (
                            <div key={key}>
                              <div className="text-[11px] text-[#94A3B8] font-medium">{key}</div>
                              <pre className="text-[10px] bg-[#F8FAFC] rounded p-2 overflow-x-auto text-[#0F172A]">
                                {JSON.stringify(value, null, 2)}
                              </pre>
                            </div>
                          ))}
                        </div>
                      </div>
                    )
                  })()}
                </div>
              </section>
            )}

            {/* Intervention actions（waiting_human 显示批准/驳回） */}
            <section>
              <h4 className="text-xs font-medium text-[#94A3B8] uppercase tracking-wider mb-3">操作</h4>
              <div className="flex items-center gap-2 flex-wrap">
                {taskDetail.status === 'running' && (
                  <Button
                    danger
                    icon={<StopOutlined />}
                    onClick={() => handleCancel(taskDetail)}
                    loading={interveneMutation.isPending}
                  >
                    取消任务
                  </Button>
                )}
                {taskDetail.status === 'waiting_human' && (
                  <div className="w-full flex flex-col gap-3">
                    <div className="flex items-center gap-2 flex-wrap">
                      <Button
                        type="primary"
                        icon={<CheckOutlined />}
                        onClick={() => handleApprove(taskDetail)}
                        loading={interveneMutation.isPending}
                        style={{ backgroundColor: APPROVAL_ACCENT, borderColor: APPROVAL_ACCENT }}
                      >
                        通过
                      </Button>
                      <Button
                        danger
                        icon={<CloseCircleOutlined />}
                        onClick={() => handleReject(taskDetail)}
                        loading={interveneMutation.isPending}
                      >
                        驳回
                      </Button>
                    </div>
                  </div>
                )}
                {taskDetail.status === 'failed' && (
                  <Button
                    type="primary"
                    icon={<RedoOutlined />}
                    onClick={() => handleRetry(taskDetail)}
                    loading={interveneMutation.isPending}
                  >
                    重试
                  </Button>
                )}
                {(taskDetail.status === 'completed' || taskDetail.status === 'failed' || taskDetail.status === 'cancelled') && (
                  <Button
                    danger
                    icon={<DeleteOutlined />}
                    onClick={() => handleDelete(taskDetail)}
                    loading={deleteMutation.isPending}
                  >
                    删除
                  </Button>
                )}
              </div>
            </section>
          </div>
        )}
      </Drawer>

      {/* ─── Approval Modal ─── */}
      <Modal
        title={
          approvalAction === 'approve'
            ? '批准任务'
            : approvalAction === 'reject'
              ? '驳回任务'
              : '审批操作'
        }
        open={!!approvalAction}
        onOk={handleApprovalConfirm}
        onCancel={handleApprovalCancel}
        okText={approvalAction === 'approve' ? '批准' : '驳回'}
        cancelText="取消"
        confirmLoading={interveneMutation.isPending}
        okButtonProps={approvalAction === 'reject' ? { danger: true } : {}}
        destroyOnClose
      >
        <div className="flex flex-col gap-3 py-2">
          <p className="text-sm text-[#0F172A]">
            {approvalAction === 'approve'
              ? `确定批准任务「${approvalTask?.id}」并继续执行吗？`
              : `确定驳回任务「${approvalTask?.id}」吗？任务将被标记为失败。`}
          </p>
          <div>
            <label className="block text-sm text-[#0F172A] mb-1.5">comment（可选）</label>
            <Input.TextArea
              value={approvalReason}
              onChange={(e) => setApprovalReason(e.target.value)}
              placeholder={approvalAction === 'reject' ? '建议填写驳回原因（可选）' : '审批意见（可选）'}
              rows={3}
            />
          </div>
        </div>
      </Modal>
    </div>
  )
}

/* ─── Info row component ─── */
function InfoRow({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-xs text-[#64748B]">{label}</span>
      <span className={`text-xs text-[#0F172A] ${mono ? 'font-mono' : ''} ml-4 text-right max-w-[280px] truncate`}>
        {value}
      </span>
    </div>
  )
}
