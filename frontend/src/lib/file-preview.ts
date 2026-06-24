/**
 * 文件预览能力判断 — 决定 FilePreview 组件如何渲染。
 *
 * Story 4-15-UI：仅支持图片和文本类内嵌预览；其他类型走"请下载"提示。
 * 保持最小依赖：不做扩展名 fallback / 字节嗅探。
 */

export type PreviewKind = 'image' | 'text' | 'none'

const IMAGE_MIMES = new Set<string>([
  'image/png',
  'image/jpeg',
  'image/gif',
  'image/webp',
  'image/svg+xml',
])

const TEXT_MIMES = new Set<string>([
  'text/plain',
  'application/json',
  'text/markdown',
  'text/csv',
  'text/html',
])

/**
 * 将 mime 类型归类为预览能力。
 * @returns 'image' / 'text' / 'none'
 */
export function getPreviewKind(
  mime: string | undefined | null
): PreviewKind {
  if (!mime) return 'none'
  if (IMAGE_MIMES.has(mime)) return 'image'
  if (TEXT_MIMES.has(mime)) return 'text'
  return 'none'
}
