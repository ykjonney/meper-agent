/** 字节数转人类可读字符串（B/KB/MB/GB，<10 保留一位小数）。 */
export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  const units = ['KB', 'MB', 'GB']
  const i = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)) - 1, units.length - 1)
  const val = bytes / Math.pow(1024, i + 1)
  return `${val < 10 ? val.toFixed(1) : Math.round(val)} ${units[i]}`
}
