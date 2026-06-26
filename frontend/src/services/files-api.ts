/**
 * File API service — wraps backend /files endpoints.
 *
 * Provides generic file upload functionality for workflow inputs,
 * task attachments, etc.
 */
import { apiClient } from './api-client'

/* ─── Types ─── */

export interface FileRefResponse {
  id: string
  _id?: string  // Backend returns _id due to MongoDB field alias
  name: string
  size: number
  mime_type: string
  storage_key: string
  status: string
  created_at: string
}

/** Get file ID, handling both `id` and `_id` (MongoDB alias) */
export function getFileId(file: FileRefResponse): string {
  return file.id || file._id || ''
}

/* ─── API ─── */

export const filesApi = {
  /**
   * Upload a file to the file library.
   * POST /api/v1/files
   *
   * @param file - The file to upload
   * @param originKind - Origin kind (default: 'user_library')
   * @param originId - Origin ID (optional)
   * @param onProgress - Upload progress callback (0-100)
   * @returns FileRefResponse with the uploaded file metadata
   */
  async upload(
    file: File,
    originKind: string = 'user_library',
    originId?: string,
    onProgress?: (percent: number) => void,
  ): Promise<FileRefResponse> {
    const formData = new FormData()
    formData.append('file', file)

    const params = new URLSearchParams()
    params.append('origin_kind', originKind)
    if (originId) {
      params.append('origin_id', originId)
    }

    const res = await apiClient.post<FileRefResponse>(
      `/api/v1/files?${params.toString()}`,
      formData,
      {
        headers: { 'Content-Type': 'multipart/form-data' },
        onUploadProgress: (progressEvent) => {
          if (onProgress && progressEvent.total) {
            const percent = Math.round((progressEvent.loaded * 100) / progressEvent.total)
            onProgress(percent)
          }
        },
      },
    )
    return res.data
  },

  /**
   * Get file metadata by ID.
   * GET /api/v1/files/{fileId}
   */
  async get(fileId: string): Promise<FileRefResponse> {
    const res = await apiClient.get<FileRefResponse>(`/api/v1/files/${encodeURIComponent(fileId)}`)
    return res.data
  },

  /**
   * Delete a file by ID.
   * DELETE /api/v1/files/{fileId}
   */
  async delete(fileId: string): Promise<void> {
    await apiClient.delete(`/api/v1/files/${encodeURIComponent(fileId)}`)
  },
}
