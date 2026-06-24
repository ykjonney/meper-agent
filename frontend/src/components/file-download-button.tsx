/**
 * FileDownloadButton — 触发文件下载到本地。
 *
 * 通过 apiClient 走标准鉴权（自动 refresh），fetch → blob → 临时 <a download>。
 *
 * Story 4-15-UI：让用户能下载 Agent 节点产出到 file_library 的文件。
 */
import { useState } from 'react'
import { Button, message } from 'antd'
import { DownloadOutlined } from '@ant-design/icons'
import { apiClient } from '../services/api-client'

interface Props {
  fileId: string
  filename: string
  /** 按钮大小，默认 small（与列表项视觉一致） */
  size?: 'small' | 'middle' | 'large'
  /** 下载成功后的回调（埋点 / 刷新列表等，可选） */
  onDownloaded?: () => void
}

export default function FileDownloadButton({
  fileId,
  filename,
  size = 'small',
  onDownloaded,
}: Props) {
  const [loading, setLoading] = useState(false)

  const handleDownload = async () => {
    setLoading(true)
    try {
      const res = await apiClient.get(
        `/api/v1/files/${encodeURIComponent(fileId)}/download`,
        { responseType: 'blob' }
      )
      const blob =
        res.data instanceof Blob ? res.data : new Blob([res.data])
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
      onDownloaded?.()
    } catch (err) {
      message.error('下载失败')
      console.error('[file_download]', err)
    } finally {
      setLoading(false)
    }
  }

  return (
    <Button
      size={size}
      type="text"
      icon={<DownloadOutlined />}
      loading={loading}
      onClick={handleDownload}
    >
      下载
    </Button>
  )
}
