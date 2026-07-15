/**
 * WorkflowInputForm — 按 variables 渲染输入参数表单的可复用受控组件。
 *
 * 从 ExecuteInputDialog 抽出，供两处入口共用：
 *  - 工作流编辑器「执行参数」弹窗（ExecuteInputDialog）
 *  - 定时任务弹窗（TriggerConfigModal）选工作流后的 default_input 收集
 *
 * 半受控：外部持有 value（按变量名聚合的值对象）+ onChange；组件内部只保留
 * 纯 UI 态（文件上传中标记、本次会话上传的文件展示信息）。必填校验由
 * findMissingRequired 计算，通过 onValidityChange 上报；是否显示红框由 showErrors 控制。
 */
import { useState, useRef, useEffect, useMemo } from 'react'
import { Upload, X, File as FileIcon, Loader2 } from 'lucide-react'
import { Input, Select, Switch } from '../../components/ui'
import { uploadFile, type FileRefResponse } from '../../services/file-api'
import { type VariableDefinition, getTypeLabel } from './utils/variable-types'
import { findMissingRequired } from './utils/workflow-input-values'

interface Props {
  variables: VariableDefinition[]
  /** 按变量名聚合的当前值（受控） */
  value: Record<string, unknown>
  onChange: (next: Record<string, unknown>) => void
  /** 必填校验结果变化时上报（valid + 未满足的变量名列表） */
  onValidityChange?: (valid: boolean, missing: string[]) => void
  /** 是否显示必填红框/提示（一般在用户尝试提交后置 true） */
  showErrors?: boolean
  /** 禁用全部输入（如保存中） */
  disabled?: boolean
}

