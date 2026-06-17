/**
 * HumanNodeConfig — 人工审批节点配置面板。
 *
 * options 改为逐条编辑模式：每条包含一个「选项标签」，
 * 与后续 Gateway 节点条件中的 decision 值一一对应。
 * 新增超时动作选择器。
 */
import { useCallback, useMemo } from 'react'
import { Button, Input, Select } from 'antd'
import { PlusOutlined, DeleteOutlined } from '@ant-design/icons'

interface Props {
  config: Record<string, unknown>
  onChange: (c: Record<string, unknown>) => void
}

const TIMEOUT_ACTIONS = [
  { label: '自动通过', value: 'auto_approve' },
  { label: '自动驳回', value: 'auto_reject' },
  { label: '自动跳过', value: 'auto_skip' },
  { label: '标记失败', value: 'fail' },
]

const DEFAULT_OPTIONS: string[] = []

/** 安全提取 options，保证返回 string[] */
function safeOptions(raw: unknown): string[] {
  if (Array.isArray(raw)) return raw.map(String)
  return []
}

export default function HumanNodeConfig({ config, onChange }: Props) {
  const rawOptions = config?.options
  const options = useMemo(() => safeOptions(rawOptions), [rawOptions])

  const updateOptions = useCallback(
    (next: string[]) => onChange({ ...(config ?? {}), options: next }),
    [config, onChange],
  )

  const addOption = useCallback(() => {
    updateOptions([...options, ''])
  }, [options, updateOptions])

  const removeOption = useCallback(
    (idx: number) => {
      updateOptions(options.filter((_, i) => i !== idx))
    },
    [options, updateOptions],
  )

  const updateOption = useCallback(
    (idx: number, value: string) => {
      const next = options.slice()
      next[idx] = value
      updateOptions(next)
    },
    [options, updateOptions],
  )

  return (
    <div className="space-y-3">
      {/* ── 审批标题 ── */}
      <div>
        <label className="block text-xs text-[#64748B] mb-1">审批标题</label>
        <Input
          value={typeof config?.title === 'string' ? config.title : ''}
          onChange={(e) => onChange({ ...(config ?? {}), title: e.target.value })}
          placeholder="请审批以下内容"
        />
      </div>

      {/* ── 审批描述 ── */}
      <div>
        <label className="block text-xs text-[#64748B] mb-1">审批描述</label>
        <Input.TextArea
          value={typeof config?.description === 'string' ? config.description : ''}
          onChange={(e) => onChange({ ...(config ?? {}), description: e.target.value })}
          rows={3}
          placeholder="描述需要人工审批的内容..."
        />
      </div>

      {/* ── 审批选项（逐条编辑） ── */}
      <div>
        <div className="flex items-center justify-between mb-1">
          <label className="text-xs text-[#64748B]">审批选项</label>
          <Button
            size="small"
            type="link"
            icon={<PlusOutlined />}
            onClick={addOption}
          >
            添加选项
          </Button>
        </div>

        {options.length > 0 ? (
          <div className="space-y-1.5">
            {options.map((opt, idx) => (
              <div key={idx} className="flex items-center gap-1.5">
                <Input
                  size="small"
                  value={opt}
                  onChange={(e) => updateOption(idx, e.target.value)}
                  placeholder={`选项 ${idx + 1}，如 approve / reject`}
                  className="flex-1 font-mono"
                />
                <Button
                  size="small"
                  type="text"
                  danger
                  icon={<DeleteOutlined />}
                  onClick={() => removeOption(idx)}
                />
              </div>
            ))}
          </div>
        ) : (
          <div className="text-xs text-[#94A3B8] text-center py-3">
            暂无选项，点击「添加选项」创建
          </div>
        )}

        <div className="text-[10px] text-[#94A3B8] mt-1.5">
          选项值将写入变量 <code className="font-mono">node_id.decision</code>，
          供后续 Gateway 条件分支使用
        </div>
      </div>

      {/* ── 超时时间 ── */}
      <div>
        <label className="block text-xs text-[#64748B] mb-1">超时时间 (分钟)</label>
        <Input
          type="number"
          value={typeof config?.timeout_minutes === 'number' ? config.timeout_minutes : 60}
          onChange={(e) =>
            onChange({ ...(config ?? {}), timeout_minutes: parseInt(e.target.value) || 60 })
          }
          min={1}
          max={1440}
        />
      </div>

      {/* ── 超时动作 ── */}
      <div>
        <label className="block text-xs text-[#64748B] mb-1">超时动作</label>
        <Select
          className="w-full"
          size="small"
          value={typeof config?.timeout_action === 'string' ? config.timeout_action : 'fail'}
          onChange={(val) => onChange({ ...(config ?? {}), timeout_action: val })}
          options={TIMEOUT_ACTIONS}
        />
      </div>
    </div>
  )
}
