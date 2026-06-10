/**
 * Formatting utilities.
 */
export function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString('zh-CN')
}

export function truncate(str: string, maxLen: number): string {
  if (str.length <= maxLen) return str
  return str.slice(0, maxLen - 1) + '…'
}