export default function WorkflowInputForm({
  variables,
  value,
  onChange,
  onValidityChange,
  showErrors = false,
  disabled = false,
}: Props) {
  // 文件类型纯 UI 态：上传中标记 + 本次会话上传的文件展示信息（按变量名）
  const [uploading, setUploading] = useState<Record<string, boolean>>({})
  const [files, setFiles] = useState<Record<string, FileRefResponse[]>>({})
  const fileInputRefs = useRef<Record<string, HTMLInputElement | null>>({})

  const missing = useMemo(
    () => findMissingRequired(variables, value),
    [variables, value],
  )
  const missingSet = useMemo(() => new Set(missing), [missing])

  // 上报校验结果
  useEffect(() => {
    onValidityChange?.(missing.length === 0, missing)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [missing])

  /** 更新单个变量值 */
  const update = (name: string, val: unknown) => {
    onChange({ ...value, [name]: val })
  }

  /** 文件选择 → 上传 → 写入值 */
  const handleFilePick = async (v: VariableDefinition, fileList: FileList | null) => {
    if (!fileList || fileList.length === 0) return
    const multiple = !!v.constraints?.multiple
    const allowed = (v.constraints?.allowed_extensions as string[] | undefined) ?? []
    const maxMb = v.constraints?.max_size_mb as number | undefined
    const picked = Array.from(fileList)
    if (allowed.length > 0) {
      const ok = picked.every((f) => {
        const ext = '.' + (f.name.split('.').pop() ?? '').toLowerCase()
        return allowed.map((e) => e.toLowerCase()).includes(ext)
      })
      if (!ok) return // 扩展名不合法：静默忽略（约束信息已在 UI 展示）
    }
    if (maxMb) {
      const oversize = picked.find((f) => f.size > maxMb * 1024 * 1024)
      if (oversize) return
    }
    setUploading((p) => ({ ...p, [v.name]: true }))
    try {
      const uploaded: FileRefResponse[] = []
      for (const f of picked) uploaded.push(await uploadFile(f))
      const cur = value[v.name]
      const mergedValue = multiple
        ? [...((cur as string[]) ?? []), ...uploaded.map((u) => u.id)]
        : uploaded[0]?.id ?? ''
      setFiles((p) => {
        const curFiles = p[v.name] ?? []
        const merged = multiple ? [...curFiles, ...uploaded] : uploaded
        return { ...p, [v.name]: merged }
      })
      update(v.name, mergedValue)
    } catch {
      // 上传失败：静默（上层可由空值感知）
    } finally {
      setUploading((p) => ({ ...p, [v.name]: false }))
    }
  }

  /** 移除本次上传的某个文件 */
  const removeFile = (v: VariableDefinition, idx: number) => {
    const multiple = !!v.constraints?.multiple
    const curFiles = files[v.name] ?? []
    const nextFiles = curFiles.filter((_, i) => i !== idx)
    setFiles((p) => ({ ...p, [v.name]: nextFiles }))
    const nextValue = multiple ? nextFiles.map((f) => f.id) : nextFiles[0]?.id ?? ''
    update(v.name, nextValue)
  }

  const formatSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes}B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`
    return `${(bytes / 1024 / 1024).toFixed(1)}MB`
  }

  return (
    <div className="space-y-4">
      {variables.map((v) => {
        const val = value[v.name]
        const isMissing = showErrors && missingSet.has(v.name)
        const allowed = (v.constraints?.allowed_extensions as string[] | undefined) ?? []
        const multiple = !!v.constraints?.multiple
        const options = (v.constraints?.options as string[] | undefined) ?? []

        return (
          <div key={v.name} className="space-y-1.5">
            {/* 标签 */}
            <div className="flex items-center gap-1.5">
              <span className="text-xs font-medium text-[#fafafa]">{v.label || v.name}</span>
              {v.required && <span className="text-red-400 text-xs">*</span>}
              <span className="text-[10px] text-[#52525b]">({getTypeLabel(v.type)})</span>
            </div>
            {v.description && (
              <p className="text-[10px] text-[#71717a] -mt-0.5">{v.description}</p>
            )}

            {/* 字段 */}
            {(v.type === 'text' || v.type === 'number') && (
              <Input
                type={v.type === 'number' ? 'number' : 'text'}
                value={(val as string) ?? ''}
                status={isMissing ? 'error' : undefined}
                placeholder={v.required ? '必填' : '可选'}
                disabled={disabled}
                onChange={(e) => update(v.name, e.target.value)}
              />
            )}

            {v.type === 'boolean' && (
              <div className="pt-1">
                <Switch checked={!!val} onChange={(c) => update(v.name, c)} />
              </div>
            )}

            {v.type === 'json' && (
              <Input.TextArea
                rows={3}
                value={(val as string) ?? ''}
                placeholder='{"key": "value"}'
                disabled={disabled}
                className={isMissing ? 'border-red-400' : ''}
                onChange={(e) => update(v.name, e.target.value)}
              />
            )}

            {v.type === 'select' && !multiple && (
              <Select
                value={(val as string) || null}
                disabled={disabled}
                onChange={(nv) => update(v.name, nv ?? '')}
                placeholder="请选择"
                options={options.map((o) => ({ value: o, label: o }))}
              />
            )}

            {v.type === 'select' && multiple && (
              <div className="space-y-1.5 rounded-md border border-[#27272a] bg-[#121214] p-2.5">
                {options.length === 0 && (
                  <p className="text-[10px] text-[#71717a]">未配置选项</p>
                )}
                {options.map((o) => {
                  const arr = (val as string[]) ?? []
                  const checked = arr.includes(o)
                  return (
                    <label
                      key={o}
                      className="flex items-center gap-2 text-xs text-[#fafafa] cursor-pointer"
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        disabled={disabled}
                        onChange={() => {
                          const next = checked ? arr.filter((x) => x !== o) : [...arr, o]
                          update(v.name, next)
                        }}
                        className="accent-[#1E5EFF]"
                      />
                      {o}
                    </label>
                  )
                })}
              </div>
            )}

            {v.type === 'file' && (
              <div className="space-y-1.5">
                <input
                  ref={(el) => {
                    fileInputRefs.current[v.name] = el
                  }}
                  type="file"
                  className="hidden"
                  accept={allowed.join(',') || undefined}
                  multiple={multiple}
                  onChange={(e) => handleFilePick(v, e.target.files)}
                />
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => fileInputRefs.current[v.name]?.click()}
                    disabled={disabled || uploading[v.name]}
                    className="flex items-center gap-1.5 px-2.5 h-8 rounded-md bg-[#27272a] text-xs text-[#fafafa] hover:bg-[#3f3f46] disabled:opacity-50 transition cursor-pointer"
                  >
                    {uploading[v.name] ? (
                      <Loader2 size={13} className="animate-spin" />
                    ) : (
                      <Upload size={13} />
                    )}
                    {uploading[v.name] ? '上传中...' : '选择文件'}
                  </button>
                  {allowed.length > 0 && (
                    <span className="text-[10px] text-[#71717a]">{allowed.join(', ')}</span>
                  )}
                </div>
                {/* 本次会话上传的文件（有完整信息，可移除） */}
                {(files[v.name] ?? []).map((f, idx) => (
                  <div
                    key={f.id}
                    className="flex items-center gap-2 px-2 py-1.5 rounded-md bg-[#121214] border border-[#27272a] text-xs"
                  >
                    <FileIcon size={13} className="text-[#F97316] shrink-0" />
                    <span className="text-[#fafafa] truncate flex-1">{f.name}</span>
                    <span className="text-[#71717a] text-[10px] shrink-0">
                      {formatSize(f.size)}
                    </span>
                    <X
                      size={13}
                      className="text-[#71717a] cursor-pointer hover:text-red-400 shrink-0"
                      onClick={() => removeFile(v, idx)}
                    />
                  </div>
                ))}
                {/* 回填但本次未上传的 file id（编辑模式带入，无 name/size） */}
                {!multiple &&
                  typeof val === 'string' &&
                  val &&
                  !(files[v.name] ?? []).some((f) => f.id === val) && (
                    <div className="flex items-center gap-2 px-2 py-1.5 rounded-md bg-[#121214] border border-[#27272a] text-xs">
                      <FileIcon size={13} className="text-[#F97316] shrink-0" />
                      <span className="text-[#71717a] truncate flex-1">已设置文件：{val}</span>
                      <X
                        size={13}
                        className="text-[#71717a] cursor-pointer hover:text-red-400 shrink-0"
                        onClick={() => update(v.name, '')}
                      />
                    </div>
                  )}
              </div>
            )}

            {isMissing && <p className="text-[10px] text-red-400">此项为必填</p>}
          </div>
        )
      })}
    </div>
  )
}
