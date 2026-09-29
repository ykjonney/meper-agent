/**
 * ChannelConfigModal - 渠道实例配置 Modal，创建/编辑二合一。
 *
 * 平台类型固定（飞书/钉钉，同平台可建多个实例），表单极简：绑定智能体 +
 * 必填凭据字段（飞书 App ID/Secret、钉钉 App Key/Secret，由后端 provider
 * schema 的 required 字段驱动）。其余配置一律代为决定：name 自动取
 * 「平台 · 智能体」、receive_mode 固定长连接（免公网回调），选填凭据不
 * 展示——长连接模式不需要 verification_token/encrypt_key/webhook_url。
 *
 * 编辑模式凭据留空 = 不修改（后端 credentials merge 跳过空值）。
 */
import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Loader2 } from 'lucide-react'
import { Modal, Input, Select } from '../ui'
import { toast } from '../ui/toast'
import { getErrorMessage } from '../../lib/api-client'
import {
  channelsApi,
  channelKeys,
  type Channel,
  type ChannelProvider,
  type CredentialFieldSchema,
} from '../../services/channels-api'
import { agentApi, agentKeys } from '../../services/agent-api'

interface Props {
  open: boolean
  /** 固定渠道槽位：'lark' | 'dingtalk' */
  provider: ChannelProvider
  /** 平台显示名（飞书/钉钉），也用作自动生成的渠道名 */
  label: string
  /** 该槽位已有渠道实例；null = 首次配置（create） */
  channel: Channel | null
  onClose: () => void
  onSaved: () => void
}

/** 平台侧准备步骤引导（Modal 顶部一句话说明，凭据从哪来）。 */
const PROVIDER_GUIDES: Partial<Record<ChannelProvider, string>> = {
  lark:
    '飞书开放平台创建企业自建应用 → 添加「机器人」能力 → 事件与回调选择「使用长连接接收事件」→ 订阅「接收消息 im.message.receive_v1」，然后将 App ID / App Secret 填写到下方。',
  dingtalk:
    '钉钉开放平台创建企业内部应用 → 开启「机器人」→ 消息接收模式选择「Stream 模式」，然后将 App Key / App Secret 填写到下方。',
}

export default function ChannelConfigModal({
  open,
  provider,
  label,
  channel,
  onClose,
  onSaved,
}: Props) {
  const isEdit = !!channel
  const [agentId, setAgentId] = useState('')
  const [credValues, setCredValues] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState(false)

  // provider schema（与页面共享同 query key 缓存）：只渲染 required 凭据字段
  const schemaQuery = useQuery({
    queryKey: channelKeys.schema(),
    queryFn: () => channelsApi.getProviderSchema(),
    enabled: open,
  })
  const requiredFields: CredentialFieldSchema[] =
    (schemaQuery.data?.providers[provider]?.credential_fields ?? []).filter(
      (f) => f.required,
    )

  // 已发布智能体（绑定目标）
  const agentsQuery = useQuery({
    queryKey: agentKeys.list({ page: 1, page_size: 100, status: 'published' }),
    queryFn: () => agentApi.list({ page: 1, page_size: 100, status: 'published' }),
    enabled: open,
  })
  const agents = agentsQuery.data?.items ?? []

  // 打开时初始化：agent 回填当前绑定，凭据清空（留空 = 不修改）
  useEffect(() => {
    if (!open) return
    setAgentId(channel?.agent_id ?? '')
    setCredValues({})
  }, [open, channel])

  const handleSave = async () => {
    if (!agentId) {
      toast.error('请选择绑定的智能体')
      return
    }
    // 仅创建模式强制填凭据；编辑模式留空即沿用
    const credentials: Record<string, string> = {}
    for (const f of requiredFields) {
      const v = (credValues[f.key] ?? '').trim()
      if (!isEdit && !v) {
        toast.error(`请填写 ${f.label}`)
        return
      }
      if (v) credentials[f.key] = v
    }

    setSaving(true)
    try {
      if (isEdit && channel) {
        await channelsApi.update(channel.id, { agent_id: agentId, credentials })
        toast.success('配置已更新')
      } else {
        // 实例名自动生成（平台 · 智能体），用户无需填写；编辑时不改名
        const agentName = agents.find((a) => a.id === agentId)?.name ?? ''
        const name = agentName ? `${label} · ${agentName}` : label
        await channelsApi.create({
          name,
          provider,
          agent_id: agentId,
          credentials,
          receive_mode: 'long_connection',
        })
        toast.success(`${label} 已接入`)
      }
      onSaved()
      onClose()
    } catch (err: unknown) {
      toast.error(getErrorMessage(err, '保存失败'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      open={open}
      title={isEdit ? `${channel?.name ?? label} · 设置` : `接入${label}`}
      onCancel={onClose}
      onOk={handleSave}
      okText={isEdit ? '保存' : '完成配置'}
      cancelText="取消"
      width={480}
      okButtonProps={{ disabled: saving }}
    >
      <div className="space-y-4">
        {/* 平台准备步骤引导 */}
        {PROVIDER_GUIDES[provider] && (
          <div className="rounded-md border border-[#27272a] bg-[#121214] px-3 py-2 text-[11px] leading-relaxed text-slate-400">
            {PROVIDER_GUIDES[provider]}
          </div>
        )}

        {/* 绑定智能体 */}
        <div className="space-y-1.5">
          <div className="text-xs font-medium text-[#fafafa]">绑定智能体</div>
          {agentsQuery.isLoading ? (
            <div className="flex items-center gap-2 text-[11px] text-[#71717a] py-1.5">
              <Loader2 size={13} className="animate-spin" /> 加载智能体...
            </div>
          ) : agents.length === 0 ? (
            <p className="text-[11px] text-amber-400">
              暂无已发布的智能体，请先在「智能体」页创建并发布后再接入。
            </p>
          ) : (
            <Select
              value={agentId || null}
              onChange={(v) => setAgentId(v ?? '')}
              placeholder="选择处理 IM 消息的智能体"
              options={agents.map((a) => ({ value: a.id, label: a.name }))}
            />
          )}
          <p className="text-[10px] text-[#71717a]">
            平台内收到的新消息将由该智能体自动处理并回复。
          </p>
        </div>

        {/* 必填凭据（schema 驱动：飞书 App ID/Secret，钉钉 App Key/Secret） */}
        {schemaQuery.isLoading ? (
          <div className="flex items-center gap-2 text-[11px] text-[#71717a] py-1.5">
            <Loader2 size={13} className="animate-spin" /> 加载配置项...
          </div>
        ) : (
          requiredFields.map((f) => {
            const masked = isEdit ? channel?.credentials?.[f.key] : undefined
            return (
              <div key={f.key} className="space-y-1.5">
                <div className="text-xs font-medium text-[#fafafa]">{f.label}</div>
                <Input
                  type={f.type === 'secret' ? 'password' : 'text'}
                  autoComplete="new-password"
                  value={credValues[f.key] ?? ''}
                  onChange={(e) =>
                    setCredValues((s) => ({ ...s, [f.key]: e.target.value }))
                  }
                  placeholder={
                    masked
                      ? `已配置（${masked}），留空保持不变`
                      : isEdit
                        ? '留空保持不变'
                        : `请输入 ${f.label}`
                  }
                />
              </div>
            )
          })
        )}

        <p className="text-[10px] text-[#71717a]">
          采用长连接模式接入，无需公网回调地址；保存后服务端即刻建立连接。
        </p>
      </div>
    </Modal>
  )
}
