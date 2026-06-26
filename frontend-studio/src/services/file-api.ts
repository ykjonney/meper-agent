/**
 * File API — 通用文件下载 / 预览 blob。
 *
 * 走统一端点 GET /api/v1/files/{id}/download（apiClient 自动注入 Bearer token），
 * 与 backend 的 file_library 对齐。任务输出文件、会话文件等共享这套能力。
 *
 * 对齐旧版 frontend/src/components/file-download-button.tsx +
 * file-preview.tsx 的 blob 处理逻辑，适配 studio 的鉴权拦截器。
 */
import { apiClient } from '../lib/api-client'

/**
 * 下载文件到本地：fetch blob → 临时 <a download>。
 * @param fileId  file_library 文档 id
 * @param filename 下载保存的文件名
 */
export async function downloadFile(fileId: string, filename: string): Promise<void> {
  const res = await apiClient.get(`/api/v1/files/${encodeURIComponent(fileId)}/download`, {
    responseType: 'blob',
  })
  const blob = res.data instanceof Blob ? res.data : new Blob([res.data])
  const url = URL.createObjectURL(blob)
  try {
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
  } finally {
    URL.revokeObjectURL(url)
  }
}

/**
 * 获取文件 blob（供内嵌预览使用：图片 / 文本）。
 * @param fileId file_library 文档 id
 */
export async function getFileBlob(fileId: string): Promise<Blob> {
  const res = await apiClient.get(`/api/v1/files/${encodeURIComponent(fileId)}/download`, {
    responseType: 'blob',
  })
  return res.data instanceof Blob ? res.data : new Blob([res.data])
}
