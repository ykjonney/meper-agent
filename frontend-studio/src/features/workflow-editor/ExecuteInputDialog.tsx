/**
 * ExecuteInputDialog — 工作流执行前的输入参数弹窗。
 *
 * 读取 Start 节点的 output_variables（VariableDefinition[]），按类型渲染表单，
 * 让用户填入运行时输入值；提交时按变量名组装为 input 交给 tasksApi.create。
 * 后端 StartNodeExecutor 按 name 从 task.input 取值，故这里只需按名塞值。
 *
 * file 类型：上传走 uploadFile（POST /api/v1/files，origin_kind=workflow_run），
 * 后端 file_validator 期望 value 为 FileRef id 字符串或 id 列表。
 */
import { useState, useMemo, useRef, useEffect } from 'react'
import { Upload, X, File as FileIcon, Loader2 } from 'lucide-react'
import { Modal, Input, Select, Switch } from '../../components/ui'
import { uploadFile, type FileRefResponse } from '../../services/file-api'
import {
  type VariableDefinition,
  getTypeLabel,
} from './utils/variable-types'

interface Props {
  open: boolean
  variables: VariableDefinition[]
  onCancel: () => void
  onSubmit: (values: Record<string, unknown>) => void
}

/** 单个变量的渲染态：值 + 上传态 + 已上传文件信息 */
interface FieldState {
  // text/number/boolean/select-single/json 存标量；select-multiple/file-multiple 存数组
  value: unknown
  uploading: boolean
  // file 类型用：已上传文件展示信息（单/多）
  files: FileRefResponse[]
}

function initState(variables: VariableDefinition[]): Record<string, FieldState> {
  const out: Record<string, FieldState> = {}
  for (const v of variables) {
    const dv = v.constraints?.default_value
    let value: unknown
    const multiple = !!v.constraints?.multiple
    switch (v.type) {
      case 'boolean':
        value = typeof dv === 'boolean' ? dv : false
        break
      case 'select':
        value = multiple ? (Array.isArray(dv) ? dv : []) : typeof dv === 'string' ? dv : ''
        break
      case 'file':
        value = multiple ? [] : ''
        break
      case 'number':
        value = dv !== null && dv !== undefined && dv !== '' ? String(dv) : ''
        break
      default:
        value = typeof dv === 'string' ? dv : dv !== null && dv !== undefined ? String(dv) : ''
    }
    out[v.name] = { value, uploading: false, files: [] }
  }
  return out
}

/** 必填校验：返回未满足的变量名集合 */
function findMissingRequired(
  variables: VariableDefinition[],
  states: Record<string, FieldState>,
): string[] {
  const missing: string[] = []
  for (const v of variables) {
    if (!v.required) continue
    const s = states[v.name]
    if (!s) {
      missing.push(v.name)
      continue
    }
    const val = s.value
    if (v.type === 'file' || (v.type === 'select' && v.constraints?.multiple)) {
      if (!Array.isArray(val) || val.length === 0) missing.push(v.name)
    } else if (v.type === 'boolean') {
      // boolean 总有值，跳过
    } else {
      if (val === null || val === undefined || String(val).trim() === '') missing.push(v.name)
    }
  }
  return missing
}

