/**
 * AgentConfigDrawer — thin Drawer wrapper around AgentConfigForm.
 *
 * Used in the agents list page for quick create / edit.
 * The actual form logic lives in agent-config-form.tsx.
 */
import { useRef, useState } from 'react'
import { Drawer, Button, Tag } from 'antd'
import { useTheme } from '../contexts/ThemeContext'
import type { Agent } from '../services/agent-api'
import { AGENT_STATUS_STYLES } from '../constants/agent-status'
import AgentConfigForm, { type AgentConfigFormHandle } from './agent-config-form'

/* ─── Status styles ─── */
const STATUS_STYLES = AGENT_STATUS_STYLES

/* ─── Props ─── */
interface AgentConfigDrawerProps {
  agent: Agent | null
  open: boolean
  onClose: () => void
  mode: 'create' | 'edit'
}

export default function AgentConfigDrawer({ agent, open, onClose, mode }: AgentConfigDrawerProps) {
  const { t } = useTheme()
  const formRef = useRef<AgentConfigFormHandle>(null)
  const [isSaving, setIsSaving] = useState(false)
  const isEdit = mode === 'edit' && agent !== null
  const statusStyle = STATUS_STYLES[agent?.status ?? 'draft'] ?? STATUS_STYLES.draft

  return (
    <Drawer
      title={
        <div className="flex items-center gap-2">
          {isEdit ? (
            <>
              <span className="text-base font-medium">{agent?.name ?? '编辑 Agent'}</span>
              <Tag
                className="!m-0 !text-[10px]"
                style={{ color: statusStyle.color, background: statusStyle.bg, borderColor: 'transparent' }}
              >
                {statusStyle.label}
              </Tag>
            </>
          ) : (
            '新建 Agent'
          )}
        </div>
      }
      open={open}
      onClose={onClose}
      width={600}
      destroyOnClose
      footer={
        <div className="flex justify-end gap-2">
          <Button onClick={onClose}>取消</Button>
          <Button
            type="primary"
            onClick={() => formRef.current?.submit()}
            loading={isSaving}
            style={{ background: t.primary, borderColor: t.primary }}
          >
            {isEdit ? '保存修改' : '创建'}
          </Button>
        </div>
      }
    >
      <AgentConfigForm
        ref={formRef}
        agent={agent}
        mode={mode}
        onSaved={onClose}
        onSavingChange={setIsSaving}
      />
    </Drawer>
  )
}
