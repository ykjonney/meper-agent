/**
 * TriggerSchedulePicker — 可视化频率选择器。
 *
 * 用户通过 Radio 选择频率（每小时/每天/每周/每月/自定义），
 * 组件内部维护状态并生成对应的 cron 表达式。
 */
import { useState, useEffect, useCallback } from 'react'
import { Radio, TimePicker, Input, Select } from 'antd'
import type { RadioChangeEvent } from 'antd'
import type { ScheduleFrequency } from '@/types/workflow-trigger'
import { WEEKDAY_LABELS } from '@/types/workflow-trigger'

interface Props {
  value: string           // Cron 表达式
  onChange: (cron: string) => void
  disabled?: boolean
}

/* ─── Cron ↔ 内部状态 转换 ─── */

interface InternalState {
  frequency: ScheduleFrequency
  minute: number
  hour: number
  days: number[]         // 1=周一 … 7=周日
  dayOfMonth: number     // 1-28
  customCron: string
}

function parseCron(cron: string): InternalState {
  const parts = cron.trim().split(/\s+/)
  if (parts.length !== 5) {
    return { frequency: 'custom', minute: 0, hour: 0, days: [], dayOfMonth: 1, customCron: cron }
  }

  const [minStr, hourStr, domStr, , dowStr] = parts

  // 每小时: "0 * * * *"  or "{m} * * * *"
  if (domStr === '*' && dowStr === '*' && hourStr === '*') {
    return { frequency: 'hourly', minute: parseInt(minStr) || 0, hour: 0, days: [], dayOfMonth: 1, customCron: '' }
  }

  // 每天: "{m} {h} * * *"
  if (domStr === '*' && dowStr === '*') {
    return { frequency: 'daily', minute: parseInt(minStr) || 0, hour: parseInt(hourStr) || 0, days: [], dayOfMonth: 1, customCron: '' }
  }

  // 每月: "{m} {h} {d} * *"
  if (domStr !== '*' && dowStr === '*') {
    return { frequency: 'monthly', minute: parseInt(minStr) || 0, hour: parseInt(hourStr) || 0, days: [], dayOfMonth: parseInt(domStr) || 1, customCron: '' }
  }

  // 每周: "{m} {h} * * {d1,d2,...}"
  if (domStr === '*' && dowStr !== '*') {
    const days = dowStr.split(',').map(Number).filter((n) => n >= 0 && n <= 6)
    // 转换 cron 星期 (0=Sun) 到内部 (1=Mon…7=Sun)
    const internalDays = days.map((d) => d === 0 ? 7 : d)
    return { frequency: 'weekly', minute: parseInt(minStr) || 0, hour: parseInt(hourStr) || 0, days: internalDays, dayOfMonth: 1, customCron: '' }
  }

  return { frequency: 'custom', minute: 0, hour: 0, days: [], dayOfMonth: 1, customCron: cron }
}

function buildCron(state: InternalState): string {
  switch (state.frequency) {
    case 'hourly':
      return `${state.minute} * * * *`
    case 'daily':
      return `${state.minute} ${state.hour} * * *`
    case 'weekly': {
      if (state.days.length === 0) return `${state.minute} ${state.hour} * * *`
      // 转换内部星期 (1=Mon…7=Sun) 到 cron (0=Sun)
      const cronDays = state.days.map((d) => d === 7 ? 0 : d).sort().join(',')
      return `${state.minute} ${state.hour} * * ${cronDays}`
    }
    case 'monthly':
      return `${state.minute} ${state.hour} ${state.dayOfMonth} * *`
    case 'custom':
      return state.customCron
  }
}

/* ─── 组件 ─── */