export default function ExecuteInputDialog({ open, variables, onCancel, onSubmit }: Props) {
  const [states, setStates] = useState<Record<string, FieldState>>(() => initState(variables))
  const [submitError, setSubmitError] = useState<string | null>(null)
  // 记录用户尝试过提交，用于显示字段错误
  const [touched, setTouched] = useState(false)
  // 文件 input 引用（按变量名）
  const fileInputRefs = useRef<Record<string, HTMLInputElement | null>>({})

  // 每次打开时重置表单（清空上次输入 / 上传 / 错误）
  useEffect(() => {
    if (open) {
      setStates(initState(variables))
      setSubmitError(null)
      setTouched(false)
    }
  }, [open, variables])

  // variables 变化时重置（切换工作流/重新打开）
  // 用 useMemo 派生 missing；初始化用 useState 仅首次，open 切换时通过 key 重置
  const missing = useMemo(() => findMissingRequired(variables, states), [variables, states])
  const missingSet = useMemo(() => new Set(missing), [missing])

  /** 更新单个字段值 */
  const update = (name: string, patch: Partial<FieldState>) => {
    setStates((prev) => ({ ...prev, [name]: { ...prev[name], ...patch } }))
  }

  /** 处理文件选择 → 上传 */
  const handleFilePick = async (v: VariableDefinition, fileList: FileList | null) => {
    if (!fileList || fileList.length === 0) return
    const multiple = !!v.constraints?.multiple
    const allowed = (v.constraints?.allowed_extensions as string[] | undefined) ?? []
    const maxMb = v.constraints?.max_size_mb as number | undefined
    // 前端轻量预检（扩展名 / 大小），其余交给后端
    const picked = Array.from(fileList)
    if (allowed.length > 0) {
      const ok = picked.every((f) => {
        const ext = '.' + (f.name.split('.').pop() ?? '').toLowerCase()
        return allowed.map((e) => e.toLowerCase()).includes(ext)
      })
      if (!ok) {
        setSubmitError(`文件扩展名不被允许，仅支持：${allowed.join(', ')}`)
        return
      }
    }
    if (maxMb) {
      const oversize = picked.find((f) => f.size > maxMb * 1024 * 1024)
      if (oversize) {
        setSubmitError(`文件 ${oversize.name} 超过最大限制 ${maxMb}MB`)
        return
      }
    }
    setSubmitError(null)
    update(v.name, { uploading: true })
    try {
      const uploaded: FileRefResponse[] = []
      for (const f of picked) {
        uploaded.push(await uploadFile(f))
      }
      setStates((prev) => {
        const cur = prev[v.name]
        const mergedFiles = multiple ? [...cur.files, ...uploaded] : uploaded
        const mergedValue = multiple
          ? [...((cur.value as string[]) ?? []), ...uploaded.map((u) => u.id)]
          : uploaded[0]?.id ?? ''
        return { ...prev, [v.name]: { ...cur, files: mergedFiles, value: mergedValue } }
      })
    } catch (err) {
      setSubmitError(err instanceof Error ? `上传失败：${err.message}` : '文件上传失败')
    } finally {
      update(v.name, { uploading: false })
    }
  }

  /** 移除已上传文件 */
  const removeFile = (v: VariableDefinition, idx: number) => {
    const multiple = !!v.constraints?.multiple
    setStates((prev) => {
      const cur = prev[v.name]
      const files = cur.files.filter((_, i) => i !== idx)
      let value: unknown
      if (multiple) {
        value = files.map((f) => f.id)
      } else {
        value = files[0]?.id ?? ''
      }
      return { ...prev, [v.name]: { ...cur, files, value } }
    })
  }

  /** 提交：按类型强转并组装 input */
  const handleSubmit = () => {
    setTouched(true)
    if (missing.length > 0) return
    const out: Record<string, unknown> = {}
    for (const v of variables) {
      const s = states[v.name]
      if (!s) continue
      const val = s.value
      switch (v.type) {
        case 'number': {
          if (val === '' || val === null || val === undefined) continue // 空 → 不传，后端用 default/None
          const n = Number(val)
          if (Number.isNaN(n)) continue
          out[v.name] = n
          break
        }
        case 'boolean':
          out[v.name] = !!val
          break
        case 'json': {
          if (typeof val === 'string' && val.trim() === '') continue
          try {
            out[v.name] = typeof val === 'string' ? JSON.parse(val) : val
          } catch {
            setSubmitError(`变量 ${v.label} 的 JSON 解析失败`)
            return
          }
          break
        }
        case 'select': {
          if (v.constraints?.multiple) {
            const arr = (val as string[]) ?? []
            if (arr.length === 0) continue
            out[v.name] = arr
          } else {
            if (val === '' || val === null || val === undefined) continue
            out[v.name] = val
          }
          break
        }
        case 'file': {
          if (v.constraints?.multiple) {
            const arr = (val as string[]) ?? []
            if (arr.length === 0) continue
            out[v.name] = arr
          } else {
            if (!val) continue
            out[v.name] = val
          }
          break
        }
        default: {
          // text
          if (val === '' || val === null || val === undefined) continue
          out[v.name] = val
        }
      }
    }
    onSubmit(out)
  }

  const formatSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes}B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`
    return `${(bytes / 1024 / 1024).toFixed(1)}MB`
  }

  return (
    <Modal
      open={open}
      title="执行参数"
      onCancel={onCancel}
      onOk={handleSubmit}
      okText="执行"
      cancelText="取消"
      width={520}
      okButtonProps={{ disabled: missing.length > 0 }}
    >
      <div className="space-y-4">
        <p className="text-[11px] text-[#71717a]">
          开始节点定义了输入变量，请填入本次执行所需的参数。未填的可选变量将使用默认值。
        </p>

        {variables.map((v) => {
          const s = states[v.name]
          if (!s) return null
          const isMissing = touched && missingSet.has(v.name)
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
                  value={s.value as string}
                  status={isMissing ? 'error' : undefined}
                  placeholder={v.required ? '必填' : '可选'}
                  onChange={(e) => update(v.name, { value: e.target.value })}
                />
              )}

              {v.type === 'boolean' && (
                <div className="pt-1">
                  <Switch checked={!!s.value} onChange={(c) => update(v.name, { value: c })} />
                </div>
              )}

              {v.type === 'json' && (
                <Input.TextArea
                  rows={3}
                  value={s.value as string}
                  placeholder='{"key": "value"}'
                  className={isMissing ? 'border-red-400' : ''}
                  onChange={(e) => update(v.name, { value: e.target.value })}
                />
              )}

              {v.type === 'select' && !multiple && (
                <Select
                  value={(s.value as string) || null}
                  onChange={(val) => update(v.name, { value: val ?? '' })}
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
                    const arr = (s.value as string[]) ?? []
                    const checked = arr.includes(o)
                    return (
                      <label key={o} className="flex items-center gap-2 text-xs text-[#fafafa] cursor-pointer">
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={() => {
                            const next = checked ? arr.filter((x) => x !== o) : [...arr, o]
                            update(v.name, { value: next })
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
                    ref={(el) => { fileInputRefs.current[v.name] = el }}
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
                      disabled={s.uploading}
                      className="flex items-center gap-1.5 px-2.5 h-8 rounded-md bg-[#27272a] text-xs text-[#fafafa] hover:bg-[#3f3f46] disabled:opacity-50 transition cursor-pointer"
                    >
                      {s.uploading ? <Loader2 size={13} className="animate-spin" /> : <Upload size={13} />}
                      {s.uploading ? '上传中...' : multiple ? '选择文件' : '选择文件'}
                    </button>
                    {allowed.length > 0 && (
                      <span className="text-[10px] text-[#71717a]">{allowed.join(', ')}</span>
                    )}
                  </div>
                  {s.files.map((f, idx) => (
                    <div
                      key={f.id}
                      className="flex items-center gap-2 px-2 py-1.5 rounded-md bg-[#121214] border border-[#27272a] text-xs"
                    >
                      <FileIcon size={13} className="text-[#F97316] shrink-0" />
                      <span className="text-[#fafafa] truncate flex-1">{f.name}</span>
                      <span className="text-[#71717a] text-[10px] shrink-0">{formatSize(f.size)}</span>
                      <X
                        size={13}
                        className="text-[#71717a] cursor-pointer hover:text-red-400 shrink-0"
                        onClick={() => removeFile(v, idx)}
                      />
                    </div>
                  ))}
                </div>
              )}

              {isMissing && (
                <p className="text-[10px] text-red-400">此项为必填</p>
              )}
            </div>
          )
        })}

        {submitError && (
          <div className="px-3 py-2 rounded-md bg-red-500/10 border border-red-500/20 text-[11px] text-red-400">
            {submitError}
          </div>
        )}
      </div>
    </Modal>
  )
}
