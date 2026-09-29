/**
 * ChannelsPage - 消息渠道（IM 集成）页（系统设置内「消息渠道」Tab）。
 *
 * 平台类型固定为飞书/钉钉两个分组（无自定义平台），每个平台下可创建
 * 多个渠道实例（如多个飞书应用，各绑一个 agent、独立凭据）。实例配置
 * 走极简表单（见 ChannelConfigModal）：绑定智能体 + 必填凭据，接收模式
 * 固定长连接。
 *
 * 实例状态：运行中（含长连接 已连接●/已断开● 实时状态）/ 已停用 /
 * 已降级（可重置）；支持启用/停用开关、编辑、删除（软删除）。
 * 渠道全局共享；RBAC（判权限不判角色）：页面由 channel:read 门控，
 * 写操作（新增/编辑/启停/重置/删除）需 channel:write——后端同键兜底。
 *
 * 无 theme prop - 明暗由 .theme-light/.theme-dark CSS 作用域处理。
 */
import { useMemo, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Loader2, RotateCcw, Pencil, Trash2, Plus,
} from 'lucide-react'
import {
  channelsApi,
  channelKeys,
  type Channel,
  type ChannelProvider,
} from '../services/channels-api'
import { agentApi, agentKeys } from '../services/agent-api'
import { usePermission } from '../hooks/use-permission'
import { Switch, Tag } from './ui'
import { confirmDialog } from './ui/confirm'
import { toast } from './ui/toast'
import { getErrorMessage } from '../lib/api-client'
import ChannelConfigModal from './channel/ChannelConfigModal'

/** 固定平台分组：显示名 + 分组角标配色（品牌主色近似）。 */
const PROVIDER_GROUPS: {
  provider: ChannelProvider
  label: string
  color: string
}[] = [
  { provider: 'lark', label: '飞书', color: '#3370FF' },
  { provider: 'dingtalk', label: '钉钉', color: '#0089FF' },
]

