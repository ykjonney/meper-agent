/**
 * TriggerSchedulePicker - 可视化频率选择器（生成 cron 表达式）。
 *
 * 频率预设：每小时 / 每天 / 每周 / 每月 / 自定义。
 * parseCron / buildCron 为纯函数（搬自老基线，与 UI 无关）。
 * UI 用 studio 原生 Tailwind 组件（无 antd 依赖）：频率用按钮组、时间用
 * 原生 <input type="time">、星期用按钮组、分钟/日期用 Select。
 */
import { useState, useEffect, useCallback } from 'react'
import { Input, Select } from '../ui'
import type { ScheduleFrequency } from '../../services/triggers-api'
import { WEEKDAY_LABELS } from '../../services/triggers-api'

interface Props {
  /** Cron 表达式（5 段标准 cron） */
  value: string
  onChange: (cron: string) => void
  disabled?: boolean
}

/* ─── Cron ↔ 内部状态 转换（纯函数）─── */

interface InternalState {
  frequency: ScheduleFrequency
  minute: number
  hour: number
  days: number[] // 1=周一 … 7=周日
  dayOfMonth: number // 1-28
  customCron: string
}

function parseCron(cron: string): InternalState {
  const parts = cron.trim().split(/\s+/)
  if (parts.length !== 5) {
    return { frequency: 'custom', minute: 0, hour: 0, days: [], dayOfMonth: 1, customCron: cron }
  }

  const [minStr, hourStr, domStr, , dowStr] = parts

  // 每小时: "{m} * * * *"
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
    const internalDays = days.map((d) => (d === 0 ? 7 : d))
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
      // 默认选择周一
      const days = state.days.length > 0 ? state.days : [1]
      const cronDays = days.map((d) => (d === 7 ? 0 : d)).sort().join(',')
      return `${state.minute} ${state.hour} * * ${cronDays}`
    }
    case 'monthly': {
      // 默认 1 号
      const day = state.dayOfMonth || 1
      return `${state.minute} ${state.hour} ${day} * *`
    }
    case 'custom':
      return state.customCron
  }
}

const FREQUENCIES: { value: ScheduleFrequency; label: string }[] = [
  { value: 'hourly', label: '每小时' },
  { value: 'daily', label: '每天' },
  { value: 'weekly', label: '每周' },
  { value: 'monthly', label: '每月' },
  { value: 'custom', label: '自定义' },
]

const timeStr = (hour: number, minute: number) =>
  `${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`

const timeInputCls =
  'h-8 px-2.5 rounded-md border border-[#27272a] bg-[#121214] text-[#fafafa] text-xs ' +
  'focus:outline-none focus:border-[#1E5EFF] focus:ring-1 focus:ring-[#1E5EFF]/30 [color-scheme:dark]'

export default function TriggerSchedulePicker({ value, onChange, disabled = false }: Props) {
  const [state, setState] = useState<InternalState>(() => parseCron(value))

  // 自定义模式下，外部 value 变化时同步
  useEffect(() => {
    if (state.frequency === 'custom' && value !== state.customCron) {
      setState((prev) => ({ ...prev, customCron: value }))
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value])

  const updateState = useCallback(
    (partial: Partial<InternalState>) => {
      setState((prev) => {
        const next = { ...prev, ...partial }
        onChange(buildCron(next))
        return next
      })
    },
    [onChange],
  )

  const renderTimePicker = () => (
    <div className="flex items-center gap-2 text-xs">
      <span className="text-slate-400">时间：</span>
      <input
        type="time"
        value={timeStr(state.hour, state.minute)}
        disabled={disabled}
        onChange={(e) => {
          const [h, m] = e.target.value.split(':').map(Number)
          updateState({ hour: h ?? 0, minute: m ?? 0 })
        }}
        className={timeInputCls}
      />
    </div>
  )

  return (
    <div className="space-y-3">
      {/* 频率按钮组 */}
      <div className="flex flex-wrap gap-1.5">
        {FREQUENCIES.map((f) => {
          const active = state.frequency === f.value
          return (
            <button
              key={f.value}
              type="button"
              disabled={disabled}
              onClick={() => updateState({ frequency: f.value })}
              className={`h-7 px-3 rounded-md text-xs font-medium transition-colors border cursor-pointer
                ${active
                  ? 'bg-[#1E5EFF] border-[#1E5EFF] text-white'
                  : 'bg-[#18181b] border-[#27272a] text-slate-300 hover:border-[#1E5EFF] hover:text-[#1E5EFF]'}
                ${disabled ? 'opacity-50 cursor-not-allowed' : ''}`}
            >
              {f.label}
            </button>
          )
        })}
      </div>

      {/* 频率对应配置 */}
      <div className="flex flex-wrap items-center gap-3">
        {state.frequency === 'hourly' && (
          <div className="flex items-center gap-2 text-xs">
            <span className="text-slate-400">分钟：</span>
            <Select
              value={String(state.minute)}
              onChange={(v) => updateState({ minute: Number(v) ?? 0 })}
              disabled={disabled}
              className="!w-24"
              options={Array.from({ length: 60 }, (_, i) => ({ value: String(i), label: `${i} 分` }))}
            />
          </div>
        )}

        {state.frequency === 'daily' && renderTimePicker()}

        {state.frequency === 'weekly' && (
          <>
            <div className="flex items-center gap-1.5">
              <span className="text-xs text-slate-400">星期：</span>
              {WEEKDAY_LABELS.map((label, idx) => {
                const dayNum = idx + 1
                const selected = state.days.includes(dayNum)
                return (
                  <button
                    key={dayNum}
                    type="button"
                    disabled={disabled}
                    onClick={() => {
                      const days = selected
                        ? state.days.filter((d) => d !== dayNum)
                        : [...state.days, dayNum].sort()
                      updateState({ days })
                    }}
                    className={`w-7 h-7 rounded text-xs border transition-colors cursor-pointer
                      ${selected
                        ? 'bg-[#1E5EFF] text-white border-[#1E5EFF]'
                        : 'bg-[#18181b] text-slate-300 border-[#27272a] hover:border-[#1E5EFF]'}
                      ${disabled ? 'opacity-50 cursor-not-allowed' : ''}`}
                  >
                    {label}
                  </button>
                )
              })}
            </div>
            {renderTimePicker()}
          </>
        )}

        {state.frequency === 'monthly' && (
          <>
            <div className="flex items-center gap-2 text-xs">
              <span className="text-slate-400">日期：</span>
              <Select
                value={String(state.dayOfMonth)}
                onChange={(v) => updateState({ dayOfMonth: Number(v) ?? 1 })}
                disabled={disabled}
                className="!w-24"
                options={Array.from({ length: 28 }, (_, i) => ({ value: String(i + 1), label: `${i + 1} 号` }))}
              />
            </div>
            {renderTimePicker()}
          </>
        )}

        {state.frequency === 'custom' && (
          <div className="flex items-center gap-2 text-xs w-full">
            <span className="text-slate-400">Cron 表达式：</span>
            <Input
              value={state.customCron}
              onChange={(e) => updateState({ customCron: e.target.value })}
              placeholder="* * * * *"
              className="flex-1 font-mono"
              disabled={disabled}
            />
          </div>
        )}
      </div>

      {state.frequency !== 'custom' && (
        <div className="text-[10px] text-[#94A3B8] font-mono">Cron: {buildCron(state)}</div>
      )}
    </div>
  )
}
