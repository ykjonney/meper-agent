/**
 * SystemPromptManager — 多提示词模板管理器。
 *
 * 替代原有的巨大 TextArea，改为列表 + 弹框的形式：
 * - 显示当前活跃提示词的名称
 * - 点击打开模态框进行编辑
 * - 支持创建多个提示词模板，同时只能启用一个
 */
import { useState } from 'react'
import { Button, Input, Modal, Typography, Empty } from 'antd'
import { PlusOutlined, EditOutlined, CheckOutlined } from '@ant-design/icons'
import type { SavedPrompt } from '../services/agent-api'

const { Text } = Typography
const { TextArea } = Input

/* ─── Props ─── */
export interface SystemPromptManagerProps {
  /** 当前活跃提示词内容 */
  value: string
  /** 所有保存的提示词模板 */
  prompts: SavedPrompt[]
  /** 通知父组件更新外部状态 */
  onChange: (value: string, prompts: SavedPrompt[]) => void
}

/** 生成简易 ID */
let _counter = 0
function uid(): string {
  _counter += 1
  return `prompt_${Date.now()}_${_counter}`
}

export default function SystemPromptManager({
  value,
  prompts,
  onChange,
}: SystemPromptManagerProps) {
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState<SavedPrompt | null>(null)

  const activePrompt = prompts.find((p) => p.is_active)
  const activeName = activePrompt?.name ?? 'default'

  /* ─── Modal handlers ─── */

  const handleOpen = () => {
    setEditing(null)
    setOpen(true)
  }

  const handleClose = () => {
    setEditing(null)
    setOpen(false)
  }

  /** 选择一个提示词设为 active */
  const handleSelect = (prompt: SavedPrompt) => {
    const next = prompts.map((p) => ({
      ...p,
      is_active: p.id === prompt.id,
    }))
    onChange(prompt.content, next)
  }

  /** 保存当前编辑中的提示词 */
  const handleSaveEditing = () => {
    if (!editing) return
    const existing = prompts.find((p) => p.id === editing.id)
    let next: SavedPrompt[]
    if (existing) {
      next = prompts.map((p) => (p.id === editing.id ? { ...editing } : p))
    } else {
      next = [...prompts, { ...editing, is_active: prompts.length === 0 }]
    }
    // 如果编辑的是活跃提示词，同步更新 value
    const active = next.find((p) => p.is_active)
    onChange(active?.content ?? editing.content, next)
    setEditing(null)
  }

  /** 新建提示词模板（清空编辑内容） */
  const handleAdd = () => {
    setEditing({ id: uid(), name: '', content: '', is_active: false })
  }

  /** 删除提示词 */
  const handleDelete = (promptId: string) => {
    const target = prompts.find((p) => p.id === promptId)
    const next = prompts.filter((p) => p.id !== promptId)
    // 如果删除了活跃提示词，激活第一个
    if (target?.is_active && next.length > 0) {
      next[0] = { ...next[0], is_active: true }
    }
    const active = next.find((p) => p.is_active)
    onChange(active?.content ?? '', next)
  }

  return (
    <>
      {/* ─── 紧凑展示 ─── */}
      <div
        className="flex items-center justify-between px-3 py-2 border border-[#E2E8F0] rounded-lg cursor-pointer hover:border-[#3B82F6] transition-colors group"
        onClick={handleOpen}
      >
        <div className="flex items-center gap-2 min-w-0">
          <Text className="text-sm text-[#0F172A] truncate">
            {value ? activeName : <span className="text-[#94A3B8]">未设置提示词</span>}
          </Text>
          {prompts.length > 1 && (
            <Text className="text-[11px] text-[#94A3B8] shrink-0">
              （{prompts.length} 个模板）
            </Text>
          )}
        </div>
        <EditOutlined className="text-[#94A3B8] text-sm group-hover:text-[#3B82F6] transition-colors shrink-0" />
      </div>

      {/* ─── 编辑模态框 ─── */}
      <Modal
        title="管理系统提示词"
        open={open}
        onCancel={handleClose}
        footer={null}
        width={640}
        destroyOnClose
      >
        {editing ? (
          /* ── 编辑单个提示词 ── */
          <div className="flex flex-col gap-3">
            <div>
              <label className="block text-sm text-[#0F172A] mb-1">名称</label>
              <Input
                placeholder="提示词模板名称"
                value={editing.name}
                onChange={(e) => setEditing({ ...editing, name: e.target.value })}
              />
            </div>
            <div>
              <label className="block text-sm text-[#0F172A] mb-1">内容</label>
              <TextArea
                placeholder="输入系统提示词..."
                value={editing.content}
                onChange={(e) => setEditing({ ...editing, content: e.target.value })}
                rows={10}
                maxLength={10000}
                showCount
              />
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <Button onClick={() => setEditing(null)}>取消</Button>
              <Button type="primary" onClick={handleSaveEditing}>
                保存
              </Button>
            </div>
          </div>
        ) : (
          /* ── 模板列表 ── */
          <div className="flex flex-col gap-3">
            <div className="max-h-[320px] overflow-y-auto flex flex-col gap-2">
              {prompts.length === 0 ? (
                <Empty
                  description="暂无提示词模板"
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                />
              ) : prompts.map((p) => (
                <div
                  key={p.id}
                  className={`flex items-center justify-between px-3 py-2 rounded-lg border transition-colors ${
                    p.is_active
                      ? 'border-[#3B82F6] bg-[#EFF6FF]'
                      : 'border-[#E2E8F0] hover:border-[#94A3B8]'
                  }`}
                >
                  <div className="flex items-center gap-2 min-w-0">
                    <Text strong className="text-sm text-[#0F172A] truncate">
                      {p.name || '未命名'}
                    </Text>
                    {p.is_active && (
                      <Text className="text-[11px] text-[#3B82F6] shrink-0">当前使用</Text>
                    )}
                  </div>
                  <div className="flex items-center gap-1 shrink-0">
                    {!p.is_active && (
                      <Button
                        type="text"
                        size="small"
                        icon={<CheckOutlined />}
                        onClick={() => handleSelect(p)}
                      />
                    )}
                    <Button
                      type="text"
                      size="small"
                      icon={<EditOutlined />}
                      onClick={() => setEditing({ ...p })}
                    />
                    <Button
                      type="text"
                      size="small"
                      danger
                      onClick={() => handleDelete(p.id)}
                    >
                      删除
                    </Button>
                  </div>
                </div>
              ))}
            </div>

            <Button
              type="dashed"
              block
              icon={<PlusOutlined />}
              onClick={handleAdd}
            >
              新建提示词模板
            </Button>
          </div>
        )}
      </Modal>
    </>
  )
}
