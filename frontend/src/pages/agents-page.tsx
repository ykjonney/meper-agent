/**
 * Agents page — manage AI agents with lifecycle status.
 *
 * Powered by TanStack Query + agent-api.ts service.
 * Backend contract: snake_case fields, paginated list.
 *
 * Features:
 * - Agent list with search, status filter, and stats
 * - Create agent → auto-redirect to detail page
 * - Publish / Archive lifecycle management
 * - Duplicate with automatic naming
 */
import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Button, Tag, Select, Tooltip, message, Spin, Modal, Input } from 'antd'
import {
  PlusOutlined,
  SearchOutlined,
  RobotOutlined,
  CopyOutlined,
  DeleteOutlined,
  InboxOutlined,
  CloudUploadOutlined,
  StopOutlined,
} from '@ant-design/icons'
import { useTheme } from '../contexts/ThemeContext'
import {
  agentApi,
  agentKeys,
  type Agent,
  type AgentStatus,
} from '../services/agent-api'
import { AGENT_STATUS_STYLES } from '../constants/agent-status'

/* ─── Status mappings ─── */
const STATUS_STYLES = AGENT_STATUS_STYLES

/* ─── Debounce hook ─── */
function useDebouncedValue<T>(value: T, delay = 300): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay)
    return () => clearTimeout(timer)
  }, [value, delay])
  return debounced
}

