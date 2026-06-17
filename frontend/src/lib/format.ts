/**
 * Formatting utilities.
 */

/**
 * Parse a datetime string coming from the backend.
 *
 * The backend always stores timestamps in UTC, but when serialized via
 * Pydantic / PyMongo the timezone indicator may be stripped (resulting
 * in a "naive" ISO string like ``2024-01-15T09:30:00``).  JavaScript's
 * ``new Date(naiveIso)`` per ECMA-262 treats such strings as LOCAL
 * time, which shifts the instant by the user's UTC offset (e.g. -8h
 * for Asia/Shanghai).  This helper forces UTC interpretation when no
 * timezone indicator is present.
 */
export function parseBackendDate(iso: string): Date {
  if (!iso) return new Date(NaN)
  const hasTz = /[Zz]$|[+-]\d{2}:?\d{2}$/.test(iso)
  return new Date(hasTz ? iso : iso + 'Z')
}

export function formatDateTime(iso: string): string {
  if (!iso) return '-'
  return parseBackendDate(iso).toLocaleString('zh-CN')
}

/** Format as ``HH:mm:ss`` (24h, local time). */
export function formatTime(iso: string): string {
  if (!iso) return ''
  return parseBackendDate(iso).toLocaleTimeString('zh-CN', { hour12: false })
}

export function truncate(str: string, maxLen: number): string {
  if (str.length <= maxLen) return str
  return str.slice(0, maxLen - 1) + '…'
}
