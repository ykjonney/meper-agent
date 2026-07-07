/**
 * CronPresetSelector — Cron 表达式预设选择器。
 *
 * 下拉选择常用预设（每小时/每天/每周/每月），选择"自定义"时展开
 * 原始 Cron 表达式输入框。
 *
 * 作为受控组件使用，value/onChange 与 Cron 表达式字符串对接。
 */
import { useState, useEffect } from 'react'
import { Select, Input } from 'antd'

import { CRON_PRESETS } from '@/types/workflow-trigger'

const CUSTOM_VALUE = '__custom__'

interface Props {
  value?: string
  onChange?: (value: string) => void
  placeholder?: string
  disabled?: boolean
}

export default function CronPresetSelector({
  value,
  onChange,
  placeholder = '选择 Cron 预设',
  disabled = false,
}: Props) {
  // 判断当前值是否对应某个预设；否则视为自定义
  const matchedPreset = CRON_PRESETS.find((p) => p.cron === value)
  const [selectKey, setSelectKey] = useState<string>(
    matchedPreset ? matchedPreset.value : value ? CUSTOM_VALUE : '',
  )
  const [customCron, setCustomCron] = useState<string>(value ?? '')

  // 外部 value 变化时同步内部状态
  useEffect(() => {
    const matched = CRON_PRESETS.find((p) => p.cron === value)
    if (matched) {
      setSelectKey(matched.value)
    } else if (value) {
      setSelectKey(CUSTOM_VALUE)
      setCustomCron(value)
    } else {
      setSelectKey('')
      setCustomCron('')
    }
  }, [value])

  const handleSelectChange = (key: string) => {
    setSelectKey(key)
    if (key === CUSTOM_VALUE) {
      // 切换到自定义，默认不立即触发 onChange，等待用户输入
      return
    }
    const preset = CRON_PRESETS.find((p) => p.value === key)
    if (preset) {
      setCustomCron(preset.cron)
      onChange?.(preset.cron)
    }
  }

  const handleCustomChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const v = e.target.value
    setCustomCron(v)
    onChange?.(v)
  }

  const isCustom = selectKey === CUSTOM_VALUE

  return (
    <div className="flex flex-col gap-2">
      <Select
        value={selectKey || undefined}
        onChange={handleSelectChange}
        placeholder={placeholder}
        disabled={disabled}
        className="w-full"
        options={[
          ...CRON_PRESETS.map((p) => ({
            value: p.value,
            label: `${p.label}  (${p.cron})`,
          })),
          { value: CUSTOM_VALUE, label: '自定义…' },
        ]}
      />
      {isCustom && (
        <Input
          value={customCron}
          onChange={handleCustomChange}
          placeholder="例：0 9 * * 1"
          disabled={disabled}
          className="!font-mono"
        />
      )}
    </div>
  )
}
