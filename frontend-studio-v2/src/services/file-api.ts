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
 * FileRef 响应 — 对齐后端 FileRefResponse（app/api/v1/files.py）。
 */
export interface FileRefResponse {
  id: string
  owner_user_id: string
  storage_key: string
  name: string
  size: number
  mime_type: string
  sha256: string
  origin_kind: string
  origin_id: string | null
  status: string
  created_at: string
  updated_at: string
}

/**
 * 上传文件到用户文件库，返回 FileRef。
 * 走 POST /api/v1/files（multipart/form-data），origin_kind=workflow_run，
 * 供工作流执行时把返回的 file.id 作为 Start 节点 file 变量值传入。
 */
export async function uploadFile(file: File): Promise<FileRefResponse> {
  const form = new FormData()
  form.append('file', file)
  const res = await apiClient.post<FileRefResponse>('/api/v1/files', form, {
    params: { origin_kind: 'workflow_run' },
  })
  return res.data
}

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
