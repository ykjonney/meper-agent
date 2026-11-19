import {
  DownloadOutlined,
  EyeOutlined,
  FileDoneOutlined,
  FileImageOutlined,
  FileOutlined,
  FilePdfOutlined,
  FileTextOutlined,
  FileZipOutlined,
  ReloadOutlined,
} from '@ant-design/icons'
import {
  App,
  Button,
  Drawer,
  Empty,
  List,
  Modal,
  Skeleton,
  Space,
  Typography,
} from 'antd'
import { useCallback, useEffect, useState, type ReactNode } from 'react'

import {
  downloadSessionFile,
  downloadSessionZip,
  getSessionFile,
  listSessionFiles,
} from '../api/chat'
import type { SessionFile } from '../types'

interface GeneratedFilesProps {
  sessionId: string | null
  open: boolean
  onClose: () => void
  refreshKey: number
}

function fileName(file: SessionFile): string {
  return file.name || file.path
}

function humanSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

/** 文件类型 → 图标 / 色彩 / 中文标签（产物列表的类型标识）。 */
function fileKindMeta(name: string): { icon: ReactNode; color: string; label: string } {
  if (/\.(png|jpe?g|gif|webp|svg)$/i.test(name))
    return { icon: <FileImageOutlined />, color: '#1f9d55', label: '图片' }
  if (/\.(zip|tar|gz|tgz|7z|rar)$/i.test(name))
    return { icon: <FileZipOutlined />, color: '#b45309', label: '压缩包' }
  if (/\.pdf$/i.test(name)) return { icon: <FilePdfOutlined />, color: '#d93a3f', label: 'PDF' }
  if (/\.(md|txt|docx?|rtf)$/i.test(name))
    return { icon: <FileTextOutlined />, color: '#2b4a9e', label: '文档' }
  if (/\.(json|csv|ya?ml|xml|html?)$/i.test(name))
    return { icon: <FileOutlined />, color: '#8a6dcd', label: '数据' }
  return { icon: <FileOutlined />, color: '#8a94a0', label: '文件' }
}

export function GeneratedFiles({
  sessionId,
  open,
  onClose,
  refreshKey,
}: GeneratedFilesProps) {
  const { message } = App.useApp()
  const [files, setFiles] = useState<SessionFile[]>([])
  const [loading, setLoading] = useState(false)
  const [preview, setPreview] = useState<{
    name: string
    kind: 'image' | 'pdf' | 'text' | 'unsupported'
    url?: string
    text?: string
  } | null>(null)

  const load = useCallback(async () => {
    if (!sessionId) {
      setFiles([])
      return
    }
    setLoading(true)
    try {
      setFiles(await listSessionFiles(sessionId))
    } catch (error: unknown) {
      void message.error(error instanceof Error ? error.message : '文件列表加载失败')
    } finally {
      setLoading(false)
    }
  }, [sessionId])

  useEffect(() => {
    void load()
  }, [load, refreshKey])

  useEffect(
    () => () => {
      if (preview?.url) URL.revokeObjectURL(preview.url)
    },
    [preview],
  )

  const openPreview = async (file: SessionFile) => {
    if (!sessionId) return
    const name = fileName(file)
    try {
      const blob = await getSessionFile(sessionId, name)
      const mime = blob.type || file.mime || ''
      if (mime.startsWith('image/') || /\.(png|jpe?g|gif|webp|svg)$/i.test(name)) {
        setPreview({ name, kind: 'image', url: URL.createObjectURL(blob) })
      } else if (mime === 'application/pdf' || name.toLowerCase().endsWith('.pdf')) {
        setPreview({ name, kind: 'pdf', url: URL.createObjectURL(blob) })
      } else if (
        mime.startsWith('text/') ||
        /\.(md|txt|json|csv|html|xml|ya?ml)$/i.test(name)
      ) {
        setPreview({ name, kind: 'text', text: await blob.text() })
      } else {
        setPreview({ name, kind: 'unsupported' })
      }
    } catch {
      void message.error('文件预览失败')
    }
  }

  return (
    <>
      <Drawer
        title="产物"
        width={380}
        open={open}
        onClose={onClose}
        className="files-drawer"
        extra={
          <Space>
            <Button icon={<ReloadOutlined />} onClick={() => void load()} />
            <Button
              icon={<FileZipOutlined />}
              disabled={!sessionId || files.length === 0}
              onClick={() => {
                if (sessionId) void downloadSessionZip(sessionId)
              }}
            >
              打包下载
            </Button>
          </Space>
        }
      >
        {loading ? (
          <Skeleton active paragraph={{ rows: 5 }} />
        ) : files.length === 0 ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                <FileDoneOutlined style={{ color: '#1f9d55' }} />
                还没有产物——让 Agent 生成图表或写文件吧
              </span>
            }
          />
        ) : (
          <List
            dataSource={files}
            renderItem={(file) => {
              const name = fileName(file)
              const kind = fileKindMeta(name)
              return (
                <List.Item
                  className="generated-file-item"
                  actions={[
                    <Button
                      key="preview"
                      type="text"
                      size="small"
                      icon={<EyeOutlined />}
                      onClick={() => void openPreview(file)}
                      aria-label={`预览 ${name}`}
                    >
                      预览
                    </Button>,
                    <Button
                      key="download"
                      type="text"
                      size="small"
                      icon={<DownloadOutlined />}
                      onClick={() => {
                        if (sessionId) void downloadSessionFile(sessionId, name)
                      }}
                      aria-label={`下载 ${name}`}
                    >
                      下载
                    </Button>,
                  ]}
                >
                  <List.Item.Meta
                    avatar={
                      <span className="generated-file-icon" style={{ color: kind.color }}>
                        {kind.icon}
                      </span>
                    }
                    title={<span className="generated-file-name">{name}</span>}
                    description={
                      <span className="generated-file-desc">
                        {kind.label} · {humanSize(file.size)}
                      </span>
                    }
                  />
                </List.Item>
              )
            }}
          />
        )}
      </Drawer>
      <Modal
        width="min(920px, calc(100vw - 32px))"
        title={preview?.name}
        open={Boolean(preview)}
        footer={
          preview && sessionId ? (
            <Button
              type="primary"
              icon={<DownloadOutlined />}
              onClick={() => void downloadSessionFile(sessionId, preview.name)}
            >
              下载
            </Button>
          ) : null
        }
        onCancel={() => setPreview(null)}
        destroyOnHidden
      >
        {preview?.kind === 'image' ? (
          <img className="file-preview-image" src={preview.url} alt={preview.name} />
        ) : null}
        {preview?.kind === 'pdf' ? (
          <iframe className="file-preview-pdf" src={preview.url} title={preview.name} />
        ) : null}
        {preview?.kind === 'text' ? (
          <pre className="file-preview-text">{preview.text}</pre>
        ) : null}
        {preview?.kind === 'unsupported' ? (
          <Typography.Text type="secondary">
            当前浏览器不支持预览此格式，请下载后查看。
          </Typography.Text>
        ) : null}
      </Modal>
    </>
  )
}

