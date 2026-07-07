/**
 * VariableFormField — 根据 VariableDefinition 渲染对应的表单控件。
 *
 * 从 workflow-detail-page.tsx 提取，供 TestRunModal 和 TriggerConfigModal 共用。
 */
import { Input, Button, Upload, Tooltip, message } from 'antd'
import { UploadOutlined, DeleteOutlined, FileOutlined } from '@ant-design/icons'
import type { VariableDefinition } from './utils/variable-types'
import { getTypeColor, getTypeIcon, getTypeLabel } from './utils/variable-types'
import { filesApi, getFileId } from '../../services/files-api'

export default function VariableFormField({
  variable,
  value,
  onChange,
  disabled = false,
}: {
  variable: VariableDefinition
  value: unknown
  onChange: (val: unknown) => void
  disabled?: boolean
}) {
  const label = variable.label || variable.name
  const desc = variable.description
  const required = !!variable.constraints?.required
  const type = variable.type

  let input: React.ReactNode = null

  switch (type) {
    case 'text': {
      const maxLen = variable.constraints?.max_length as number | undefined
      input = (
        <Input.TextArea
          value={value as string ?? ''}
          onChange={(e) => onChange(e.target.value)}
          rows={2}
          className="!font-mono !text-xs"
          placeholder={`输入${label}...`}
          maxLength={maxLen ?? undefined}
          showCount={!!maxLen}
        />
      )
      break
    }
    case 'number': {
      const min = variable.constraints?.min as number | undefined
      const max = variable.constraints?.max as number | undefined
      input = (
        <Input
          type="number"
          value={value as string ?? ''}
          onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)}
          className="!text-xs"
          min={min}
          max={max}
          placeholder={`输入${label}...`}
        />
      )
      break
    }
    case 'boolean':
      input = (
        <select
          value={value === true ? 'true' : value === false ? 'false' : ''}
          onChange={(e) => {
            if (e.target.value === '') onChange(null)
            else onChange(e.target.value === 'true')
          }}
          className="w-full border border-gray-200 rounded-lg px-2 py-1.5 text-xs"
        >
          <option value="">请选择...</option>
          <option value="true">是</option>
          <option value="false">否</option>
        </select>
      )
      break
    case 'json':
      input = (
        <Input.TextArea
          value={typeof value === 'string' ? value : JSON.stringify(value ?? '', null, 2)}
          onChange={(e) => {
            const raw = e.target.value
            try { onChange(raw ? JSON.parse(raw) : null) }
            catch { onChange(raw) }
          }}
          rows={3}
          className="!font-mono !text-xs"
          placeholder='{"key": "value"}'
        />
      )
      break
    case 'select': {
      const options = variable.constraints?.options as string[] | undefined
      const multiple = variable.constraints?.multiple as boolean | undefined
      const opts = Array.isArray(options) ? options : []
      if (multiple) {
        input = (
          <div className="flex flex-wrap gap-1.5">
            {opts.map((opt) => (
              <label key={opt} className="flex items-center gap-1 text-xs cursor-pointer">
                <input
                  type="checkbox"
                  checked={Array.isArray(value) && value.includes(opt)}
                  onChange={(e) => {
                    const arr = Array.isArray(value) ? [...value] : []
                    if (e.target.checked) arr.push(opt)
                    else arr.splice(arr.indexOf(opt), 1)
                    onChange(arr.length > 0 ? arr : null)
                  }}
                />
                {opt}
              </label>
            ))}
            {opts.length === 0 && (
              <span className="text-[10px] text-[#94A3B8]">无可选值</span>
            )}
          </div>
        )
      } else {
        input = (
          <select
            value={value as string ?? ''}
            onChange={(e) => onChange(e.target.value || null)}
            className="w-full border border-gray-200 rounded-lg px-2 py-1.5 text-xs"
          >
            <option value="">{required ? '请选择...' : '可选'}</option>
            {opts.map((opt) => (
              <option key={opt} value={opt}>{opt}</option>
            ))}
          </select>
        )
      }
      break
    }
    case 'file': {
      const multiple = variable.constraints?.multiple as boolean | undefined
      const allowedExts = variable.constraints?.allowed_extensions as string[] | undefined
      const maxSizeMb = variable.constraints?.max_size_mb as number | undefined

      // Parse current value(s) to file info
      const fileIds: string[] = Array.isArray(value)
        ? value.map((v) => String(v))
        : value
          ? [String(value)]
          : []

      const accept = allowedExts?.map((ext) => ext.startsWith('.') ? ext : `.${ext}`).join(',') || undefined
      const maxBytes = maxSizeMb ? maxSizeMb * 1024 * 1024 : undefined

      const handleUpload = async (file: File) => {
        // Validate size
        if (maxBytes && file.size > maxBytes) {
          message.error(`文件 "${file.name}" 超过大小限制 (${maxSizeMb}MB)`)
          return false
        }

        try {
          const ref = await filesApi.upload(file, 'workflow_input')
          const fileId = getFileId(ref)

          if (multiple) {
            const current = Array.isArray(value) ? value : []
            onChange([...current, fileId])
          } else {
            onChange(fileId)
          }
          message.success(`文件 "${file.name}" 上传成功`)
        } catch (err) {
          const msg = err && typeof err === 'object' && 'message' in err
            ? (err as { message: string }).message : '上传失败'
          message.error(msg)
        }
        return false // Prevent default upload
      }

      const handleRemove = (fileId: string) => {
        if (multiple) {
          const current = Array.isArray(value) ? value : []
          onChange(current.filter((id) => String(id) !== fileId))
        } else {
          onChange(null)
        }
      }

      input = (
        <div className="space-y-1.5">
          <Upload
            beforeUpload={handleUpload}
            showUploadList={false}
            accept={accept}
            multiple={multiple}
            disabled={disabled}
          >
            <Button icon={<UploadOutlined />} size="small" loading={disabled}>
              {multiple ? '上传文件' : '选择文件'}
            </Button>
          </Upload>

          {fileIds.length > 0 && (
            <div className="space-y-1">
              {fileIds.map((fileId) => (
                <div
                  key={fileId}
                  className="flex items-center gap-2 px-2 py-1 bg-gray-50 rounded text-xs"
                >
                  <FileOutlined className="text-orange-500" />
                  <span className="flex-1 truncate font-mono" title={fileId}>
                    {fileId}
                  </span>
                  <Tooltip title="移除">
                    <Button
                      type="text"
                      size="small"
                      icon={<DeleteOutlined />}
                      danger
                      onClick={() => handleRemove(fileId)}
                      disabled={disabled}
                    />
                  </Tooltip>
                </div>
              ))}
            </div>
          )}

          {!multiple && fileIds.length > 0 && (
            <p className="text-[10px] text-[#94A3B8]">
              已选择 1 个文件
            </p>
          )}
          {multiple && fileIds.length > 0 && (
            <p className="text-[10px] text-[#94A3B8]">
              已选择 {fileIds.length} 个文件
            </p>
          )}
        </div>
      )
      break
    }
    default:
      input = (
        <Input
          value={value as string ?? ''}
          onChange={(e) => onChange(e.target.value)}
          className="!text-xs"
          placeholder={`输入${label}...`}
        />
      )
  }

  return (
    <div className="space-y-1">
      <div className="flex items-center gap-1.5">
        <span
          className="inline-flex items-center justify-center w-3.5 h-3.5 rounded text-[8px] font-bold text-white shrink-0"
          style={{ backgroundColor: getTypeColor(type) }}
        >
          {getTypeIcon(type)}
        </span>
        <label className="text-xs text-[#0F172A] font-medium">
          {label}
          {required && <span className="text-red-400 ml-0.5">*</span>}
        </label>
        <span className="text-[10px] text-[#94A3B8]">({getTypeLabel(type)})</span>
      </div>
      {desc && <p className="text-[10px] text-[#94A3B8] -mt-0.5">{desc}</p>}
      {input}
    </div>
  )
}