export default function TriggerSchedulePicker({ value, onChange, disabled = false }: Props) {
  const [state, setState] = useState<InternalState>(() => parseCron(value))

  // 外部 value 变化时同步（仅在自定义模式下，用户输入直接更新）
  useEffect(() => {
    if (state.frequency === 'custom' && value !== state.customCron) {
      setState((prev) => ({ ...prev, customCron: value }))
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value])

  const updateState = useCallback((partial: Partial<InternalState>) => {
    setState((prev) => {
      const next = { ...prev, ...partial }
      onChange(buildCron(next))
      return next
    })
  }, [onChange])

  const handleFrequencyChange = (e: RadioChangeEvent) => {
    const freq = e.target.value as ScheduleFrequency
    updateState({ frequency: freq })
  }

  const dayjs = (() => {
    // 动态导入 dayjs 的 TimePicker 需要
    try {
      return require('dayjs')
    } catch {
      return null
    }
  })()

  const renderTimePicker = () => {
    if (!dayjs) {
      // Fallback: 手动输入
      return (
        <div className="flex items-center gap-2 text-xs">
          <span>时间:</span>
          <Input
            type="time"
            value={`${String(state.hour).padStart(2, '0')}:${String(state.minute).padStart(2, '0')}`}
            onChange={(e) => {
              const [h, m] = e.target.value.split(':').map(Number)
              updateState({ hour: h ?? 0, minute: m ?? 0 })
            }}
            className="!w-auto !text-xs"
            disabled={disabled}
          />
        </div>
      )
    }

    return (
      <div className="flex items-center gap-2 text-xs">
        <span>时间:</span>
        <TimePicker
          value={dayjs().hour(state.hour).minute(state.minute)}
          onChange={(_, dateStr) => {
            if (typeof dateStr === 'string') {
              const [h, m] = dateStr.split(':').map(Number)
              updateState({ hour: h ?? 0, minute: m ?? 0 })
            }
          }}
          format="HH:mm"
          disabled={disabled}
          size="small"
        />
      </div>
    )
  }

  const renderMinutePicker = () => (
    <div className="flex items-center gap-2 text-xs">
      <span>分钟:</span>
      <Select
        value={state.minute}
        onChange={(v) => updateState({ minute: v })}
        disabled={disabled}
        size="small"
        className="!w-20"
        options={Array.from({ length: 60 }, (_, i) => ({ label: `${i}分`, value: i }))}
      />
    </div>
  )

  const renderDaySelector = () => (
    <div className="flex items-center gap-1.5">
      <span className="text-xs">选择星期:</span>
      {WEEKDAY_LABELS.map((label, idx) => {
        const dayNum = idx + 1 // 1=Mon … 7=Sun
        const selected = state.days.includes(dayNum)
        return (
          <button
            key={dayNum}
            type="button"
            onClick={() => {
              const days = selected
                ? state.days.filter((d) => d !== dayNum)
                : [...state.days, dayNum].sort()
              updateState({ days })
            }}
            disabled={disabled}
            className={`w-7 h-7 rounded text-xs border cursor-pointer transition-colors ${
              selected
                ? 'bg-blue-500 text-white border-blue-500'
                : 'bg-white text-gray-600 border-gray-200 hover:border-blue-300'
            } ${disabled ? 'opacity-50 cursor-not-allowed' : ''}`}
          >
            {label}
          </button>
        )
      })}
    </div>
  )

  const renderDayOfMonth = () => (
    <div className="flex items-center gap-2 text-xs">
      <span>日期:</span>
      <Select
        value={state.dayOfMonth}
        onChange={(v) => updateState({ dayOfMonth: v })}
        disabled={disabled}
        size="small"
        className="!w-20"
        options={Array.from({ length: 28 }, (_, i) => ({ label: `${i + 1}号`, value: i + 1 }))}
      />
    </div>
  )

  return (
    <div className="space-y-3">
      <Radio.Group
        value={state.frequency}
        onChange={handleFrequencyChange}
        disabled={disabled}
        optionType="button"
        buttonStyle="solid"
      >
        <Radio.Button value="hourly">每小时</Radio.Button>
        <Radio.Button value="daily">每天</Radio.Button>
        <Radio.Button value="weekly">每周</Radio.Button>
        <Radio.Button value="monthly">每月</Radio.Button>
        <Radio.Button value="custom">自定义</Radio.Button>
      </Radio.Group>

      <div className="flex flex-wrap items-center gap-3">
        {state.frequency === 'hourly' && renderMinutePicker()}
        {state.frequency === 'daily' && renderTimePicker()}
        {state.frequency === 'weekly' && (
          <>
            {renderDaySelector()}
            {renderTimePicker()}
          </>
        )}
        {state.frequency === 'monthly' && (
          <>
            {renderDayOfMonth()}
            {renderTimePicker()}
          </>
        )}
        {state.frequency === 'custom' && (
          <div className="flex items-center gap-2 text-xs w-full">
            <span>Cron 表达式:</span>
            <Input
              value={state.customCron}
              onChange={(e) => updateState({ customCron: e.target.value })}
              placeholder="* * * * *"
              className="!flex-1 !text-xs font-mono"
              disabled={disabled}
            />
          </div>
        )}
      </div>

      {state.frequency !== 'custom' && (
        <div className="text-[10px] text-[#94A3B8] font-mono">
          Cron: {buildCron(state)}
        </div>
      )}
    </div>
  )
}
