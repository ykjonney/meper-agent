/**
 * TaskOutputFiles — 任务产物文件列表。
 *
 * 调用 tasksApi.listOutputs 拿到 Agent 节点产出到 file_library 的文件，
 * 每项支持下载 + 弹窗预览。预览复用对话侧的富渲染能力：
 *   FilePreview（md/html/json/image/text 全类型）+ FilePreviewModal（可缩放弹窗）。
 *
 * 由父组件渲染（completed/running 均可），此处不重复判断状态。
 */
import { useState } from 'react'
import { FileText, Eye, Download, Loader2 } from 'lucide-react'
import { tasksApi, type TaskOutputFile } from '../../services/tasks-api'
import { downloadFile, getFileBlob } from '../../services/file-api'
import { detectPreviewKind } from '../FilePreview'
import { FilePreviewModal } from '../FilePreviewModal'
import { formatFileSize } from '../../lib/file-preview'

/** 文本预览大小上限 — 超过这个大小不预览（防 OOM / 渲染卡顿） */
const MAX_TEXT_BYTES = 100 * 1024

interface TaskOutputFilesProps {
  taskId: string
}

export function TaskOutputFiles({ taskId }: TaskOutputFilesProps) {
  const [files, setFiles] = useState<TaskOutputFile[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [preview, setPreview] = useState<{
    filename: string
    mime?: string
    text?: string
    imageUrl?: string
    fileId: string
  } | null>(null)
  const [previewLoading, setPreviewLoading] = useState(false)

  // 懒加载：首次渲染时拉取文件列表
  const loadFiles = async () => {
    if (files !== null) return
    try {
      const list = await tasksApi.listOutputs(taskId)
      setFiles(list)
    } catch (err) {
      console.error('[list_task_outputs]', err)
      setError('加载产物文件失败')
    } finally {
      setLoading(false)
    }
  }
  void loadFiles()

  // 点击预览：拉 blob → 按 detectPreviewKind 分流成 text/imageUrl → 开弹窗
  const handlePreview = async (file: TaskOutputFile) => {
    setPreviewLoading(true)
    try {
      const blob = await getFileBlob(file._id)
      const kind = detectPreviewKind(file.name, file.mime_type)

      if (kind === 'binary') {
        // 不可预览的二进制，直接下载
        await downloadFile(file._id, file.name)
        return
      }
      if (kind === 'text' && blob.size > MAX_TEXT_BYTES) {
        setError(`文件过大 (${Math.round(blob.size / 1024)} KB)，仅支持 ${MAX_TEXT_BYTES / 1024} KB 以内的文本预览，请下载查看`)
        return
      }
      if (kind === 'image') {
        setPreview({ filename: file.name, mime: file.mime_type, imageUrl: URL.createObjectURL(blob), fileId: file._id })
      } else {
        // md / html / json / text → 拉文本交给 FilePreview 富渲染
        setPreview({ filename: file.name, mime: file.mime_type, text: await blob.text(), fileId: file._id })
      }
    } catch (err) {
      console.error('[file_preview]', err)
      setError('预览加载失败')
    } finally {
      setPreviewLoading(false)
    }
  }

  if (loading) {
    return (
      <div className="mt-1 text-[11px] text-[#71717a] flex items-center gap-1.5">
        <Loader2 className="w-3 h-3 animate-spin" />
        加载产物文件…
      </div>
    )
  }

  if (error) {
    return <div className="mt-1 text-[11px] text-rose-400">{error}</div>
  }

  if (!files || files.length === 0) return null

  return (
    <div className="mt-2">
      <div className="text-[11px] text-[#a1a1aa] mb-1.5">产物文件 ({files.length})</div>
      <ul className="space-y-1.5">
        {files.map((f) => {
          const previewable = detectPreviewKind(f.name, f.mime_type) !== 'binary'
          return (
            <FileItem
              key={f._id}
              file={f}
              previewable={previewable}
              previewLoading={previewLoading}
              onPreview={() => handlePreview(f)}
            />
          )
        })}
      </ul>

      {/* 共享预览弹窗 */}
      <FilePreviewModal
        open={!!preview}
        filename={preview?.filename ?? ''}
        mime={preview?.mime}
        text={preview?.text}
        imageUrl={preview?.imageUrl}
        onClose={() => setPreview(null)}
        onDownload={preview ? () => downloadFile(preview.fileId, preview.filename) : undefined}
      />
    </div>
  )
}

interface FileItemProps {
  file: TaskOutputFile
  previewable: boolean
  previewLoading: boolean
  onPreview: () => void
}

function FileItem({ file, previewable, previewLoading, onPreview }: FileItemProps) {
  const fileId = file._id
  const [downloading, setDownloading] = useState(false)

  const handleDownload = async (e: React.MouseEvent) => {
    e.stopPropagation()
    if (downloading) return
    setDownloading(true)
    try {
      await downloadFile(fileId, file.name)
    } catch (err) {
      console.error('[download_file]', err)
    } finally {
      setDownloading(false)
    }
  }

  return (
    <li
      className="bg-[#121214]/60 rounded-md p-2 border border-[#27272a] hover:border-[#3f3f46] transition-colors"
      onClick={(e) => e.stopPropagation()}
    >
      <div className="flex items-center gap-2 text-xs">
        <FileText className="w-3.5 h-3.5 text-[#71717a] shrink-0" />
        <span className="flex-1 truncate text-[#d4d4d8]" title={file.name}>
          {file.name}
        </span>
        <span className="text-[#52525b] text-[10px] font-mono shrink-0">{formatFileSize(file.size)}</span>
        {previewable && (
          <button
            onClick={onPreview}
            disabled={previewLoading}
            className="inline-flex items-center gap-0.5 text-[10px] text-[#a1a1aa] hover:text-[#1E5EFF] transition-colors shrink-0 cursor-pointer disabled:opacity-50"
            title="预览"
          >
            {previewLoading ? <Loader2 className="w-3 h-3 animate-spin" /> : <Eye className="w-3 h-3" />}
          </button>
        )}
        <button
          onClick={handleDownload}
          disabled={downloading}
          className="inline-flex items-center gap-0.5 text-[10px] text-[#a1a1aa] hover:text-[#1E5EFF] transition-colors shrink-0 cursor-pointer disabled:opacity-50"
          title="下载"
        >
          {downloading ? <Loader2 className="w-3 h-3 animate-spin" /> : <Download className="w-3 h-3" />}
        </button>
      </div>
    </li>
  )
}

export default TaskOutputFiles
