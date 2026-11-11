/**
 * Studio TaskBoard — 任务协作看板（6 列按后端状态精确分桶）。
 *
 * 对齐旧版 frontend/src/pages/tasks-page.tsx，适配 studio 暗色风 + 原生组件。
 *
 * 设计要点：
 * - 6 列状态分桶：pending / running / waiting_human / completed / failed / cancelled
 * - 列表查询：useQueries 并发发起 6 次 list（按 status，page=1, page_size=50）
 *   刷新双通道：WS task_status 事件 invalidate（见 use-task-realtime）为主，
 *   running/waiting_human 两列非空时另有 5s 条件轮询兜底（WS 断连时状态仍可迁移）
 * - 节点进度：仅对 running / waiting_human 两列拉详情（3s 轮询，上限 20 个）——
 *   WS 不推 node_start/node_complete，节点进度靠轮询拉 timeline 推进
 * - 详情查询与详情 Drawer 共用 taskKeys.detail(id) 缓存
 * - 搜索改为纯前端过滤（task.id / workflow_id includes）
 * - workflowNameMap：始终拉一次 workflow 列表，把 workflow_id 解析成可读名称
 */
import { useState, useMemo, useCallback, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient, useQueries } from '@tanstack/react-query'
import { Plus, Search, Loader2, Pencil, Trash2, History } from 'lucide-react'
import {
  tasksApi, taskKeys,
  type TaskSummary, type TaskStatusValue, type TaskDetail, type NodeProgress,
  type CommentValue, BOARD_STATUSES, parseNodeProgress, type WorkflowRegistryEntry,
} from '../services/tasks-api'
import { workflowsApi, workflowKeys } from '../services/workflows-api'
import { agentApi, agentKeys } from '../services/agent-api'
import { toStudioAgent } from '../services/adapters'
import type { Agent } from '../types'
import { userApi } from '../services/user-api'
import {
  triggersApi, triggerKeys, getTriggerId, type TriggerConfig,
} from '../services/triggers-api'
import { useAuthStore } from '../stores/auth-store'
import { usePermission } from '../hooks/use-permission'
import { TASK_STATUS_STYLES, toneVar } from '../constants/task-status'
import { TaskBoardCard } from './task/TaskBoardCard'
import { RewindModal } from './task/RewindModal'
import TriggerConfigModal from './trigger/TriggerConfigModal'
import TriggerTaskRecordsModal from './trigger/TriggerTaskRecordsModal'
import { formatTimeRelative } from '../lib/formatTime'
import { Modal, Select, Popover } from './ui'
import { confirmDialog } from './ui/confirm'
import { toast } from './ui/toast'
import { getErrorMessage } from '../lib/api-client'
import { ResModal, Field as ResField, UInput, UTextarea, Seg } from './res-modal'
import WorkflowInputForm from '../features/workflow-editor/WorkflowInputForm'
import { buildDefaultValues, coerceValues } from '../features/workflow-editor/utils/workflow-input-values'
import type { VariableDefinition } from '../features/workflow-editor/utils/variable-types'

