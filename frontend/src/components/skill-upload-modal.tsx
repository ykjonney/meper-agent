/**
 * Skill upload modal — supports file and directory upload.
 */
import { useRef, useState } from 'react'
import { Modal, Upload, message, Alert } from 'antd'
import { InboxOutlined, FolderOpenOutlined, FileOutlined, ClearOutlined } from '@ant-design/icons'
import type { UploadProps } from 'antd'
import { toolsApi } from '../services/tools-api'

const { Dragger } = Upload

interface SkillUploadModalProps {
  open: boolean
  onClose: () => void
  onSuccess: () => void
}

export default function SkillUploadModal({ open, onClose, onSuccess }: SkillUploadModalProps) {
  const [fileList, setFileList] = useState<File[]>([])
  const [uploading, setUploading] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const dirInputRef = useRef<HTMLInputElement>(null)

  const handleUpload = async () => {
    if (fileList.length === 0) {
      message.warning('请选择要上传的文件或文件夹')
      return
    }

    setUploading(true)
    try {
      const result = await toolsApi.upload(fileList)
      const { created, errors } = result

      if (created.length > 0) {
        message.success(`成功创建 ${created.length} 个 Skill`)
      }
      if (errors.length > 0) {
        message.warning(`${errors.length} 个文件上传失败：${errors.map((e) => e.error).join('; ')}`)
      }

      onSuccess()
      handleClose()
    } catch (err: unknown) {
      const error = err as { message?: string }
      message.error(error?.message ?? '上传失败')
    } finally {
      setUploading(false)
    }
  }

  const handleClose = () => {
    setFileList([])
    // Reset hidden inputs so the same file/dir can be re-selected
    if (fileInputRef.current) fileInputRef.current.value = ''
    if (dirInputRef.current) dirInputRef.current.value = ''
    onClose()
  }

  /* Dragger collects files (single / multi) */
  const draggerProps: UploadProps = {
    name: 'files',
    multiple: true,
    fileList: [] as never,
    beforeUpload: (_file, files) => {
      setFileList((prev) => [...prev, ...files])
      return false
    },
  }

  /* Hidden <input type=file> handlers */
  const handleFileInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files
    if (files && files.length > 0) {
      setFileList((prev) => [...prev, ...Array.from(files)])
    }
    // Reset so same file can be picked again
    e.target.value = ''
  }

  const handleDirInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files
    if (files && files.length > 0) {
      setFileList((prev) => [...prev, ...Array.from(files)])
    }
    e.target.value = ''
  }

  const handleClear = () => {
    setFileList([])
  }

  const handleRemoveFile = (index: number) => {
    setFileList((prev) => prev.filter((_, i) => i !== index))
  }

  return (
    <Modal
      title="上传 Skill"
      open={open}
      onOk={handleUpload}
      onCancel={handleClose}
      okText="上传"
      cancelText="取消"
      confirmLoading={uploading}
      width={600}
      okButtonProps={{ disabled: fileList.length === 0 }}
    >
      <div className="space-y-4">
        <Alert
          message="支持上传单文件 Markdown 或完整目录（目录需包含 SKILL.md 入口文件）"
          type="info"
          showIcon
        />

        {/* Drag-drop area (collects individual files) */}
        <Dragger {...draggerProps} style={{ marginBottom: 16 }}>
          <p className="ant-upload-drag-icon"><InboxOutlined /></p>
          <p className="ant-upload-text">点击或拖拽文件到此区域上传</p>
          <p className="ant-upload-hint">支持多个文件同时上传</p>
        </Dragger>

        {/* Action buttons + hidden inputs */}
        <div className="flex items-center gap-2">
          {/* Hidden file input */}
          <input
            ref={fileInputRef}
            type="file"
            multiple
            onChange={handleFileInputChange}
            style={{ display: 'none' }}
          />
          <button
            type="button"
            className="px-4 py-2 rounded border border-gray-300 bg-white hover:bg-gray-50 text-sm inline-flex items-center gap-1.5"
            onClick={() => fileInputRef.current?.click()}
          >
            <FileOutlined />
            选择文件
          </button>

          {/* Hidden directory input */}
          {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
          <input
            ref={dirInputRef}
            type="file"
            {...({ webkitdirectory: '', directory: '' } as any)}
            onChange={handleDirInputChange}
            style={{ display: 'none' }}
          />
          <button
            type="button"
            className="px-4 py-2 rounded border border-gray-300 bg-white hover:bg-gray-50 text-sm inline-flex items-center gap-1.5"
            onClick={() => dirInputRef.current?.click()}
          >
            <FolderOpenOutlined />
            选择文件夹
          </button>

          <button
            type="button"
            className="px-4 py-2 rounded border border-gray-300 bg-white hover:bg-gray-50 text-sm inline-flex items-center gap-1.5"
            onClick={handleClear}
          >
            <ClearOutlined />
            清空
          </button>

          <span className="ml-auto text-sm text-gray-500">已选 {fileList.length} 个文件</span>
        </div>

        {/* File list preview */}
        {fileList.length > 0 && (
          <div className="text-sm text-gray-600">
            <div className="font-medium mb-1">文件列表：</div>
            <ul className="max-h-40 overflow-y-auto space-y-0.5 border rounded-lg p-2 bg-gray-50">
              {fileList.map((f, i) => (
                <li key={`${f.webkitRelativePath || f.name}-${i}`} className="flex items-center justify-between truncate group">
                  <span className="truncate flex-1">
                    {f.webkitRelativePath || f.name}
                    <span className="text-gray-400 ml-2">({(f.size / 1024).toFixed(1)} KB)</span>
                  </span>
                  <button
                    type="button"
                    className="opacity-0 group-hover:opacity-100 text-gray-400 hover:text-red-500 transition-opacity shrink-0 ml-2"
                    onClick={() => handleRemoveFile(i)}
                    title="移除"
                  >
                    x
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </Modal>
  )
}
