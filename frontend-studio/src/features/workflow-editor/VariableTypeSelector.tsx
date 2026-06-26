/**
 * VariableTypeSelector — 变量类型选择器组件。
 *
 * 功能：
 * 1. 类型下拉框（Select 组件，带颜色 icon）
 * 2. 根据选中类型动态显示约束表单
 * 3. 支持编辑模式下回填已有变量配置
 *
 * antd 组件 → 原生 Tailwind ui 封装。
 */
import { useMemo } from 'react'
import { Select, Input, Switch, Tag } from '../../components/ui'
import type { VariableTypeName, VariableDefinition } from './utils/variable-types'
import {
  VARIABLE_TYPE_CONFIGS,
  getTypeIcon,
  getDefaultConstraints,
} from './utils/variable-types'

/* ─── Props ─── */

export interface VariableTypeSelectorProps {
  /** 当前编辑的变量（新建时为 undefined） */
  value?: Partial<VariableDefinition>
  /** 值变更回调 */
  onChange: (updates: Partial<VariableDefinition>) => void
  /** 是否显示名称和标签字段（在 Modal 中编辑时显示） */
  showMeta?: boolean
  /** 已存在的变量名列表（用于校验重名） */
  existingNames?: string[]
}

/* ─── 约束字段渲染 ─── */

function renderConstraintField(
  fieldDef: { name: string; label: string; valueType: string; placeholder?: string; min?: number; max?: number },
  value: unknown,
  onChange: (name: string, val: unknown) => void,
) {
  switch (fieldDef.valueType) {
    case 'number':
      return (
        <Input
          type="number"
          value={value as number ?? ''}
          onChange={(e) => {
            const v = e.target.value
            onChange(fieldDef.name, v === '' ? null : Number(v))
          }}
          placeholder={fieldDef.placeholder}
          className="!text-xs"
        />
      )
    case 'string':
      return (
        <Input
          value={value as string ?? ''}
          onChange={(e) => onChange(fieldDef.name, e.target.value)}
          placeholder={fieldDef.placeholder}
          className="!text-xs"
        />
      )
    case 'boolean':
      return (
        <Switch
          checked={!!value}
          onChange={(checked) => onChange(fieldDef.name, checked)}
        />
      )
    case 'json':
      return (
        <Input.TextArea
          rows={2}
          value={
            value
              ? typeof value === 'string'
                ? value
                : JSON.stringify(value, null, 2)
              : ''
          }
          onChange={(e) => {
            const raw = e.target.value
            try {
              onChange(fieldDef.name, raw ? JSON.parse(raw) : null)
            } catch {
              onChange(fieldDef.name, raw)
            }
          }}
          placeholder={fieldDef.placeholder}
          className="!text-xs font-mono"
        />
      )
    case 'tags':
      return (
        <Input
          value={Array.isArray(value) ? value.join(', ') : ''}
          onChange={(e) => {
            const tags = e.target.value
              .split(',')
              .map((t) => t.trim())
              .filter(Boolean)
            onChange(fieldDef.name, tags)
          }}
          placeholder={fieldDef.placeholder}
          className="!text-xs"
        />
      )
    default:
      return null
  }
}

/* ─── 类型选项 ─── */

const TYPE_OPTIONS = (Object.entries(VARIABLE_TYPE_CONFIGS) as [VariableTypeName, typeof VARIABLE_TYPE_CONFIGS[VariableTypeName]][]).map(
  ([key, cfg]) => ({
    value: key,
    label: (
      <div className="flex items-center gap-2">
        <span
          className="inline-flex items-center justify-center w-5 h-5 rounded text-[10px] font-bold text-white"
          style={{ backgroundColor: cfg.color }}
        >
          {cfg.icon}
        </span>
        <span>{cfg.label}</span>
        <span className="text-[10px] text-[#71717a]">({cfg.description})</span>
      </div>
    ),
  }),
)

/* ─── Component ─── */

export default function VariableTypeSelector({
  value,
  onChange,
  showMeta = false,
  existingNames = [],
}: VariableTypeSelectorProps) {
  const currentType = (value?.type as VariableTypeName) ?? 'text'
  const typeConfig = VARIABLE_TYPE_CONFIGS[currentType]
  const constraintFields = typeConfig?.constraintFields ?? []

  const handleTypeChange = (newType: string | null) => {
    if (!newType) return
    const defaults = getDefaultConstraints(newType as VariableTypeName)
    onChange({
      ...value,
      type: newType as VariableTypeName,
      constraints: defaults,
    })
  }

  const handleConstraintChange = (name: string, val: unknown) => {
    onChange({
      ...value,
      constraints: { ...(value?.constraints ?? {}), [name]: val },
    })
  }

  // 检查名称是否重复
  const nameError = useMemo(() => {
    if (!value?.name || !showMeta) return null
    if (existingNames.includes(value.name)) return '变量名已存在'
    if (!/^[a-zA-Z_][a-zA-Z0-9_]*$/.test(value.name)) return '变量名须以字母或下划线开头，仅含字母、数字、下划线'
    return null
  }, [value?.name, existingNames, showMeta])

  return (
    <div className="space-y-3">
      {/* 类型选择 */}
      <div>
        <label className="block text-xs text-slate-400 mb-1">类型</label>
        <Select
          className="w-full"
          value={currentType}
          onChange={handleTypeChange}
          options={TYPE_OPTIONS}
        />
      </div>

      {/* 变量名（编辑时可选） */}
      {showMeta && (
        <>
          <div>
            <label className="block text-xs text-slate-400 mb-1">
              变量名 <span className="text-red-400">*</span>
            </label>
            <Input
              value={value?.name ?? ''}
              onChange={(e) => onChange({ ...value, name: e.target.value })}
              placeholder="如 user_query"
              className={`!text-xs ${nameError ? '!border-red-400' : ''}`}
              status={nameError ? 'error' : undefined}
            />
            {nameError && (
              <p className="text-[10px] text-red-400 mt-0.5">{nameError}</p>
            )}
          </div>
          <div>
            <label className="block text-xs text-slate-400 mb-1">显示标签</label>
            <Input
              value={value?.label ?? ''}
              onChange={(e) => onChange({ ...value, label: e.target.value })}
              placeholder="如 用户查询"
              className="!text-xs"
            />
          </div>
          <div>
            <label className="block text-xs text-slate-400 mb-1">描述</label>
            <Input
              value={value?.description ?? ''}
              onChange={(e) => onChange({ ...value, description: e.target.value })}
              placeholder="变量的简短说明"
              className="!text-xs"
            />
          </div>
        </>
      )}

      {/* 动态约束表单 */}
      {constraintFields.length > 0 && (
        <div className="border border-[#27272a]/60 rounded-lg p-2.5 bg-[#121214]/60">
          <p className="text-[10px] text-slate-400 font-medium mb-2">约束</p>
          <div className="space-y-2">
            {constraintFields.map((field) => (
              <div key={field.name}>
                <label className="block text-[10px] text-[#71717a] mb-0.5">
                  {field.label}
                </label>
                {renderConstraintField(
                  field,
                  value?.constraints?.[field.name],
                  handleConstraintChange,
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 当前类型摘要 */}
      <div className="flex items-center gap-1.5">
        <Tag
          className="!m-0 !text-[10px] !px-1.5 !py-0"
          color={typeConfig?.color ?? '#64748B'}
        >
          {getTypeIcon(currentType)} {typeConfig?.label ?? currentType}
        </Tag>
        <span className="text-[10px] text-[#71717a]">{typeConfig?.description}</span>
      </div>
    </div>
  )
}
