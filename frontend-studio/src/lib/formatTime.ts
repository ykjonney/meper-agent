/**
 * 日期/时间格式化统一入口（收敛全站本地副本）。
 *
 * 空值 / 无效日期统一兜底 '-'。
 */

type Input = string | number | Date | null | undefined

function toDate(v: Input): Date | null {
  if (v == null || v === '') return null
  const d = new Date(v)
  return Number.isNaN(d.getTime()) ? null : d
}

const pad = (n: number) => String(n).padStart(2, '0')

/** 完整日期时间：YYYY-MM-DD HH:mm:ss */
export function formatTimeFull(v: Input): string {
  const d = toDate(v)
  if (!d) return '-'
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

/** 紧凑日期时间：MM-DD HH:mm:ss */
export function formatTimeShort(v: Input): string {
  const d = toDate(v)
  if (!d) return '-'
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

/** 相对时间：刚刚 / x 分钟前 / x 小时前 / x 天前 */
export function formatTimeRelative(v: Input): string {
  const d = toDate(v)
  if (!d) return '-'
  const diff = Date.now() - d.getTime()
  if (diff < 0) return '刚刚'
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return '刚刚'
  if (mins < 60) return `${mins} 分钟前`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours} 小时前`
  return `${Math.floor(hours / 24)} 天前`
}
