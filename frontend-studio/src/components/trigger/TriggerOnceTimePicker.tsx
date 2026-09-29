/**
 * TriggerOnceTimePicker - 一次性任务执行时间选择器。
 *
 * 演进史：原生 datetime-local → date/time 双原生输入框（日历可点任意
 * 位置弹出）→ 本版：原生 <input type="time"> 的 spinner 箭头极小、时/分
 * 段落要先点选再调，实测仍难命中——时间改为**自绘滚轮下拉**（小时/分钟
 * 双列整行大点击区，打开自动滚到当前值），面板底部保留精确键盘输入
 * （HH:MM，支持 9:5 这类松散写法）。日期维持原生 date（点任意位置即弹
 * 日历，体验可接受），date 禁选过去日期。
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

/** 解析松散时间输入为 HH:MM：支持 "9"、"9:5"、"09:30"、"930"（3-4 位数字）。 */
function parseLooseTime(raw: string): string | null {
  const s = raw.trim().replace('：', ':')
  const m1 = s.match(/^(\d{1,2})[:.](\d{1,2})$/)
  if (m1) {
    const h = Number(m1[1]); const mi = Number(m1[2])
    if (h <= 23 && mi <= 59) return `${pad(h)}:${pad(mi)}`
    return null
  }
  const m2 = s.match(/^(\d{3,4})$/)
  if (m2) {
    const h = Number(s.slice(0, s.length - 2))
    const mi = Number(s.slice(-2))
    if (h <= 23 && mi <= 59) return `${pad(h)}:${pad(mi)}`
  }
  return null
}

const HOURS = Array.from({ length: 24 }, (_, h) => pad(h))
const MINUTES = Array.from({ length: 12 }, (_, i) => pad(i * 5))

/**
 * 时间滚轮下拉：触发按钮 + 内联展开的双列（小时 00-23 / 分钟每 5 分）。
 * 整行 h-8 大点击区；点选即时生效（另一侧缺省时补 当前小时/00），
 * 面板保持展开便于连续微调；底部输入框支持精确到任意分钟。
 */
function TimeWheel({
  time, onPick, disabled,
}: { time: string; onPick: (hhmm: string) => void; disabled?: boolean }) {
  const [open, setOpen] = useState(false)
  const [loose, setLoose] = useState('')
  const [hour, minute] = time ? time.split(':') : ['', '']
  const hourColRef = useRef<HTMLDivElement>(null)
  const minuteColRef = useRef<HTMLDivElement>(null)

  // 打开时滚到当前选中项（无选中滚到当前时刻附近）
  useEffect(() => {
    if (!open) return
    const now = new Date()
    const selHour = hour || pad(now.getHours())
    const selMinute = minute || pad(Math.floor(now.getMinutes() / 5) * 5)
    for (const [ref, sel] of [[hourColRef, selHour], [minuteColRef, selMinute]] as const) {
      const el = ref.current?.querySelector(`[data-v="${sel}"]`)
      el?.scrollIntoView({ block: 'center' })
    }
  }, [open, hour, minute])

  const pick = (h: string, m: string) => onPick(`${h}:${m}`)
  const pickHour = (h: string) => pick(h, minute || '00')
  const pickMinute = (m: string) => pick(hour || pad(new Date().getHours()), m)

  const applyLoose = () => {
    const parsed = parseLooseTime(loose)
    if (parsed) {
      onPick(parsed)
      setLoose('')
    }
  }

  const rowCls = (active: boolean) =>
    `h-8 flex items-center justify-center rounded-md text-xs cursor-pointer transition-colors select-none ` +
    (active
      ? 'bg-[#1E5EFF] text-white font-semibold'
      : 'text-slate-300 hover:bg-[#27272a] hover:text-[#fafafa]')

  return (
    <div className="relative flex-1 min-w-0">
      <button
        type="button"
        disabled={disabled}
        onClick={() => setOpen((v) => !v)}
        className={`${inputCls} flex items-center justify-between cursor-pointer text-left ${
          disabled ? 'opacity-50 cursor-not-allowed' : ''
        }`}
      >
        <span className={time ? '' : 'text-[#71717a]'}>{time || '选择时间'}</span>
        <span className="text-[#71717a] text-[10px]">▾</span>
      </button>

      {open && (
        <div className="absolute z-20 mt-1.5 left-0 right-0 rounded-lg border border-[#27272a] bg-[#18181b] shadow-xl p-2 space-y-2">
          <div className="flex gap-1.5">
            <div className="flex-1 min-w-0">
              <div className="text-[10px] text-[#71717a] text-center mb-1">小时</div>
              <div ref={hourColRef} className="max-h-44 overflow-y-auto space-y-0.5 pr-0.5">
                {HOURS.map((h) => (
                  <div
                    key={h}
                    data-v={h}
                    onClick={() => pickHour(h)}
                    className={rowCls(h === hour)}
                  >
                    {h}
                  </div>
                ))}
              </div>
            </div>
            <div className="flex-1 min-w-0">
              <div className="text-[10px] text-[#71717a] text-center mb-1">分钟</div>
              <div ref={minuteColRef} className="max-h-44 overflow-y-auto space-y-0.5 pr-0.5">
                {MINUTES.map((m) => (
                  <div
                    key={m}
                    data-v={m}
                    onClick={() => pickMinute(m)}
                    className={rowCls(m === minute)}
                  >
                    {m}
                  </div>
                ))}
              </div>
            </div>
          </div>
          {/* 精确输入：滚轮为 5 分钟粒度，任意分钟键盘直达 */}
          <div className="flex items-center gap-1.5 pt-1.5 border-t border-[#27272a]">
            <input
              value={loose}
              onChange={(e) => setLoose(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && applyLoose()}
              onBlur={applyLoose}
              disabled={disabled}
              placeholder="精确输入，如 9:07"
              className="h-7 flex-1 min-w-0 px-2 rounded-md border border-[#27272a] bg-[#121214] text-[#fafafa] text-xs focus:outline-none focus:border-[#1E5EFF]"
            />
            <button
              type="button"
              onClick={() => setOpen(false)}
              className="h-7 px-2.5 rounded-md text-xs bg-[#27272a] text-slate-300 hover:text-[#fafafa] cursor-pointer"
            >
              收起
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

export default function TriggerOnceTimePicker({ value, onChange, disabled = false }: Props) {
  const [parts, setParts] = useState<{ date: string; time: string }>(() => isoToLocalParts(value))

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

      {/* 自定义日期 + 时间（时间为自绘滚轮下拉，日期原生日历） */}
      <div className="flex items-center gap-2">
        <input
          type="date"
          value={parts.date}
          min={todayStr}
          disabled={disabled}
          onChange={(e) => updateParts({ date: e.target.value })}
          className={inputCls}
        />
        <TimeWheel
          time={parts.time}
          disabled={disabled}
          onPick={(hhmm) => updateParts({ time: hhmm })}
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