export default function AgentsPage() {
  const { t } = useTheme()
  const queryClient = useQueryClient()
  const navigate = useNavigate()

  /* ─── Filter state ─── */
  const [searchInput, setSearchInput] = useState('')
  const [statusFilter, setStatusFilter] = useState<string>('all')
  const debouncedSearch = useDebouncedValue(searchInput, 300)

  /* ─── Create modal state ─── */
  const [createOpen, setCreateOpen] = useState(false)
  const [createName, setCreateName] = useState('')
  const [createDesc, setCreateDesc] = useState('')
  const [creating, setCreating] = useState(false)

  /* ─── Query: agent list ─── */
  const queryParams = {
    page: 1,
    page_size: 50,
    ...(debouncedSearch ? { name: debouncedSearch } : {}),
    ...(statusFilter !== 'all' ? { status: statusFilter as AgentStatus } : {}),
  }

  const {
    data,
    isLoading,
    isError,
    error,
  } = useQuery({
    queryKey: agentKeys.list(queryParams),
    queryFn: () => agentApi.list(queryParams),
  })

  const agents = data?.items ?? []
  const total = data?.total ?? 0

  /* ─── Mutation: delete agent ─── */
  const deleteMutation = useMutation({
    mutationFn: agentApi.remove,
    onSuccess: () => {
      message.success('Agent 已删除')
      queryClient.invalidateQueries({ queryKey: agentKeys.lists() })
    },
    onError: (err: unknown) => {
      const msg = err && typeof err === 'object' && 'message' in err
        ? (err as { message: string }).message
        : '删除失败'
      message.error(msg)
    },
  })

  /* ─── Mutation: duplicate agent ─── */
  const duplicateMutation = useMutation({
    mutationFn: agentApi.duplicate,
    onSuccess: () => {
      message.success('Agent 已复制')
      queryClient.invalidateQueries({ queryKey: agentKeys.lists() })
    },
    onError: (err: unknown) => {
      const msg = err && typeof err === 'object' && 'message' in err
        ? (err as { message: string }).message
        : '复制失败'
      message.error(msg)
    },
  })

  /* ─── Mutation: publish agent ─── */
  const publishMutation = useMutation({
    mutationFn: agentApi.publish,
    onSuccess: () => {
      message.success('Agent 已发布')
      queryClient.invalidateQueries({ queryKey: agentKeys.lists() })
    },
    onError: (err: unknown) => {
      const msg = err && typeof err === 'object' && 'message' in err
        ? (err as { message: string }).message : '发布失败'
      message.error(msg)
    },
  })

  /* ─── Mutation: archive agent ─── */
  const archiveMutation = useMutation({
    mutationFn: agentApi.archive,
    onSuccess: () => {
      message.success('Agent 已下架')
      queryClient.invalidateQueries({ queryKey: agentKeys.lists() })
    },
    onError: (err: unknown) => {
      const msg = err && typeof err === 'object' && 'message' in err
        ? (err as { message: string }).message : '下架失败'
      message.error(msg)
    },
  })

  /* ─── Actions ─── */
  const handleCreate = () => {
    setCreateName('')
    setCreateDesc('')
    setCreating(false)
    setCreateOpen(true)
  }

  const handleCreateSubmit = async () => {
    if (!createName.trim()) {
      message.warning('请输入 Agent 名称')
      return
    }
    setCreating(true)
    try {
      const newAgent = await agentApi.create({
        name: createName.trim(),
        description: createDesc.trim(),
      })
      message.success('Agent 创建成功')
      queryClient.invalidateQueries({ queryKey: agentKeys.lists() })
      setCreateOpen(false)
      navigate(`/agents/${newAgent.id}`)
    } catch (err: unknown) {
      const msg = err && typeof err === 'object' && 'message' in err
        ? (err as { message: string }).message : '创建失败'
      message.error(msg)
    } finally {
      setCreating(false)
    }
  }

  const handleDelete = (agent: Agent) => {
    Modal.confirm({
      title: '确认删除',
      content: `确定要删除 Agent「${agent.name}」吗？此操作不可恢复。`,
      okText: '删除',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: () => deleteMutation.mutate(agent.id),
    })
  }

  const handleDuplicate = (agent: Agent) => {
    Modal.confirm({
      title: '确认复制',
      content: `确定要复制 Agent「${agent.name}」吗？将创建一个新的草稿 Agent。`,
      okText: '复制',
      cancelText: '取消',
      onOk: () => duplicateMutation.mutate(agent.id),
    })
  }

  const handlePublish = (agent: Agent) => {
    Modal.confirm({
      title: '确认发布',
      content: `确定要发布 Agent「${agent.name}」吗？发布后将出现在对话测试面板中。`,
      okText: '发布',
      cancelText: '取消',
      onOk: () => publishMutation.mutate(agent.id),
    })
  }

  const handleArchive = (agent: Agent) => {
    Modal.confirm({
      title: '确认下架',
      content: `确定要下架 Agent「${agent.name}」吗？下架后新对话将无法使用此 Agent。`,
      okText: '下架',
      okButtonProps: { danger: true },
      cancelText: '取消',
      onOk: () => archiveMutation.mutate(agent.id),
    })
  }

  /* ─── Helper: model display ─── */
  const getModelDisplay = (agent: Agent): string => {
    const modelRef = agent.llm_config?.default_model
    if (!modelRef) return '未配置'
    return modelRef
  }

  /* ─── Stats ─── */
  const stats = [
    { label: '全部 Agent', value: total.toString() },
    { label: '已发布（当前页）', value: agents.filter(a => a.status === 'published').length.toString() },
    { label: '草稿（当前页）', value: agents.filter(a => a.status === 'draft').length.toString() },
    { label: '已归档（当前页）', value: agents.filter(a => a.status === 'archived').length.toString() },
  ]

  /* ─── Format relative time ─── */
  function formatTime(iso: string) {
    if (!iso) return '-'
    const diff = Date.now() - new Date(iso).getTime()
    const mins = Math.floor(diff / 60000)
    if (mins < 1) return '刚刚'
    if (mins < 60) return `${mins} 分钟前`
    const hours = Math.floor(mins / 60)
    if (hours < 24) return `${hours} 小时前`
    return `${Math.floor(hours / 24)} 天前`
  }

  return (
    <div className="animate-[fadeIn_0.3s_ease-out]">
      {/* Header actions */}
      <div className="flex items-center justify-between gap-4 mb-6">
        <div className="flex items-center gap-3">
          <div className="relative">
            <SearchOutlined className="absolute left-3 top-1/2 -translate-y-1/2 text-[#94A3B8] text-sm" />
            <input
              type="text"
              placeholder="搜索 Agent..."
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              className="pl-9 pr-4 py-2 rounded-lg border border-gray-200 text-sm focus:outline-none focus:ring-2 w-64"
              style={{ '--tw-ring-color': t.bg } as React.CSSProperties}
            />
          </div>
          <Select
            value={statusFilter}
            onChange={setStatusFilter}
            className="w-28"
            options={[
              { value: 'all', label: '全部' },
              { value: 'published', label: '已发布' },
              { value: 'draft', label: '草稿' },
              { value: 'archived', label: '已归档' },
            ]}
          />
        </div>
        <Button type="primary" icon={<PlusOutlined />} onClick={handleCreate}>
          新建 Agent
        </Button>
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-4 gap-4 mb-6">
        {stats.map((s) => (
          <div key={s.label} className="rounded-xl border border-gray-200 bg-white p-4">
            <div className="text-2xl font-semibold text-[#0F172A] mb-0.5">
              {isLoading ? <Spin size="small" /> : s.value}
            </div>
            <div className="text-xs text-[#64748B]">{s.label}</div>
          </div>
        ))}
      </div>

      {/* Loading state */}
      {isLoading && (
        <div className="flex items-center justify-center py-20">
          <Spin size="large" tip="加载中..." />
        </div>
      )}

      {/* Error state */}
      {isError && !isLoading && (
        <div className="flex flex-col items-center justify-center py-20 text-[#94A3B8]">
          <InboxOutlined className="text-4xl mb-3" />
          <p className="text-sm">
            {error && typeof error === 'object' && 'message' in error
              ? (error as { message: string }).message
              : '加载失败，请稍后重试'}
          </p>
        </div>
      )}

      {/* Empty state */}
      {!isLoading && !isError && agents.length === 0 && (
        <div className="flex flex-col items-center justify-center py-20 text-[#94A3B8]">
          <InboxOutlined className="text-4xl mb-3" />
          <p className="text-sm">暂无 Agent，点击右上角「新建 Agent」开始创建</p>
        </div>
      )}

      {/* Agent cards */}
      {!isLoading && !isError && agents.length > 0 && (
        <div className="grid grid-cols-3 gap-4">
          {agents.map((agent) => {
            const ss = STATUS_STYLES[agent.status] ?? STATUS_STYLES.draft
            const modelLabel = getModelDisplay(agent)
            const canPublish = agent.status === 'draft' || agent.status === 'archived'
            const canArchive = agent.status === 'published'
            return (
              <div
                key={agent.id}
                onClick={() => navigate(`/agents/${agent.id}`)}
                className="rounded-xl border border-gray-200 bg-white p-5 hover:shadow-sm transition-all duration-200 cursor-pointer"
              >
                {/* Header row */}
                <div className="flex items-start justify-between mb-3">
                  <div className="flex items-center gap-3 min-w-0">
                    <div className="w-10 h-10 rounded-lg flex items-center justify-center text-base shrink-0" style={{ background: t.bg, color: t.primary }}>
                      <RobotOutlined />
                    </div>
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-medium text-[#0F172A] truncate">{agent.name}</span>
                      </div>
                      <div className="text-xs text-[#64748B] truncate max-w-[200px]">{agent.description || '暂无描述'}</div>
                    </div>
                  </div>
                </div>

                {/* Model & status tags */}
                <div className="flex items-center gap-2 mb-3 flex-wrap">
                  <Tag className="!m-0 !px-2 !py-0.5 !text-[11px] !rounded" style={{ color: t.primary, background: t.bg, borderColor: 'transparent' }}>
                    {modelLabel}
                  </Tag>
                  <Tag className="!m-0 !px-2 !py-0.5 !text-[11px] !rounded" style={{ color: ss.color, background: ss.bg, borderColor: 'transparent' }}>
                    {ss.label}
                  </Tag>
                  {agent.skill_ids && agent.skill_ids.length > 0 && (
                    <Tag className="!m-0 !px-2 !py-0.5 !text-[11px] !rounded" style={{ color: '#3B82F6', background: '#EFF6FF', borderColor: 'transparent' }}>
                      {agent.skill_ids.length} Skill
                    </Tag>
                  )}
                  {agent.builtin_config && agent.builtin_config.length > 0 && (
                    <Tag className="!m-0 !px-2 !py-0.5 !text-[11px] !rounded" style={{ color: '#F59E0B', background: '#FFFBEB', borderColor: 'transparent' }}>
                      {agent.builtin_config.length} Built-in
                    </Tag>
                  )}
                  {agent.mcp_connection_ids && agent.mcp_connection_ids.length > 0 && (
                    <Tag className="!m-0 !px-2 !py-0.5 !text-[11px] !rounded" style={{ color: '#10B981', background: '#ECFDF5', borderColor: 'transparent' }}>
                      {agent.mcp_connection_ids.length} MCP
                    </Tag>
                  )}
                </div>

                {/* Footer: time + actions */}
                <div className="flex items-center justify-between pt-3 border-t border-gray-50">
                  <span className="text-[11px] text-[#94A3B8]">{formatTime(agent.updated_at)}</span>
                  <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
                    {canPublish && (
                      <Tooltip title="发布">
                        <button
                          onClick={() => handlePublish(agent)}
                          disabled={publishMutation.isPending}
                          className="border-0 bg-transparent w-7 h-7 flex items-center justify-center rounded text-[#10B981] hover:bg-[#D1FAE5] transition-colors duration-150 text-xs"
                        ><CloudUploadOutlined /></button>
                      </Tooltip>
                    )}
                    {canArchive && (
                      <Tooltip title="下架">
                        <button
                          onClick={() => handleArchive(agent)}
                          disabled={archiveMutation.isPending}
                          className="border-0 bg-transparent w-7 h-7 flex items-center justify-center rounded text-[#F59E0B] hover:bg-[#FEF3C7] transition-colors duration-150 text-xs"
                        ><StopOutlined /></button>
                      </Tooltip>
                    )}
                    <Tooltip title="复制">
                      <button
                        onClick={() => handleDuplicate(agent)}
                        disabled={duplicateMutation.isPending}
                        className="border-0 bg-transparent w-7 h-7 flex items-center justify-center rounded text-[#94A3B8] hover:text-[#0F172A] hover:bg-gray-50 transition-colors duration-150 text-xs"
                      ><CopyOutlined /></button>
                    </Tooltip>
                    <Tooltip title="删除">
                      <button
                        onClick={() => handleDelete(agent)}
                        disabled={deleteMutation.isPending}
                        className="border-0 bg-transparent w-7 h-7 flex items-center justify-center rounded text-[#94A3B8] hover:text-[#EF4444] hover:bg-gray-50 transition-colors duration-150 text-xs"
                      ><DeleteOutlined /></button>
                    </Tooltip>
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      )}

      {/* Create Agent Modal */}
      <Modal
        title="新建 Agent"
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        onOk={handleCreateSubmit}
        okText="创建"
        cancelText="取消"
        confirmLoading={creating}
        okButtonProps={{ disabled: !createName.trim() }}
        destroyOnClose
        width={480}
      >
        <div className="flex flex-col gap-4 py-2">
          <div>
            <label className="block text-sm text-[#0F172A] mb-1.5">
              名称 <span className="text-[#EF4444]">*</span>
            </label>
            <Input
              value={createName}
              onChange={(e) => setCreateName(e.target.value)}
              placeholder="如：客服助手"
              maxLength={100}
              showCount
              autoFocus
            />
          </div>
          <div>
            <label className="block text-sm text-[#0F172A] mb-1.5">
              描述
            </label>
            <Input.TextArea
              value={createDesc}
              onChange={(e) => setCreateDesc(e.target.value)}
              placeholder="简要描述 Agent 的用途"
              maxLength={500}
              showCount
              rows={3}
            />
          </div>
        </div>
      </Modal>
    </div>
  )
}