/** 单个渠道实例行。写操作（启停/重置/编辑/删除）需 channel:write。 */
function ChannelInstanceRow({
  channel,
  agentName,
  onEdit,
}: {
  channel: Channel
  agentName: string | undefined
  onEdit: () => void
}) {
  const queryClient = useQueryClient()
  const canWrite = usePermission('channel:write')

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: channelKeys.lists() })

  const toggleMutation = useMutation({
    mutationFn: (enabled: boolean) =>
      enabled ? channelsApi.enable(channel.id) : channelsApi.disable(channel.id),
    onSuccess: () => invalidate(),
    onError: (e) => toast.error(getErrorMessage(e, '操作失败')),
  })

  const resetMutation = useMutation({
    mutationFn: () => channelsApi.reset(channel.id),
    onSuccess: () => {
      toast.success('已重置')
      invalidate()
    },
    onError: (e) => toast.error(getErrorMessage(e, '重置失败')),
  })

  const deleteMutation = useMutation({
    mutationFn: () => channelsApi.remove(channel.id),
    onSuccess: () => {
      toast.success('已删除')
      invalidate()
    },
    onError: (e) => toast.error(getErrorMessage(e, '删除失败')),
  })

  const handleDelete = async () => {
    const ok = await confirmDialog({
      title: '删除渠道实例',
      description: `删除「${channel.name}」后将断开连接并不再处理该应用的 IM 消息，历史会话记录保留。`,
      okText: '删除',
      danger: true,
    })
    if (ok) deleteMutation.mutate()
  }

  // 状态优先级：降级 > 启用 > 停用
  const degraded = channel.status === 'degraded'
  const connected = channel.connection_status === 'long_connection_connected'
  const disconnected = channel.connection_status === 'long_connection_disconnected'

  return (
    <div className="px-4 py-3 rounded-lg border border-[#27272a] bg-[#18181b] flex items-center gap-4">
      {/* 实例信息 */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-xs font-medium text-[#fafafa] truncate">
            {channel.name}
          </span>
          <Tag color={degraded ? 'warning' : channel.enabled ? 'success' : 'default'}>
            {degraded ? '已降级' : channel.enabled ? '运行中' : '已停用'}
          </Tag>
        </div>
        <div className="flex items-center gap-2 mt-1 text-[11px] text-[#71717a] flex-wrap">
          <span>
            绑定智能体：
            <span className="text-slate-300">{agentName ?? channel.agent_id}</span>
          </span>
          {channel.receive_mode === 'long_connection' ? (
            <span className="flex items-center gap-1.5 text-slate-400">
              <span
                className={`w-1.5 h-1.5 rounded-full ${
                  connected ? 'bg-emerald-400' : disconnected ? 'bg-red-400' : 'bg-[#52525b]'
                }`}
              />
              {connected ? '已连接' : disconnected ? '已断开' : '未启动'}
              {degraded && <span className="text-amber-400 ml-1">连续失败已降级</span>}
            </span>
          ) : (
            <Tag color="blue">Webhook 模式</Tag>
          )}
        </div>
      </div>

      {/* 操作（channel:write 门控——无写权限只读） */}
      {canWrite && (
        <div className="flex items-center gap-1 shrink-0">
          {degraded && (
            <button
              title="清除降级状态并重置失败计数"
              onClick={() => resetMutation.mutate()}
              disabled={resetMutation.isPending}
              className="flex items-center gap-1 h-7 px-2 rounded-md border border-amber-500/40 text-amber-400 text-[11px] hover:bg-amber-500/10 cursor-pointer transition-colors disabled:opacity-50"
            >
              <RotateCcw size={11} /> 重置
            </button>
          )}
          <Switch
            checked={channel.enabled}
            disabled={toggleMutation.isPending}
            size="small"
            onChange={(checked) => toggleMutation.mutate(checked)}
          />
          <button
            title="编辑配置"
            onClick={onEdit}
            className="p-1.5 rounded-lg hover:bg-[#27272a] text-slate-400 hover:text-[#1E5EFF] cursor-pointer transition-colors"
          >
            <Pencil size={14} />
          </button>
          <button
            title="删除"
            onClick={handleDelete}
            disabled={deleteMutation.isPending}
            className="p-1.5 rounded-lg hover:bg-[#27272a] text-slate-400 hover:text-red-400 cursor-pointer transition-colors disabled:opacity-50"
          >
            <Trash2 size={14} />
          </button>
        </div>
      )}
    </div>
  )
}

export function ChannelsPage() {
  const queryClient = useQueryClient()
  const canWrite = usePermission('channel:write')
  // 配置 Modal 目标（null = 关闭；channel=null 为该平台新增实例）
  const [modalTarget, setModalTarget] = useState<{
    provider: ChannelProvider
    label: string
    channel: Channel | null
  } | null>(null)

  // 全量渠道（全局列表，软删除的已过滤；channel:read 门控下均可见）
  const channelsQuery = useQuery({
    queryKey: channelKeys.list({ page: 1, page_size: 100 }),
    queryFn: () => channelsApi.list({ page: 1, page_size: 100 }),
  })
  const channels = channelsQuery.data?.items ?? []

  // provider schema：判断长连接运行时是否可用（分组提示用）
  const schemaQuery = useQuery({
    queryKey: channelKeys.schema(),
    queryFn: () => channelsApi.getProviderSchema(),
  })

  // agent 名解析（status=all：绑定的 agent 可能已下架，仍要能显示名字）
  const agentsQuery = useQuery({
    queryKey: agentKeys.list({ page: 1, page_size: 100, status: 'all' }),
    queryFn: () => agentApi.list({ page: 1, page_size: 100, status: 'all' }),
  })
  const agentNameMap = useMemo(() => {
    const map: Record<string, string> = {}
    for (const a of agentsQuery.data?.items ?? []) map[a.id] = a.name
    return map
  }, [agentsQuery.data])

  // 按固定平台分组
  const grouped = useMemo(() => {
    const map: Record<string, Channel[]> = {}
    for (const c of channels) (map[c.provider] ??= []).push(c)
    return map
  }, [channels])

  const loading = channelsQuery.isLoading

  return (
    <div className="space-y-4">
      {/* Tab 内容说明（页面标题由系统设置 Tab 承担） */}
      <p className="text-[11px] text-[#71717a]">
        接入飞书 / 钉钉，平台内新消息由绑定的智能体自动处理并回复；每个平台可接入多个应用
      </p>

      {/* 平台分组 */}
      {loading ? (
        <div className="flex items-center justify-center py-16 text-[#71717a]">
          <Loader2 size={18} className="animate-spin" />
        </div>
      ) : (
        PROVIDER_GROUPS.map(({ provider, label, color }) => {
          const instances = grouped[provider] ?? []
          const longConnectionAvailable =
            schemaQuery.data?.providers[provider]?.receive_modes.includes(
              'long_connection',
            ) ?? true

          return (
            <section
              key={provider}
              className="rounded-xl border border-[#27272a] bg-[#121214]/40 p-4 space-y-3"
            >
              {/* 分组头：平台标识 + 新增 */}
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2.5">
                  <div
                    className="w-7 h-7 rounded-md flex items-center justify-center text-white text-xs font-bold shrink-0"
                    style={{ backgroundColor: color }}
                  >
                    {label.slice(0, 1)}
                  </div>
                  <div>
                    <span className="text-sm font-semibold text-[#fafafa]">{label}</span>
                    <span className="ml-2 text-[11px] text-[#71717a]">
                      {instances.length > 0 ? `${instances.length} 个实例` : '尚未接入'}
                    </span>
                  </div>
                </div>
                {canWrite && (
                  <button
                    onClick={() => setModalTarget({ provider, label, channel: null })}
                    className="flex items-center gap-1.5 h-7 px-2.5 rounded-md border border-[#27272a] bg-[#18181b] hover:border-[#1E5EFF] hover:text-[#1E5EFF] text-slate-300 text-[11px] font-medium cursor-pointer transition-colors"
                  >
                    <Plus size={12} /> 新增接入
                  </button>
                )}
              </div>

              {/* 实例列表 */}
              {instances.length === 0 ? (
                <p className="text-[11px] text-[#71717a] py-2">
                  点「新增接入」，填写平台应用凭据即可开始——采用长连接，无需公网回调地址。
                </p>
              ) : (
                <div className="space-y-2">
                  {instances.map((channel) => (
                    <ChannelInstanceRow
                      key={channel.id}
                      channel={channel}
                      agentName={agentNameMap[channel.agent_id]}
                      onEdit={() => setModalTarget({ provider, label, channel })}
                    />
                  ))}
                </div>
              )}

              {!longConnectionAvailable && (
                <p className="text-[11px] text-amber-400">
                  当前部署未启用{label}长连接，请联系管理员开启后重新保存配置。
                </p>
              )}
            </section>
          )
        })
      )}

      {/* 配置 Modal（同平台可多次新增） */}
      <ChannelConfigModal
        open={!!modalTarget}
        provider={modalTarget?.provider ?? 'lark'}
        label={modalTarget?.label ?? ''}
        channel={modalTarget?.channel ?? null}
        onClose={() => setModalTarget(null)}
        onSaved={() =>
          queryClient.invalidateQueries({ queryKey: channelKeys.lists() })
        }
      />
    </div>
  )
}

export default ChannelsPage
