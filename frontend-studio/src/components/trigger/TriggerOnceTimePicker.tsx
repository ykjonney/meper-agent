/**
 * TriggerOnceTimePicker - 一次性任务执行时间选择器。
 *
 * 原生输入框 + showPicker()：date/time 原生控件默认只有最右侧小图标能
 * 弹面板（time 甚至只给 spinner 箭头），点击输入框主体无反应——这是
 * 「难点到时间」的根因。HTML showPicker() API（Chrome/Edge 99+、
 * Safari 16.4+、Firefox 101+）可编程唤起原生面板：点击输入框任意位置
 * 即弹原生日历/时间面板，样式与系统一致。不支持的环境静默回退为
 * 原生分段编辑。保留快捷预设（1 小时后 / 明天 09:00 / 后天 09:00），
 * date 禁选过去日期。
 *
 * 与 TriggerSchedulePicker 相同的同步模式：外部 value 变化且与本地
 * 构建值不一致时重新解析（防编辑回填错位），自身操作不会误重置。
 */
import { useState, useEffect, useRef } from 'react'

interface Props {
  /** 执行时间 ISO 字符串（once 类型 execute_at） */
  value: string
  onChange: (iso: string) => void
  disabled?: boolean
}

/* ─── ISO ↔ 本地 date/time 双字段 转换（纯函数）─── */

const pad = (n: number) => String(n).padStart(2, '0')

/** ISO -> 本地时区 { date: YYYY-MM-DD, time: HH:MM }；空/非法返回空串。 */
function isoToLocalParts(iso: string): { date: string; time: string } {
  if (!iso) return { date: '', time: '' }
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return { date: '', time: '' }
  return {
    date: `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`,
    time: `${pad(d.getHours())}:${pad(d.getMinutes())}`,
  }
}

/** 本地 date/time -> ISO 字符串；任一为空返回 ''。 */
function localPartsToIso(date: string, time: string): string {
  if (!date || !time) return ''
  const d = new Date(`${date}T${time}`)
  if (Number.isNaN(d.getTime())) return ''
  return d.toISOString()
}

/** 生成预设目标时间：offsetDays 天后的 hour:minute（当天传 0），秒/毫秒归零。 */
function presetTarget(offsetDays: number, hour: number, minute: number): Date {
  const d = new Date()
  d.setDate(d.getDate() + offsetDays)
  d.setHours(hour, minute, 0, 0)
  return d
}

const PRESETS: { label: string; build: () => Date }[] = [
  { label: '1 小时后', build: () => new Date(Math.floor(Date.now() / 60000) * 60000 + 3600_000) },
  { label: '明天 09:00', build: () => presetTarget(1, 9, 0) },
  { label: '后天 09:00', build: () => presetTarget(2, 9, 0) },
]

const WEEKDAY_LABELS = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']

const inputCls =
  'h-8 flex-1 min-w-0 px-2.5 rounded-md border border-[#27272a] bg-[#121214] text-[#fafafa] text-xs ' +
  'focus:outline-none focus:border-[#1E5EFF] focus:ring-1 focus:ring-[#1E5EFF]/30 [color-scheme:dark]'

/** 点击输入框任意位置即唤起原生面板（showPicker 不支持时静默回退）。 */
function useNativePicker() {
  const ref = useRef<HTMLInputElement>(null)
  const open = () => {
    try {
      ref.current?.showPicker()
    } catch {
      // 浏览器不支持（如无安全激活）——回退为原生分段编辑
    }
  }
  return { ref, open }
}

export default function TriggerOnceTimePicker({ value, onChange, disabled = false }: Props) {
  const [parts, setParts] = useState<{ date: string; time: string }>(() => isoToLocalParts(value))
  const datePicker = useNativePicker()
  const timePicker = useNativePicker()

  // 外部 value 变化时重新解析同步（编辑回填等场景）
  useEffect(() => {
    if (value !== localPartsToIso(parts.date, parts.time)) {
      setParts(isoToLocalParts(value))
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value])

  const updateParts = (partial: Partial<{ date: string; time: string }>) => {
    setParts((prev) => {
      const next = { ...prev, ...partial }
      onChange(localPartsToIso(next.date, next.time))
      return next
    })
  }

  const applyPreset = (build: () => Date) => {
    const target = build()
    const next = isoToLocalParts(target.toISOString())
    setParts(next)
    onChange(target.toISOString())
  }

  // date 禁选过去日期（今天起）；预览含星期便于确认
  const todayStr = isoToLocalParts(new Date().toISOString()).date
  const previewDate = new Date(parts.date ? `${parts.date}T00:00:00` : '')
  const weekday = Number.isNaN(previewDate.getTime())
    ? ''
    : `（${WEEKDAY_LABELS[previewDate.getDay()]}）`

  return (
    <div className="space-y-3">
      {/* 快捷预设按钮组 */}
      <div className="flex flex-wrap gap-1.5">
        {PRESETS.map((p) => (
          <button
            key={p.label}
            type="button"
            disabled={disabled}
            onClick={() => applyPreset(p.build)}
            className={`h-7 px-3 rounded-md text-xs font-medium transition-colors border cursor-pointer
              bg-[#18181b] border-[#27272a] text-slate-300 hover:border-[#1E5EFF] hover:text-[#1E5EFF]
              ${disabled ? 'opacity-50 cursor-not-allowed' : ''}`}
          >
            {p.label}
          </button>
        ))}
      </div>

      {/* 自定义日期 + 时间：原生控件 + showPicker，点框任意处弹原生面板 */}
      <div className="flex items-center gap-2">
        <input
          ref={datePicker.ref}
          type="date"
          value={parts.date}
          min={todayStr}
          disabled={disabled}
          onClick={datePicker.open}
          onChange={(e) => updateParts({ date: e.target.value })}
          className={`${inputCls} cursor-pointer`}
        />
        <input
          ref={timePicker.ref}
          type="time"
          value={parts.time}
          disabled={disabled}
          onClick={timePicker.open}
          onChange={(e) => updateParts({ time: e.target.value })}
          className={`${inputCls} cursor-pointer`}
        />
      </div>

      {/* 选中时间预览（对齐 Cron 展示行） */}
      {value && parts.date && parts.time && (
        <div className="text-[10px] text-[#94A3B8] font-mono">
          {parts.date} {parts.time} {weekday}
        </div>
      )}
    </div>
  )
}