export function TaskBoard({ theme = 'dark', onOpenTaskDetail }: { theme?: 'light' | 'dark'; onOpenTaskDetail?: (taskId: string) => void }) {
  const qc = useQueryClient()
  const permissions = useAuthStore((s) => s.user?.permissions ?? [])
  const canReadUsers = permissions.includes('user:read')
  const authUser = useAuthStore((s) => s.user)

  /* ─── 双视图：执行看板 / 定时调度（设计稿 task-unified.html） ─── */
  const [tab, setTab] = useState<'runs' | 'sched'>('runs')
  // 任务来源筛选（runs）：定时=trigger_id 命中 / 手动
  const [srcFilter, setSrcFilter] = useState<'all' | 'manual' | 'cron'>('all')
  // 列内排序：默认最新在前；「按时间」切换 最早在前
  const [timeAsc, setTimeAsc] = useState(false)
  // 调度（sched）：从 TriggersPage 并入——列表/启停/删除/新建/记录
  const canWriteTrigger = usePermission('trigger:write')
  const canManageTrigger = usePermission('trigger:manage')
  const [scope, setScope] = useState<'own' | 'all'>('own')
  const [tSearch, setTSearch] = useState('')
  const [configModal, setConfigModal] = useState<{
    open: boolean; mode: 'create' | 'edit'; trigger: TriggerConfig | null
  }>({ open: false, mode: 'create', trigger: null })
  const [recordsTrigger, setRecordsTrigger] = useState<TriggerConfig | null>(null)

  const triggersQuery = useQuery({
    queryKey: triggerKeys.list(scope),
    queryFn: () => triggersApi.list(scope === 'all'),
  })
  const triggers: TriggerConfig[] = triggersQuery.data?.items ?? []
  const triggerStats = useMemo(() => {
    const enabled = triggers.filter((t) => t.enabled).length
    return { total: triggers.length, enabled, disabled: triggers.length - enabled }
  }, [triggers])

  const invalidateTriggers = () => qc.invalidateQueries({ queryKey: triggerKeys.lists() })
  const toggleTrigger = useMutation({
    mutationFn: (vars: { trigger: TriggerConfig; enabled: boolean }) =>
      triggersApi.toggle(getTriggerId(vars.trigger), vars.enabled),
    onSuccess: invalidateTriggers,
  })
  const deleteTriggerM = useMutation({
    mutationFn: (triggerId: string) => triggersApi.remove(triggerId),
    onSuccess: () => { invalidateTriggers(); toast.success('已删除') },
    onError: (e) => setActionError(`删除失败：${getErrorMessage(e)}`),
  })
  // 列头 dot 颜色（设计稿：进行中=品牌靛蓝动画 / 完成=绿 / 等待人工=琥珀 / 失败=红）
  const COL_DOT: Record<TaskStatusValue, string> = {
    pending: 'var(--color-ink-faint)',
    running: 'var(--color-brand)',
    waiting_human: 'var(--color-sig-wait)',
    completed: 'var(--color-sig-ok)',
    failed: 'var(--color-sig-fail)',
    cancelled: 'var(--color-ink-faint)',
  }

  /* ─── Search state（纯前端过滤） ─── */
  const [searchInput, setSearchInput] = useState('')
  const debouncedSearch = useDebouncedValue(searchInput.toLowerCase(), 200)

  /* ─── Create modal state ───
     entryId 存选中的 workflow_registry 条目 _id（wfr_...，唯一稳定）；
     提交时再由 resolveTemplateId 解析成真正的模板 workflow_id（wf_...）传给后端，
     避免 task.workflow_id 存成 wfr_ 导致引擎找不到模板（engine 直接按 _id 查 workflows 集合）。 */
  const [createOpen, setCreateOpen] = useState(false)
  const [newTask, setNewTask] = useState<{ entryId: string; input: string }>({ entryId: '', input: '' })
  // 执行目标：工作流 或 单个 Agent（设计稿 tgt-row 双类型）
  const [tgtOpen, setTgtOpen] = useState(false)
  const [tgtPos, setTgtPos] = useState<{ top: number; left: number; width: number }>({ top: 0, left: 0, width: 0 })
  const [target, setTarget] = useState<{ kind: 'workflow' | 'agent'; id: string; name: string; sub: string } | null>(null)
  // 标准下拉：贴触发行下方弹出（下方空间不足自动翻到上方），浮层自身滚动，modal 不被拉扯
  const openTgtPicker = (e: { currentTarget: EventTarget & HTMLElement }) => {
    const r = e.currentTarget.getBoundingClientRect()
    const MAXH = 280
    const below = window.innerHeight - r.bottom - 12
    const top = below >= 200 ? r.bottom + 6 : Math.max(12, r.top - MAXH - 6)
    setTgtPos({ top, left: r.left, width: Math.max(r.width, 320) })
    setTgtOpen(true)
  }
  const [actionError, setActionError] = useState<string | null>(null)
  // 结构化输入参数表单（选中声明了输入变量的工作流时启用，见下方 detailQuery）
  const [inputValues, setInputValues] = useState<Record<string, unknown>>({})
  const [inputValid, setInputValid] = useState(true)
  const [inputTouched, setInputTouched] = useState(false)

  /* ─── Rewind modal state（看板卡片「退回重跑」打开的共享弹窗） ─── */
  const [rewindTask, setRewindTask] = useState<TaskSummary | null>(null)

  /* ─── 发起任务双模式（设计稿 taskModal）：立即执行 / 定时调度 ─── */
  const [createMode, setCreateMode] = useState<'immediate' | 'sched'>('immediate')
  const [schedFreq, setSchedFreq] = useState<'daily' | 'weekly' | 'monthly' | 'hourly' | 'once' | 'adv'>('daily')
  const [schedTime, setSchedTime] = useState('09:00')
  const [schedDow, setSchedDow] = useState(1)
  const [schedDom, setSchedDom] = useState(1)
  const [schedEvery, setSchedEvery] = useState(2)
  const [schedOnceAt, setSchedOnceAt] = useState('')
  const [cronAdv, setCronAdv] = useState('0 9 * * *')

  const buildCron = () => {
    const [hh, mm] = schedTime.split(':').map(Number)
    switch (schedFreq) {
      case 'daily': return `${mm || 0} ${hh || 0} * * *`
      case 'weekly': return `${mm || 0} ${hh || 0} * * ${schedDow}`
      case 'monthly': return `${mm || 0} ${hh || 0} ${schedDom} * *`
      case 'hourly': return `0 */${schedEvery || 1} * * *`
      case 'adv': return cronAdv.trim()
      default: return '0 9 * * *'
    }
  }
  const SCHED_FREQ_LABEL: Record<typeof schedFreq, string> = {
    daily: '每天', weekly: '每周', monthly: '每月', hourly: '按小时间隔', once: '仅一次', adv: '自定义 cron',
  }
  const DOW_LABEL = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']

  /* ─── 6 列并发列表查询（按 status 分桶） ───
     刷新双通道：任务级状态变迁由 WS task_status 事件 invalidate 即时驱动
     （use-task-realtime）；running/waiting_human 两列另有条件轮询（非空时 5s，
     兜底 WS 断连时的状态迁移），空列 / 终态列零轮询。 */
  const boardQueries = useQueries({
    queries: BOARD_STATUSES.map((status) => ({
      queryKey: taskKeys.list({ status, page: 1, page_size: 50 }),
      queryFn: () => tasksApi.list({ status, page: 1, page_size: 50 }),
      refetchInterval: (query: { state: { data?: { items?: unknown[] } | undefined } }) =>
        (status === 'running' || status === 'waiting_human') &&
        (query.state.data?.items?.length ?? 0) > 0
          ? 5_000
          : false,
    })),
  })

  const tasksByStatus = useMemo(() => {
    const map: Record<TaskStatusValue, TaskSummary[]> = {
      pending: [], running: [], waiting_human: [], completed: [], failed: [], cancelled: [],
    }
    BOARD_STATUSES.forEach((status, idx) => {
      const result = boardQueries[idx]
      map[status] = (result?.data?.items ?? []) as TaskSummary[]
    })
    return map
  }, [boardQueries])

  const boardLoading = boardQueries.some((q) => q.isLoading)

  /* ─── 收集 active 任务，批量拉详情（staleTime 3s，上限 20 个） ─── */
  const MAX_PROGRESS_TASKS = 20
  const ACTIVE_STATUSES: TaskStatusValue[] = ['running', 'waiting_human']
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
      staleTime: 3_000,
      // 3s 轮询驱动节点进度（WS 只推任务级状态变迁，node_start/node_complete
      // 靠拉 timeline）；任务进入终态后从活跃列移除，查询随之销毁、轮询自停。
      refetchInterval: 3_000,
    })),
  })

  const progressMap = useMemo(() => {
    const map: Record<string, NodeProgress | null | undefined> = {}
    activeTasksForDetail.forEach((task, idx) => {
      const detail = activeDetailQueries[idx]?.data
      if (detail) map[task.id] = parseNodeProgress(detail.timeline)
    })
    return map
  }, [activeTasksForDetail, activeDetailQueries])

  /* ─── Workflow 名称映射（看板卡片用，始终启用） ───
     registry 条目有两个 id 字段，职责不同：
       _id         → workflow_registry 条目 id（wfr_...），用于 UI 选项 value（唯一稳定）
       workflow_id → 工作流模板 id（wf_...），后端 task.workflow_id 应存这个
     新建任务统一用 entry._id 选择、提交时 resolveTemplateId 转 workflow_id，保证
     task.workflow_id 一定是模板 id，引擎 run_and_persist 才能按 _id 查到 workflows 文档。
     历史任务可能存了 wfr_（旧 bug），workflowNameMap/resolveTemplateId 双向兼容。 */
  const { data: wfData } = useQuery({
    queryKey: taskKeys.workflows(),
    queryFn: () => tasksApi.listWorkflows(),
    staleTime: 60_000,
  })
  const workflowNameMap = useMemo(() => {
    const map: Record<string, string> = {}
    for (const wf of (wfData?.items ?? []) as WorkflowRegistryEntry[]) {
      if (wf.name) {
        map[wf._id] = wf.name          // registry entry id (wfr_...) — 兼容历史任务存 wfr_ 的情况
        map[wf.workflow_id] = wf.name   // 模板 id (wf_...) — 新任务正常存这个
      }
    }
    return map
  }, [wfData])
  // 把 registry entry _id (wfr_) 解析为模板 workflow_id (wf_)；传入已是 wf_ 则原样返回。
  const resolveTemplateId = useCallback((maybeRegistryId: string): string => {
    if (!maybeRegistryId) return ''
    const entry = (wfData?.items ?? []).find(
      (wf) => wf._id === maybeRegistryId || wf.workflow_id === maybeRegistryId,
    )
    return entry?.workflow_id ?? maybeRegistryId
  }, [wfData])
  const workflows: WorkflowRegistryEntry[] = wfData?.items ?? []
  // 已发布 Agent（发起任务弹窗的执行目标第二类型：委派单个 Agent 执行）
  const { data: pubAgentsData } = useQuery({
    queryKey: agentKeys.list({ page: 1, page_size: 100, status: 'published' }),
    queryFn: () => agentApi.list({ page: 1, page_size: 100, status: 'published' }),
    enabled: createOpen,
  })
  const pubAgents: Agent[] = useMemo(() => (pubAgentsData?.items ?? []).map(toStudioAgent), [pubAgentsData])

  // 调度规则过滤（名称 / cron / workflow_id）
  const filteredTriggers = useMemo(() => {
    if (!tSearch.trim()) return triggers
    const q = tSearch.trim().toLowerCase()
    return triggers.filter((t) => {
      const wfName = workflowNameMap[t.workflow_id] || ''
      return wfName.toLowerCase().includes(q) || (t.cron_expression || '').toLowerCase().includes(q)
    })
  }, [triggers, tSearch, workflowNameMap])

  // 下次执行预告：启用中的调度里最近的一条
  const nextRun = useMemo(
    () => triggers
      .filter((t) => t.enabled && t.next_trigger_at)
      .sort((a, b) => new Date(a.next_trigger_at!).getTime() - new Date(b.next_trigger_at!).getTime())[0] ?? null,
    [triggers],
  )

  /* ─── 新建任务：选中工作流后拉详情，读 start 节点 output_variables ───
     与「AI 工作路线」运行链路（useWorkflowExecution）及定时任务弹窗
     （TriggerConfigModal）对齐：声明了输入变量的工作流用结构化表单按名收集，
     否则保留可选 prompt 透传。缓存 key 与工作流详情页共用。 */
  const selectedTemplateId = useMemo(
    () => (createOpen ? resolveTemplateId(newTask.entryId) : ''),
    [createOpen, newTask.entryId, resolveTemplateId],
  )
  const { data: wfDetail, isLoading: wfDetailLoading } = useQuery({
    queryKey: workflowKeys.detail(selectedTemplateId),
    queryFn: () => workflowsApi.get(selectedTemplateId),
    enabled: createOpen && !!selectedTemplateId,
    staleTime: 60_000,
  })
  const inputVariables = useMemo(() => {
    const startNode = (wfDetail?.nodes ?? []).find((n) => n.type === 'start')
    return (startNode?.config?.output_variables as VariableDefinition[] | undefined) ?? []
  }, [wfDetail])
  const hasInputVariables = inputVariables.length > 0
  // 切换工作流 / 变量定义载入后重置表单（默认值填充 + 清除错误态）
  useEffect(() => {
    setInputValues(buildDefaultValues(inputVariables))
    setInputTouched(false)
  }, [newTask.entryId, inputVariables])

  /* ─── Creator 名称映射（user:read 权限时拉一次 users 列表，把 created_by 的 user id 解析成可读 username） ─── */
  const { data: usersData } = useQuery({
    queryKey: ['users', { page: 1, page_size: 100 }],
    queryFn: async () => (await userApi.list({ page: 1, page_size: 100 })).data,
    enabled: canReadUsers,
    staleTime: 60_000,
  })
  const creatorNameMap = useMemo(() => {
    const map: Record<string, string> = {}
    for (const u of usersData?.items ?? []) map[u.id] = u.username
    return map
  }, [usersData])
  const creatorLabel = useCallback((created_by: string, created_by_type?: string) => {
    // 绝不把内部 id（user_01KT…）直接展示给用户：解析不到时降级为角色词
    if (created_by_type === 'system') return '系统'
    if (created_by_type === 'user') {
      if (creatorNameMap[created_by]) return creatorNameMap[created_by]
      return authUser?.id === created_by ? '我' : '成员'
    }
    if (created_by_type === 'agent') return 'Agent'
    return created_by_type ? created_by_type : '—'
  }, [creatorNameMap, authUser])

  /* ─── Mutations ─── */
  const createTask = useMutation({
    // structuredInput：结构化表单收集的值（workflow 有输入变量定义时优先）；
    // agent 目标：input = {instruction}，entryId 此时存的是 agent id
    mutationFn: (vars: { entryId: string; input: string; structuredInput?: Record<string, unknown>; targetKind: 'workflow' | 'agent'; scheduledAt?: string }) =>
      vars.targetKind === 'agent'
        ? tasksApi.create({ agent_id: vars.entryId, input: { instruction: vars.input }, scheduled_at: vars.scheduledAt ?? null })
        : tasksApi.create({
            // 把 registry entry _id (wfr_) 解析成模板 workflow_id (wf_) 再传给后端
            workflow_id: resolveTemplateId(vars.entryId),
            input: vars.structuredInput ?? (vars.input ? { prompt: vars.input } : {}),
          }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: taskKeys.lists() })
      setCreateOpen(false)
      setNewTask({ entryId: '', input: '' })
    },
    onError: (e) => setActionError(`创建任务失败：${getErrorMessage(e)}`),
  })

  // 定时调度创建（发起任务弹窗 sched 分支）：enabled 直启，保存后按 cron 出实例
  const createScheduleM = useMutation({
    mutationFn: (vars: { workflowId: string; type: 'cron' | 'once'; cron_expression?: string; execute_at?: string }) =>
      triggersApi.create(vars.workflowId, {
        type: vars.type,
        enabled: true,
        cron_expression: vars.cron_expression,
        execute_at: vars.execute_at,
        default_input: {},
      }),
    onSuccess: () => {
      invalidateTriggers()
      setCreateOpen(false)
      setNewTask({ entryId: '', input: '' })
      toast.success('已保存调度规则')
    },
    onError: (e) => setActionError(`保存调度失败：${getErrorMessage(e)}`),
  })

  const intervene = useMutation({
    mutationFn: (vars: { taskId: string; action: string; version: number; comment?: CommentValue }) =>
      tasksApi.intervene(vars.taskId, { action: vars.action, version: vars.version, comment: vars.comment }),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: taskKeys.lists() })
      // 已打开的详情页立即刷新，不等 WS task_status 事件
      qc.invalidateQueries({ queryKey: taskKeys.detail(vars.taskId) })
    },
    onError: (e) => setActionError(`操作失败：${getErrorMessage(e)}`),
  })

  const removeTask = useMutation({
    mutationFn: (taskId: string) => tasksApi.remove(taskId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: taskKeys.lists() })
    },
    onError: (e) => setActionError(`删除失败：${getErrorMessage(e)}`),
  })

  /* ─── Actions ─── */
  const handleCreateSubmit = (e: React.FormEvent) => {
    // 不阻止默认提交 → 原生表单提交整页刷新回聊天主页（历史 bug：toast 一闪即逝）
    e.preventDefault()
    if (!newTask.entryId) {
      setActionError(target?.kind === 'agent' ? '请先选择一个已发布的 Agent' : '请先选择一个已发布的工作流')
      return
    }
    // agent 目标的单次定时：调度规则(triggers)绑定 workflow，不走 createScheduleM——
    // 创建带 scheduled_at 的任务，到期由 task_scheduler_service 自动拉起
    if (createMode === 'sched' && target?.kind === 'agent') {
      if (!schedOnceAt) {
        setActionError('请选择一次性执行的时间')
        return
      }
      setActionError(null)
      createTask.mutate({ ...newTask, targetKind: 'agent', scheduledAt: new Date(schedOnceAt).toISOString() })
      return
    }
    // 定时调度分支：保存为调度规则（按 cron 自动产生执行实例），不立即执行
    if (createMode === 'sched') {
      if (schedFreq === 'once' && !schedOnceAt) {
        setActionError('请选择一次性执行的时间')
        return
      }
      if (schedFreq !== 'once' && schedFreq === 'adv' && !cronAdv.trim()) {
        setActionError('请填写 cron 表达式')
        return
      }
      setActionError(null)
      createScheduleM.mutate({
        workflowId: resolveTemplateId(newTask.entryId),
        type: schedFreq === 'once' ? 'once' : 'cron',
        cron_expression: schedFreq === 'once' ? undefined : buildCron(),
        execute_at: schedFreq === 'once' ? new Date(schedOnceAt).toISOString() : undefined,
      })
      return
    }
    setActionError(null)
    const targetKind = target?.kind ?? 'workflow'
    // 有输入变量定义：先过必填校验 + 类型强转，再按变量名提交
    if (hasInputVariables) {
      setInputTouched(true)
      if (!inputValid) return
      const res = coerceValues(inputVariables, inputValues)
      if (res.error) {
        setActionError(res.error)
        return
      }
      createTask.mutate({ ...newTask, structuredInput: res.values, targetKind })
      return
    }
    createTask.mutate({ ...newTask, targetKind })
  }

  const handleCancel = useCallback(async (task: TaskSummary | TaskDetail) => {
    const ok = await confirmDialog({
      title: `取消任务「${task.id.slice(-8)}」？`,
      description: '任务将被中止，无法恢复。',
      okText: '取消任务',
      danger: true,
    })
    if (!ok) return
    intervene.mutate({ taskId: task.id, action: 'cancel', version: task.version })
  }, [intervene])

  const handleRetry = useCallback(async (task: TaskSummary | TaskDetail) => {
    const ok = await confirmDialog({
      title: `重试任务「${task.id.slice(-8)}」？`,
      description: '任务将重置为待执行并重新开始执行。',
      okText: '重试',
    })
    if (!ok) return
    intervene.mutate({ taskId: task.id, action: 'retry', version: task.version })
  }, [intervene])

  // comment 空判：text 模式空字符串时省略（后端默认归一化为 ""），其余（含 json）透传
  const isCommentEmpty = (c: CommentValue | undefined): boolean =>
    !c || (typeof c === 'string' && !c) || (typeof c === 'object' && c.type === 'text' && !c.value)

  const handleApprovalSubmit = useCallback((task: TaskSummary | TaskDetail, action: 'approve' | 'reject', comment: CommentValue) => {
    intervene.mutate({ taskId: task.id, action, version: task.version, comment: isCommentEmpty(comment) ? undefined : comment })
  }, [intervene])

  const handleDelete = useCallback(async (task: TaskSummary | TaskDetail) => {
    const ok = await confirmDialog({
      title: `删除任务「${task.id.slice(-8)}」？`,
      description: '此操作不可恢复，任务及其时间线将被永久删除。',
      okText: '删除',
      danger: true,
    })
    if (!ok) return
    removeTask.mutate(task.id)
  }, [removeTask])

  const handleCardClick = useCallback((task: TaskSummary) => {
    onOpenTaskDetail?.(task.id)
  }, [onOpenTaskDetail])

  /* ─── 过滤函数（前端 includes 匹配） ─── */
  const filterTasks = useCallback((tasks: TaskSummary[]) => {
    if (!debouncedSearch) return tasks
    return tasks.filter(
      (task) =>
        task.id.toLowerCase().includes(debouncedSearch) ||
        task.workflow_id.toLowerCase().includes(debouncedSearch),
    )
  }, [debouncedSearch])

  // 页头计数随视图切换（设计稿 headCnt）
  const activeCount = tasksByStatus.running.length + tasksByStatus.waiting_human.length
  const headCnt = tab === 'runs'
    ? `${tasksByStatus.waiting_human.length} 等待人工 · ${tasksByStatus.running.length} 进行中 · ${triggerStats.total} 调度规则`
    : `${triggerStats.total} 条规则 · ${triggerStats.enabled} 启用 · ${triggerStats.disabled} 停用`
  // 来源筛选（runs，纯前端）：定时=trigger_id 命中
  const matchSrc = (t: TaskSummary) => srcFilter === 'all' || (srcFilter === 'cron' ? !!t.trigger_id : !t.trigger_id)

  return (
    <div className="af-scope theme-indigo flex flex-col h-full min-h-0 gap-4 font-sans">
      {actionError && (
        <div className="px-3 py-2 rounded-lg bg-sig-fail-soft border border-line text-sig-fail text-[11px] flex items-center justify-between shrink-0">
          <span>⚠ {actionError}</span>
          <button onClick={() => setActionError(null)} className="text-sig-fail hover:text-sig-fail cursor-pointer">✕</button>
        </div>
      )}

      {/* ─── 页头：衬线大标题 + 动态计数 + 视图 tab + 主 CTA ─── */}
      <div className="af-page-head shrink-0">
        <h2 className="text-[22px] font-bold text-ink" style={{ fontFamily: 'var(--font-serif)' }}>任务</h2>
        <span className="af-cnt font-mono">{headCnt}</span>
        <div className="right flex items-center gap-5">
          {/* 视图切换：执行看板 / 定时调度（下划线式） */}
          <div className="flex items-center gap-[18px]">
            {([['runs', '执行看板'], ['sched', '定时调度']] as const).map(([k, label]) => (
              <button
                key={k}
                onClick={() => setTab(k)}
                className={`px-0.5 pt-1 pb-[7px] -mb-px text-[12.5px] border-b-2 transition-colors cursor-pointer ${
                  tab === k ? 'text-brand border-brand font-bold' : 'text-ink-dim border-transparent hover:text-ink'
                }`}
              >
                {label}
              </button>
            ))}
          </div>
          {/* 下次执行预告（设计稿 next-run）：最近的启用调度 */}
          {tab === 'runs' && nextRun && (
            <span className="text-[11.5px] text-ink-faint flex items-center gap-1.5">
              接下来：<b className="text-ink font-semibold">{workflowNameMap[nextRun.workflow_id] ?? nextRun.workflow_id}</b>
              <span>· {formatTimeRelative(nextRun.next_trigger_at)}</span>
            </span>
          )}
          <button
            onClick={() => {
              setActionError(null)
              setCreateMode(tab === 'sched' ? 'sched' : 'immediate')
              setCreateOpen(true)
            }}
            className="af-btn af-btn-primary"
          >
            ＋ 新建任务
          </button>
        </div>
      </div>

      {tab === 'runs' && (
      /* ─── 筛选行：搜索 + 来源筛选（任务 ID / 工作流） ─── */
      <div className="flex items-center gap-3 shrink-0">
        <div className="relative w-[280px]">
          <Search className="w-3.5 h-3.5 pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-faint" />
          <input
            type="text"
            placeholder="搜索任务 ID 或工作流..."
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            className="w-full pl-9 pr-3 h-8 text-xs bg-panel border border-line rounded-lg text-ink placeholder:text-ink-faint focus:outline-none focus:border-brand transition font-medium"
          />
        </div>
        {/* 来源筛选：全部 / 手动 / 定时 */}
        <div className="flex items-center gap-1 p-0.5 rounded-lg bg-raise">
          {([['all', '全部'], ['manual', '手动'], ['cron', '定时']] as const).map(([k, label]) => (
            <button
              key={k}
              onClick={() => setSrcFilter(k)}
              className={`px-2.5 h-6 rounded-md text-[11px] cursor-pointer transition-colors ${
                srcFilter === k ? 'bg-panel text-brand font-semibold shadow-[0_1px_2px_rgba(0,0,0,.06)]' : 'text-ink-dim hover:text-ink'
              }`}
            >
              {label}
            </button>
          ))}
        </div>
        {/* 按时间排序（设计稿「按时间 ▾」）：切换列内 新→旧 / 旧→新 */}
        <button
          onClick={() => setTimeAsc((v) => !v)}
          className="text-[11px] text-ink-faint hover:text-ink cursor-pointer"
          title="切换列内任务排序方向"
        >
          按时间 {timeAsc ? '↑' : '↓'}
        </button>
      </div>
      )}

      {/* ─── 6 列全高看板：列直达页底、列内纵向滚、横向滚动条隐藏（规范 §5.10） ─── */}
      <div className={tab === 'runs' ? 'flex gap-3 overflow-x-auto flex-1 min-h-0 [&::-webkit-scrollbar]:hidden [scrollbar-width:none]' : 'hidden'}>
        {boardLoading ? (
          <div className="flex items-center justify-center w-full py-20 text-ink-dim text-xs">
            <Loader2 className="w-4 h-4 animate-spin mr-2" /> 加载任务…
          </div>
        ) : (
          BOARD_STATUSES.map((status) => {
            const style = TASK_STATUS_STYLES[status]
            const tasks = [...filterTasks(tasksByStatus[status]).filter(matchSrc)]
              .sort((a, b) => timeAsc
                ? new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
                : new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
            return (
              <div
                key={status}
                className="min-w-[150px] flex-1 flex-shrink-0 flex flex-col"
              >
                {/* 列头（设计稿 col-head）：dot 7px + 名称 12.5px 700 + mono 11px 计数右对齐 */}
                <div className="flex items-center gap-2 px-1 pt-1 pb-2.5 shrink-0">
                  <span
                    className={`w-[7px] h-[7px] rounded-full shrink-0 ${status === 'running' ? 'animate-breathe' : ''}`}
                    style={{ backgroundColor: COL_DOT[status] }}
                  />
                  <span className="text-[12.5px] font-bold text-ink-soft truncate">{style.label}</span>
                  <span className="ml-auto font-mono text-[11px] text-ink-faint">{tasks.length}</span>
                </div>

                {/* 卡片区：列内独立纵向滚动到页底 */}
                <div className="flex-1 overflow-y-auto px-0.5 pb-0.5 space-y-2 scrollbar-custom">
                  {tasks.length === 0 ? (
                    <div className="flex items-center justify-center py-8 text-[11px] text-ink-faint">
                      暂无
                    </div>
                  ) : (
                    tasks.map((task) => (
                      <TaskBoardCard
                        key={task.id}
                        task={task}
                        progress={progressMap[task.id]}
                        workflowName={workflowNameMap[task.workflow_id]}
                        creatorName={creatorLabel(task.created_by, task.created_by_type)}
                        sourceTag={task.trigger_id ? 'cron' : 'manual'}
                        onClick={() => handleCardClick(task)}
                        onCancel={handleCancel}
                        onRetry={handleRetry}
                        onDelete={handleDelete}
                        onApprovalSubmit={handleApprovalSubmit}
                        onRewind={setRewindTask}
                        interveneLoading={intervene.isPending}
                        deleteLoading={removeTask.isPending}
                      />
                    ))
                  )}
                </div>
              </div>
            )
          })
        )}
      </div>

      {/* ─── 定时调度 pane：调度规则列表（设计稿 s-card） ─── */}
      {tab === 'sched' && (
        <div className="flex-1 min-h-0 overflow-y-auto scrollbar-custom pr-0.5">
          {/* 工具栏：搜索 + scope 切换 */}
          <div className="flex items-center gap-3 mb-3">
            <div className="relative w-[280px]">
              <Search className="w-3.5 h-3.5 pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-faint" />
              <input
                type="text"
                placeholder="搜索调度规则 / 工作流…"
                value={tSearch}
                onChange={(e) => setTSearch(e.target.value)}
                className="w-full pl-9 pr-3 h-8 text-xs bg-panel border border-line rounded-lg text-ink placeholder:text-ink-faint focus:outline-none focus:border-brand transition font-medium"
              />
            </div>
            {canManageTrigger && (
              <div className="flex items-center gap-1 p-0.5 rounded-lg bg-raise">
                {([['own', '我的'], ['all', '全部']] as const).map(([k, label]) => (
                  <button
                    key={k}
                    onClick={() => setScope(k)}
                    className={`px-2.5 h-6 rounded-md text-[11px] cursor-pointer transition-colors ${
                      scope === k ? 'bg-panel text-brand font-semibold shadow-[0_1px_2px_rgba(0,0,0,.06)]' : 'text-ink-dim hover:text-ink'
                    }`}
                  >
                    {label}
                  </button>
                ))}
              </div>
            )}
          </div>

          {triggersQuery.isLoading ? (
            <div className="flex items-center justify-center py-16 text-ink-dim text-xs">
              <Loader2 className="w-4 h-4 animate-spin mr-2" /> 加载调度规则…
            </div>
          ) : filteredTriggers.length === 0 ? (
            <div className="py-16 text-center text-xs text-ink-faint">
              {tSearch ? '没有匹配的调度规则' : '还没有定时任务——切到「执行看板」上方的「＋ 新建定时任务」创建'}
            </div>
          ) : (
            <div className="space-y-2.5 pb-6 max-w-[920px]">
              {filteredTriggers.map((t) => {
                const wfName = workflowNameMap[t.workflow_id] ?? t.workflow_id
                const isCron = t.type === 'cron'
                return (
                  <div
                    key={getTriggerId(t)}
                    className={`bg-panel border border-line rounded-[13px] px-[18px] py-4 flex items-center gap-[18px] ${
                      t.enabled ? '' : 'opacity-70'
                    }`}
                  >
                    {/* 主信息：名称 + cron chip / 一次性时间 + 人类描述 */}
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2 min-w-0">
                        <span className="text-[14px] font-bold text-ink truncate">{wfName}</span>
                        {isCron && (
                          <span className="font-mono text-[10.5px] px-2 py-0.5 rounded-md bg-raise text-ink-dim shrink-0">{t.cron_expression || '-'}</span>
                        )}
                      </div>
                      <div className="text-[11px] text-ink-dim mt-1 truncate">
                        {isCron ? `cron 调度` : `一次性 · ${t.execute_at ? new Date(t.execute_at).toLocaleString('zh-CN') : '-'}`}
                        {' · '}工作流「{wfName}」
                      </div>
                    </div>

                    {/* 最近 7 次执行点阵（设计稿 dots7） */}
                    <div className="hidden md:flex flex-col items-start gap-1 shrink-0">
                      <TriggerDots triggerId={getTriggerId(t)} />
                      <div className="text-[10px] text-ink-faint">{t.last_triggered_at ? `上次 ${formatTimeRelative(t.last_triggered_at)}` : '未触发过'}</div>
                    </div>

                    {/* 下次执行倒计时（设计稿 next：衬线大数字） */}
                    <div className="hidden lg:block text-center shrink-0 min-w-[96px]">
                      <b className={`block text-[19px] font-bold leading-[1.15] ${t.enabled ? 'text-ink' : 'text-ink-faint'}`} style={{ fontFamily: 'var(--font-serif)' }}>
                        {t.enabled && t.next_trigger_at ? formatCountdown(t.next_trigger_at) : '—'}
                      </b>
                      <span className="text-[9.5px] text-ink-faint">
                        {t.enabled ? '下次执行' : '已停用'}
                        {t.enabled && t.next_trigger_at && ` · ${new Date(t.next_trigger_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}`}
                      </span>
                    </div>

                    {/* 操作：记录 / 编辑 / 删除 / 启停开关 */}
                    <div className="flex items-center gap-2 shrink-0">
                      <button
                        onClick={() => setRecordsTrigger(t)}
                        title="执行记录"
                        className="p-1.5 rounded-lg text-ink-dim hover:text-brand hover:bg-raise cursor-pointer transition-colors"
                      >
                        <History size={14} />
                      </button>
                      {canWriteTrigger && (
                        <>
                          <button
                            onClick={() => setConfigModal({ open: true, mode: 'edit', trigger: t })}
                            title="编辑"
                            className="p-1.5 rounded-lg text-ink-dim hover:text-brand hover:bg-raise cursor-pointer transition-colors"
                          >
                            <Pencil size={14} />
                          </button>
                          <button
                            onClick={async () => {
                              const ok = await confirmDialog({
                                title: '删除定时任务',
                                description: '删除后将永久停止该定时任务，已触发的任务记录不受影响。',
                                okText: '删除',
                                danger: true,
                              })
                              if (ok) deleteTriggerM.mutate(getTriggerId(t))
                            }}
                            title="删除"
                            className="p-1.5 rounded-lg text-ink-dim hover:text-sig-fail hover:bg-raise cursor-pointer transition-colors"
                          >
                            <Trash2 size={14} />
                          </button>
                        </>
                      )}
                      {canWriteTrigger && (
                        <button
                          type="button"
                          role="switch"
                          aria-checked={t.enabled}
                          disabled={toggleTrigger.isPending}
                          onClick={() => toggleTrigger.mutate({ trigger: t, enabled: !t.enabled })}
                          className={`w-8 h-[18px] rounded-full relative transition-colors cursor-pointer disabled:opacity-50 ${t.enabled ? 'bg-brand' : 'bg-line-strong'}`}
                          title={t.enabled ? '点击停用' : '点击启用'}
                        >
                          <span className={`absolute top-[2px] w-[14px] h-[14px] rounded-full bg-white shadow transition-all ${t.enabled ? 'left-[16px]' : 'left-[2px]'}`} />
                        </button>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* ─── 退回重跑 Modal（卡片「退回重跑」打开，与详情页共享组件） ─── */}
      {rewindTask && (
        <RewindModal
          task={rewindTask}
          open={!!rewindTask}
          onClose={() => setRewindTask(null)}
          resolveTemplateId={resolveTemplateId}
        />
      )}

      {/* ─── 定时任务 新建/编辑 + 执行记录（从 TriggersPage 并入） ─── */}
      <TriggerConfigModal
        open={configModal.open}
        mode={configModal.mode}
        trigger={configModal.trigger}
        workflows={workflows}
        onClose={() => setConfigModal({ open: false, mode: 'create', trigger: null })}
        onSaved={invalidateTriggers}
      />
      {recordsTrigger && (
        <TriggerTaskRecordsModal
          trigger={recordsTrigger}
          workflows={workflows}
          onClose={() => setRecordsTrigger(null)}
          onViewTask={onOpenTaskDetail}
        />
      )}

      {/* ─── 发起任务 Modal：设计稿 task-unified taskModal（双模式 + sched-box） ─── */}
      {createOpen && (
        <ResModal
          badge={<span className="text-[15px]">▶</span>}
          badgeCls="bg-brand-soft text-brand"
          title={createMode === 'sched' ? '新建定时任务' : '发起任务'}
          kicker="TASK · CREATE"
          onClose={() => { setCreateOpen(false); setActionError(null) }}
          formId="task-create-form"
          smooth
          footer={{
            note: createMode === 'sched'
              ? '保存为调度规则，按 cron 自动产生执行实例'
              : '提交后立即执行，任务卡出现在执行看板',
            actions: (
              <>
                <button type="button" className="af-btn af-btn-ghost" onClick={() => { setCreateOpen(false); setActionError(null) }}>取消</button>
                <button
                  type="submit"
                  form="task-create-form"
                  disabled={!newTask.entryId || createTask.isPending || createScheduleM.isPending || wfDetailLoading || (hasInputVariables && !inputValid)}
                  className="af-btn af-btn-primary disabled:opacity-40 flex items-center gap-2"
                >
                  {(createTask.isPending || createScheduleM.isPending) && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                  {createMode === 'sched' ? '保存调度' : '立即执行'}
                </button>
              </>
            ),
          }}
        >
          <form id="task-create-form" onSubmit={handleCreateSubmit}>
            {/* agent 目标时隐藏（entryId 已被 target 选择器写为 agent id，两套选择器共享会互踩） */}
            {target?.kind !== 'agent' && (
            <ResField label="工作流（已发布）" required>
              <select
                value={newTask.entryId}
                onChange={(e) => setNewTask({ ...newTask, entryId: e.target.value })}
                className="w-full border-0 border-b border-line-strong bg-transparent px-0 py-[7px] text-[13px] text-ink outline-none transition-colors focus:border-b-brand cursor-pointer"
              >
                <option value="">— 选择工作流 —</option>
                {workflows.map((wf) => (
                  <option key={wf._id} value={wf._id}>
                    {`${wf.name} (v${wf.version})${wf.has_human_node ? ' · 含人工节点' : ''}`}
                  </option>
                ))}
              </select>
              {workflows.length === 0 && (
                <div className="text-[10.5px] text-sig-wait mt-1.5">暂无已发布工作流，请先在工作流页面发布一个。</div>
              )}
            </ResField>
            )}

            {/* 执行参数：随目标类型/工作流联动弹出 */}
            {!target ? (
              <div className="text-[10.5px] text-ink-faint -mt-2 mb-4">选择目标后填写执行参数</div>
            ) : target.kind === 'agent' ? (
              <ResField label="任务指令" required hint="描述要让这个 Agent 完成什么">
                <UTextarea rows={2} required value={newTask.input} onChange={(e) => setNewTask({ ...newTask, input: e.target.value })} placeholder="如：整理本周的销售数据并输出摘要报告" />
              </ResField>
            ) : wfDetailLoading ? (
              <div className="flex items-center gap-2 text-xs text-ink-dim min-h-[64px]">
                <Loader2 className="w-3.5 h-3.5 animate-spin" /> 加载工作流输入参数…
              </div>
            ) : hasInputVariables ? (
              <ResField label="执行参数" optional="按目标声明动态生成">
                <WorkflowInputForm
                  variables={inputVariables}
                  value={inputValues}
                  onChange={setInputValues}
                  onValidityChange={(v) => setInputValid(v)}
                  showErrors={inputTouched}
                />
              </ResField>
            ) : (
              <ResField label="任务输入" optional="prompt，可选">
                <UTextarea rows={2} value={newTask.input} onChange={(e) => setNewTask({ ...newTask, input: e.target.value })} placeholder="任务的初始输入…" />
              </ResField>
            )}

            <ResField label="触发方式" required>
              <Seg
                className="w-full"
                value={createMode}
                onChange={(v) => { setCreateMode(v); setActionError(null) }}
                options={[{ value: 'immediate', label: '立即执行' }, { value: 'sched', label: '定时调度' }]}
              />
            </ResField>
            {/* 定时调度配置（设计稿 sched-box）：重复 select + 动态行 + 靛蓝预览条
                agent 目标：调度规则(triggers)绑定 workflow，仅支持单次定时——精简为时间选择 */}
            {createMode === 'sched' && target?.kind === 'agent' && (
              <div className="border border-line rounded-[11px] px-4 py-3.5 mt-1">
                <div className="flex items-center gap-2.5">
                  <span className="w-[44px] text-[11.5px] text-ink-dim font-semibold shrink-0">时间</span>
                  <input type="datetime-local" value={schedOnceAt} onChange={(e) => setSchedOnceAt(e.target.value)}
                    className="w-[220px] border-0 border-b border-line-strong bg-transparent px-0 py-[5px] text-[12.5px] text-ink outline-none font-mono focus:border-b-brand" />
                </div>
                <div className="flex items-center gap-3.5 mt-3 px-[13px] py-2.5 bg-brand-soft rounded-[9px]">
                  <span className="text-xs text-brand font-semibold">到时由 Agent 后台执行一次，任务卡出现在执行看板</span>
                </div>
              </div>
            )}
            {createMode === 'sched' && target?.kind !== 'agent' && (
              <div className="border border-line rounded-[11px] px-4 py-3.5 mt-1">
                <div className="flex items-center gap-2.5 mb-3">
                  <span className="w-[44px] text-[11.5px] text-ink-dim font-semibold shrink-0">重复</span>
                  <select
                    value={schedFreq}
                    onChange={(e) => setSchedFreq(e.target.value as typeof schedFreq)}
                    className="flex-1 border-0 border-b border-line-strong bg-transparent px-0 py-[5px] text-[12.5px] text-ink outline-none cursor-pointer focus:border-b-brand"
                  >
                    {(Object.keys(SCHED_FREQ_LABEL) as (typeof schedFreq)[]).map((f) => (
                      <option key={f} value={f}>{SCHED_FREQ_LABEL[f]}</option>
                    ))}
                  </select>
                </div>
                {schedFreq === 'weekly' && (
                  <div className="flex items-center gap-2.5 mb-3">
                    <span className="w-[44px] text-[11.5px] text-ink-dim font-semibold shrink-0">星期</span>
                    <div className="flex gap-1.5">
                      {DOW_LABEL.map((d, i) => (
                        <button
                          key={i}
                          type="button"
                          onClick={() => setSchedDow(i)}
                          className={`w-[30px] h-[30px] rounded-lg border-[1.5px] text-[11px] cursor-pointer transition-colors ${
                            schedDow === i ? 'border-brand bg-brand-soft text-brand font-bold' : 'border-line text-ink-dim hover:text-ink'
                          }`}
                        >
                          {d.replace('周', '')}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
                {schedFreq === 'monthly' && (
                  <div className="flex items-center gap-2.5 mb-3">
                    <span className="w-[44px] text-[11.5px] text-ink-dim font-semibold shrink-0">日期</span>
                    <input type="number" min={1} max={28} value={schedDom} onChange={(e) => setSchedDom(Number(e.target.value))}
                      className="w-[120px] border-0 border-b border-line-strong bg-transparent px-0 py-[5px] text-[12.5px] text-ink outline-none focus:border-b-brand" />
                    <span className="text-[11px] text-ink-faint">号</span>
                  </div>
                )}
                {schedFreq === 'hourly' && (
                  <div className="flex items-center gap-2.5 mb-3">
                    <span className="w-[44px] text-[11.5px] text-ink-dim font-semibold shrink-0">间隔</span>
                    <input type="number" min={1} max={23} value={schedEvery} onChange={(e) => setSchedEvery(Number(e.target.value))}
                      className="w-[120px] border-0 border-b border-line-strong bg-transparent px-0 py-[5px] text-[12.5px] text-ink outline-none focus:border-b-brand" />
                    <span className="text-[11px] text-ink-faint">小时</span>
                  </div>
                )}
                {(schedFreq === 'daily' || schedFreq === 'weekly' || schedFreq === 'monthly') && (
                  <div className="flex items-center gap-2.5">
                    <span className="w-[44px] text-[11.5px] text-ink-dim font-semibold shrink-0">时间</span>
                    <input type="time" value={schedTime} onChange={(e) => setSchedTime(e.target.value)}
                      className="w-[120px] border-0 border-b border-line-strong bg-transparent px-0 py-[5px] text-[12.5px] text-ink outline-none font-mono focus:border-b-brand" />
                    <span className="text-[11px] text-ink-faint">自动产生一个执行实例</span>
                  </div>
                )}
                {schedFreq === 'once' && (
                  <div className="flex items-center gap-2.5">
                    <span className="w-[44px] text-[11.5px] text-ink-dim font-semibold shrink-0">时间</span>
                    <input type="datetime-local" value={schedOnceAt} onChange={(e) => setSchedOnceAt(e.target.value)}
                      className="w-[220px] border-0 border-b border-line-strong bg-transparent px-0 py-[5px] text-[12.5px] text-ink outline-none font-mono focus:border-b-brand" />
                  </div>
                )}
                {schedFreq === 'adv' && (
                  <div className="flex items-center gap-2.5">
                    <span className="w-[44px] text-[11.5px] text-ink-dim font-semibold shrink-0">表达式</span>
                    <UInput mono value={cronAdv} onChange={(e) => setCronAdv(e.target.value)} placeholder="0 9 * * *" />
                  </div>
                )}
                {/* 靛蓝预览条（设计稿 sched-preview） */}
                <div className="flex items-center gap-3.5 mt-3 px-[13px] py-2.5 bg-brand-soft rounded-[9px]">
                  <span className="text-xs text-brand font-semibold">
                    {schedFreq === 'once'
                      ? '到时执行一次，任务卡出现在执行看板'
                      : `按 ${schedFreq === 'adv' ? cronAdv : buildCron()} 自动产生执行实例`}
                  </span>
                </div>
              </div>
            )}
          </form>
        </ResModal>
      )}

      {/* ─── 定时任务 新建/编辑 + 执行记录（从 TriggersPage 并入） ─── */}
      <TriggerConfigModal
        open={configModal.open}
        mode={configModal.mode}
        trigger={configModal.trigger}
        workflows={workflows}
        onClose={() => setConfigModal({ open: false, mode: 'create', trigger: null })}
        onSaved={invalidateTriggers}
      />
      {recordsTrigger && (
        <TriggerTaskRecordsModal
          trigger={recordsTrigger}
          workflows={workflows}
          onClose={() => setRecordsTrigger(null)}
          onViewTask={onOpenTaskDetail}
        />
      )}

      {/* ─── 发起任务 Modal：设计稿 task-unified taskModal（双模式 + sched-box） ─── */}
      {createOpen && (
        <ResModal
          badge={<span className="text-[15px]">▶</span>}
          badgeCls="bg-brand-soft text-brand"
          title={createMode === 'sched' ? '新建定时任务' : '发起任务'}
          kicker="TASK · CREATE"
          onClose={() => { setCreateOpen(false); setActionError(null) }}
          formId="task-create-form"
          smooth
          footer={{
            note: createMode === 'sched'
              ? '保存为调度规则，按 cron 自动产生执行实例'
              : '提交后立即执行，任务卡出现在执行看板',
            actions: (
              <>
                <button type="button" className="af-btn af-btn-ghost" onClick={() => { setCreateOpen(false); setActionError(null) }}>取消</button>
                <button
                  type="submit"
                  form="task-create-form"
                  disabled={!newTask.entryId || createTask.isPending || createScheduleM.isPending || wfDetailLoading || (hasInputVariables && !inputValid)}
                  className="af-btn af-btn-primary disabled:opacity-40 flex items-center gap-2"
                >
                  {(createTask.isPending || createScheduleM.isPending) && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                  {createMode === 'sched' ? '保存调度' : '立即执行'}
                </button>
              </>
            ),
          }}
        >
          <form id="task-create-form" onSubmit={handleCreateSubmit}>
            <ResField label="执行目标" required hint="可选已发布工作流，或委派单个 Agent 执行任务">
              {tgtOpen && (
                <>
                <div className="fixed inset-0 z-30" onClick={() => setTgtOpen(false)} />
                <div
                  className="fixed z-40 max-h-[280px] overflow-y-auto scrollbar-custom border border-line rounded-xl shadow-[var(--shadow-pop)] bg-panel p-1.5"
                  style={{ top: tgtPos.top, left: tgtPos.left, width: tgtPos.width }}
                >
                    <div className="px-2 pt-1.5 pb-1 text-[10px] font-bold tracking-[.15em] text-ink-faint">已发布工作流</div>
                    {workflows.map((wf) => (
                      <button
                        key={wf._id}
                        type="button"
                        onClick={() => { setTarget({ kind: 'workflow', id: wf._id, name: wf.name, sub: `工作流 · v${wf.version}` }); setNewTask({ ...newTask, entryId: wf._id }); setTgtOpen(false) }}
                        className={`w-full flex items-center gap-2 px-2 py-1.5 rounded-lg text-left cursor-pointer hover:bg-raise transition-colors ${target?.id === wf._id && target.kind === 'workflow' ? 'bg-brand-soft' : ''}`}
                      >
                        <span className="w-6 h-6 rounded-md bg-brand-soft text-brand flex items-center justify-center text-[10px] shrink-0">⌥</span>
                        <span className="min-w-0 flex-1 text-[12.5px] text-ink truncate">{wf.name}</span>
                        <span className="font-mono text-[9.5px] text-ink-faint shrink-0">v{wf.version}{wf.has_human_node ? ' · 含人工节点' : ''}</span>
                      </button>
                    ))}
                    <div className="px-2 pt-2.5 pb-1 text-[10px] font-bold tracking-[.15em] text-ink-faint border-t border-line mt-1">已发布 Agent</div>
                    {pubAgents.length === 0 && (
                      <div className="px-2 py-1.5 text-[11px] text-ink-faint">暂无已发布 Agent</div>
                    )}
                    {pubAgents.map((a) => (
                      <button
                        key={a.id}
                        type="button"
                        onClick={() => { setTarget({ kind: 'agent', id: a.id, name: a.name, sub: 'Agent · 委派执行' }); setNewTask({ ...newTask, entryId: a.id }); setTgtOpen(false) }}
                        className={`w-full flex items-center gap-2 px-2 py-1.5 rounded-lg text-left cursor-pointer hover:bg-raise transition-colors ${target?.id === a.id && target.kind === 'agent' ? 'bg-brand-soft' : ''}`}
                      >
                        <span className="w-6 h-6 rounded-md bg-[#EEEBF8] text-cat-flow flex items-center justify-center text-[10px] shrink-0 overflow-hidden">A</span>
                        <span className="min-w-0 flex-1 text-[12.5px] text-ink truncate">{a.name}</span>
                        <span className="font-mono text-[9.5px] text-ink-faint shrink-0">Agent</span>
                      </button>
                    ))}
                  </div>
                </>
              )}
              {target ? (
                  /* 已选：tgt-row 展示行（设计稿） */
                  <div
                    onClick={openTgtPicker}
                    className="flex items-center gap-[9px] border-b border-line-strong py-1.5 cursor-pointer focus:outline-none"
                  >
                    <span
                      className={`w-[26px] h-[26px] rounded-lg flex items-center justify-center text-[11px] font-bold text-white shrink-0 ${target.kind === 'agent' ? 'bg-[#6C4FC4]' : 'bg-[#6C4FC4]'}`}
                    >
                      {target.kind === 'agent' ? 'A' : '⌥'}
                    </span>
                    <div className="min-w-0">
                      <div className="text-[13px] font-semibold text-ink truncate">{target.name}</div>
                      <div className="font-mono text-[10px] text-ink-faint">{target.sub}</div>
                    </div>
                    <span className="ml-auto text-[11px] text-brand font-semibold shrink-0">更换 ▾</span>
                  </div>
                ) : (
                  /* 未选：选择入口行 */
                  <button
                    type="button"
                    onClick={openTgtPicker}
                    className="w-full flex items-center gap-[9px] border-b border-line-strong py-1.5 cursor-pointer text-left hover:border-brand transition-colors"
                  >
                    <span className="w-[26px] h-[26px] rounded-lg flex items-center justify-center text-[11px] font-bold bg-raise text-ink-faint shrink-0">?</span>
                    <span className="text-[13px] text-ink-faint">选择工作流或 Agent…</span>
                    <span className="ml-auto text-[11px] text-brand font-semibold shrink-0">选择 ▾</span>
                  </button>
                )}
            </ResField>

            {/* 执行参数：随目标类型/工作流联动弹出 */}
            {!target ? (
              <div className="text-[10.5px] text-ink-faint -mt-2 mb-4">选择目标后填写执行参数</div>
            ) : target.kind === 'agent' ? (
              <ResField label="任务指令" required hint="描述要让这个 Agent 完成什么">
                <UTextarea rows={2} required value={newTask.input} onChange={(e) => setNewTask({ ...newTask, input: e.target.value })} placeholder="如：整理本周的销售数据并输出摘要报告" />
              </ResField>
            ) : wfDetailLoading ? (
              <div className="flex items-center gap-2 text-xs text-ink-dim min-h-[64px]">
                <Loader2 className="w-3.5 h-3.5 animate-spin" /> 加载工作流输入参数…
              </div>
            ) : hasInputVariables ? (
              <ResField label="执行参数" optional="按目标声明动态生成">
                <WorkflowInputForm
                  variables={inputVariables}
                  value={inputValues}
                  onChange={setInputValues}
                  onValidityChange={(v) => setInputValid(v)}
                  showErrors={inputTouched}
                />
              </ResField>
            ) : (
              <ResField label="任务输入" optional="prompt，可选">
                <UTextarea rows={2} value={newTask.input} onChange={(e) => setNewTask({ ...newTask, input: e.target.value })} placeholder="任务的初始输入…" />
              </ResField>
            )}

            {/* 触发方式（设计稿 seg：全宽平分） */}
            <ResField label="触发方式" required>
              <Seg
                className="w-full"
                value={createMode}
                onChange={(v) => { setCreateMode(v); setActionError(null) }}
                options={[{ value: 'immediate', label: '立即执行' }, { value: 'sched', label: '定时调度' }]}
              />
            </ResField>

            {/* 定时调度配置（设计稿 sched-box）：重复 select + 动态行 + 靛蓝预览条 */}
            {createMode === 'sched' && (
              <div className="border border-line rounded-[11px] px-4 py-3.5 mt-1">
                <div className="flex items-center gap-2.5 mb-3">
                  <span className="w-[44px] text-[11.5px] text-ink-dim font-semibold shrink-0">重复</span>
                  <select
                    value={schedFreq}
                    onChange={(e) => setSchedFreq(e.target.value as typeof schedFreq)}
                    className="flex-1 border-0 border-b border-line-strong bg-transparent px-0 py-[5px] text-[12.5px] text-ink outline-none cursor-pointer focus:border-b-brand"
                  >
                    {(Object.keys(SCHED_FREQ_LABEL) as (typeof schedFreq)[]).map((f) => (
                      <option key={f} value={f}>{SCHED_FREQ_LABEL[f]}</option>
                    ))}
                  </select>
                </div>
                {schedFreq === 'weekly' && (
                  <div className="flex items-center gap-2.5 mb-3">
                    <span className="w-[44px] text-[11.5px] text-ink-dim font-semibold shrink-0">星期</span>
                    <div className="flex gap-1.5">
                      {DOW_LABEL.map((d, i) => (
                        <button
                          key={i}
                          type="button"
                          onClick={() => setSchedDow(i)}
                          className={`w-[30px] h-[30px] rounded-lg border-[1.5px] text-[11px] cursor-pointer transition-colors ${
                            schedDow === i ? 'border-brand bg-brand-soft text-brand font-bold' : 'border-line text-ink-dim hover:text-ink'
                          }`}
                        >
                          {d.replace('周', '')}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
                {schedFreq === 'monthly' && (
                  <div className="flex items-center gap-2.5 mb-3">
                    <span className="w-[44px] text-[11.5px] text-ink-dim font-semibold shrink-0">日期</span>
                    <input type="number" min={1} max={28} value={schedDom} onChange={(e) => setSchedDom(Number(e.target.value))}
                      className="w-[120px] border-0 border-b border-line-strong bg-transparent px-0 py-[5px] text-[12.5px] text-ink outline-none focus:border-b-brand" />
                    <span className="text-[11px] text-ink-faint">号</span>
                  </div>
                )}
                {schedFreq === 'hourly' && (
                  <div className="flex items-center gap-2.5 mb-3">
                    <span className="w-[44px] text-[11.5px] text-ink-dim font-semibold shrink-0">间隔</span>
                    <input type="number" min={1} max={23} value={schedEvery} onChange={(e) => setSchedEvery(Number(e.target.value))}
                      className="w-[120px] border-0 border-b border-line-strong bg-transparent px-0 py-[5px] text-[12.5px] text-ink outline-none focus:border-b-brand" />
                    <span className="text-[11px] text-ink-faint">小时</span>
                  </div>
                )}
                {(schedFreq === 'daily' || schedFreq === 'weekly' || schedFreq === 'monthly') && (
                  <div className="flex items-center gap-2.5">
                    <span className="w-[44px] text-[11.5px] text-ink-dim font-semibold shrink-0">时间</span>
                    <input type="time" value={schedTime} onChange={(e) => setSchedTime(e.target.value)}
                      className="w-[120px] border-0 border-b border-line-strong bg-transparent px-0 py-[5px] text-[12.5px] text-ink outline-none font-mono focus:border-b-brand" />
                    <span className="text-[11px] text-ink-faint">自动产生一个执行实例</span>
                  </div>
                )}
                {schedFreq === 'once' && (
                  <div className="flex items-center gap-2.5">
                    <span className="w-[44px] text-[11.5px] text-ink-dim font-semibold shrink-0">时间</span>
                    <input type="datetime-local" value={schedOnceAt} onChange={(e) => setSchedOnceAt(e.target.value)}
                      className="w-[220px] border-0 border-b border-line-strong bg-transparent px-0 py-[5px] text-[12.5px] text-ink outline-none font-mono focus:border-b-brand" />
                  </div>
                )}
                {schedFreq === 'adv' && (
                  <div className="flex items-center gap-2.5">
                    <span className="w-[44px] text-[11.5px] text-ink-dim font-semibold shrink-0">表达式</span>
                    <UInput mono value={cronAdv} onChange={(e) => setCronAdv(e.target.value)} placeholder="0 9 * * *" />
                  </div>
                )}
                <div className="flex items-center gap-3.5 mt-3 px-[13px] py-2.5 bg-brand-soft rounded-[9px]">
                  <span className="text-xs text-brand font-semibold">
                    {schedFreq === 'once'
                      ? '到时执行一次，任务卡出现在执行看板'
                      : `按 ${schedFreq === 'adv' ? cronAdv : buildCron()} 自动产生执行实例`}
                  </span>
                </div>
              </div>
            )}
          </form>
        </ResModal>
      )}
    </div>
  )
}

/* ─── debounce hook（纯前端，避免引入额外依赖） ─── */
/** 下次执行倒计时：分钟级 → 「32 分钟」/「2 小时」/「3 天」（设计稿 next 大数字） */
function formatCountdown(iso: string): string {
  const diff = new Date(iso).getTime() - Date.now()
  if (Number.isNaN(diff) || diff <= 0) return '即将'
  const min = Math.floor(diff / 60000)
  if (min < 60) return `${min} 分钟`
  const hr = Math.floor(min / 60)
  if (hr < 24) return `${hr} 小时`
  return `${Math.floor(hr / 24)} 天`
}

function useDebouncedValue<T>(value: T, delay: number): T {
  const [debounced, setDebounced] = useState(value)
  useMemo(() => {
    const id = setTimeout(() => setDebounced(value), delay)
    return () => clearTimeout(id)
  }, [value, delay])
  return debounced
}

/** 调度卡最近 7 次执行点阵（设计稿 dots7）：per-trigger 拉最近任务状态 */
function TriggerDots({ triggerId }: { triggerId: string }) {
  const { data } = useQuery({
    queryKey: ['trigger-dots', triggerId],
    queryFn: () => tasksApi.list({ trigger_id: triggerId, page: 1, page_size: 7 }),
    staleTime: 60_000,
  })
  const items = (data?.items ?? []).slice(0, 7).reverse()
  const dotCls = (st: TaskStatusValue) =>
    st === 'completed' ? 'bg-sig-ok' : st === 'failed' ? 'bg-sig-fail' : st === 'cancelled' ? 'bg-line-strong' : 'bg-sig-wait'
  return (
    <div className="flex items-center gap-1">
      {Array.from({ length: 7 }).map((_, i) => {
        const it = items[i]
        return <span key={i} className={`w-[9px] h-[9px] rounded-full ${it ? dotCls(it.status) : 'bg-raise'}`} />
      })}
    </div>
  )
}