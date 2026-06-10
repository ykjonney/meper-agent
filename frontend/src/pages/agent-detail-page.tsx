/**
 * AgentDetailPage — Agent detail workspace with split layout.
 *
 * Route: /agents/:id
 * Layout: left = configuration form, right = chat test panel.
 *
 * Provides an inline editing + testing experience so users can
 * tweak prompts and immediately test them side by side.
 */
import { useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Button, Spin } from 'antd'
import { ArrowLeftOutlined, RobotOutlined } from '@ant-design/icons'
import { useTheme } from '../contexts/ThemeContext'
import {
  agentApi,
  agentKeys,
} from '../services/agent-api'
import AgentConfigForm, { type AgentConfigFormHandle } from '../components/agent-config-form'
import ChatPanel from '../components/chat-panel'

/* ─── Component ─── */

export default function AgentDetailPage() {
  const { t } = useTheme()
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const formRef = useRef<AgentConfigFormHandle>(null)

  /* ─── Query: agent detail ─── */
  const {
    data: agent,
    isLoading,
    isError,
  } = useQuery({
    queryKey: agentKeys.detail(id!),
    queryFn: async () => {
      const res = await agentApi.get(id!)
      return res
    },
    enabled: !!id,
    refetchOnWindowFocus: false,
  })

  /* ─── Loading / error states ─── */
  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full">
        <Spin size="large" />
      </div>
    )
  }

  if (isError || !agent) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-[#94A3B8]">
        <RobotOutlined className="text-4xl mb-3" />
        <p className="text-sm mb-3">Agent 不存在或加载失败</p>
        <Button onClick={() => navigate('/agents')}>返回 Agent 列表</Button>
      </div>
    )
  }

  /* ─── Resolve model label for chat panel ─── */
  const agentModel = agent.llm_config?.default_model ?? ''

  return (
    <div className="animate-[fadeIn_0.3s_ease-out] flex gap-6 h-full">
      {/* ════════ Left: Configuration ════════ */}
      <div className="flex flex-col w-[480px] shrink-0 min-h-0">
        {/* Toolbar */}
        <div className="flex items-center justify-between mb-3 shrink-0">
          <button
            onClick={() => navigate('/agents')}
            className="flex items-center gap-1.5 border-0 bg-transparent text-sm text-[#64748B] hover:text-[#0F172A] transition-colors duration-150 px-0 cursor-pointer"
          >
            <ArrowLeftOutlined className="text-xs" />
            <span>返回列表</span>
          </button>
          <Button
            type="primary"
            onClick={() => formRef.current?.submit()}
            loading={formRef.current?.isSaving()}
            style={{ background: t.primary, borderColor: t.primary }}
          >
            保存
          </Button>
        </div>

        {/* Form (scrollable) */}
        <div className="flex-1 overflow-y-auto rounded-xl border border-gray-200 bg-white p-5 min-h-0">
          <AgentConfigForm
            ref={formRef}
            agent={agent}
            mode="edit"
          />
        </div>
      </div>

      {/* ════════ Right: Chat test ════════ */}
      <div className="flex-1 min-w-0 min-h-0">
        <ChatPanel
          agentId={agent.id}
          agentName={agent.name}
          agentModel={agentModel}
          showSidebar={true}
          className="h-full"
        />
      </div>
    </div>
  )
}
