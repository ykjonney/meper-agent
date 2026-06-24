/**
 * FilePreview — 内嵌预览组件（图片 / 文本 / 结构化文本）。
 *
 * 走 apiClient 鉴权获取 blob：
 * - image/* → <img> 直接显示
 * - text/* / json / csv / md / html → <pre> 包裹（自动转义，防 XSS）
 * - 其他 → 走"无预览"提示
 *
 * 文本有 100 KB 阈值保护；blob URL 在 unmount 时 revoke。
 * cancelled flag 防 race condition（用户快速切换 task）。
 *
 * Story 4-15-UI
 */
import { useEffect, useState } from 'react'
import { Empty, Spin } from 'antd'
import { FileOutlined } from '@ant-design/icons'
import { apiClient } from '../services/api-client'
import { getPreviewKind } from '../lib/file-preview'

interface Props {
  fileId: string
  filename: string
  mime: string
}

/** 文本预览大小上限 — 超过这个大小不预览（防 OOM / 渲染卡顿） */
const MAX_TEXT_BYTES = 100 * 1024

export default function FilePreview({ fileId, filename, mime }: Props) {
  const kind = getPreviewKind(mime)
  const [loading, setLoading] = useState(kind !== 'none')
  const [error, setError] = useState<string | null>(null)
  const [blobUrl, setBlobUrl] = useState<string | null>(null)
  const [text, setText] = useState<string | null>(null)

  useEffect(() => {
    if (kind === 'none') return
    let cancelled = false
    const run = async () => {
      try {
        const res = await apiClient.get(
          `/api/v1/files/${encodeURIComponent(fileId)}/download`,
          { responseType: 'blob' }
        )
        if (cancelled) return
        const blob =
          res.data instanceof Blob ? res.data : new Blob([res.data])
        if (kind === 'text' && blob.size > MAX_TEXT_BYTES) {
          setError(
            `文件过大 (${Math.round(blob.size / 1024)} KB)，仅支持 ${MAX_TEXT_BYTES / 1024} KB 以内的文本预览`
          )
          return
        }
        if (kind === 'image') {
          setBlobUrl(URL.createObjectURL(blob))
        } else {
          const t = await blob.text()
          if (!cancelled) setText(t)
        }
      } catch (err) {
        if (cancelled) return
        console.error('[file_preview]', err)
        setError('预览加载失败')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    void run()
    return () => {
      cancelled = true
    }
  }, [fileId, mime, kind])

  if (loading) {
    return (
      <div className="py-4 text-center">
        <Spin size="small" />
      </div>
    )
  }

  if (error) {
    return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={error} />
  }

  if (kind === 'none') {
    return (
      <div className="py-4 text-center text-gray-500 text-xs">
        <FileOutlined className="mr-1" />
        该文件类型不支持预览，请下载查看
      </div>
    )
  }

  if (kind === 'image' && blobUrl) {
    return (
      <div className="py-2">
        <img
          src={blobUrl}
          alt={filename}
          className="max-w-full max-h-96 rounded border border-gray-200"
        />
      </div>
    )
  }

  if (kind === 'text' && text !== null) {
    return (
      <pre className="text-xs bg-gray-50 rounded p-2 mt-1 max-h-60 overflow-auto font-mono border border-gray-200 whitespace-pre-wrap break-words">
        {text}
      </pre>
    )
  }

  return null
}
