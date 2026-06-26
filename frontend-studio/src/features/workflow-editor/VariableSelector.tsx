/**
 * VariableSelector — 变量选择器组件（增强版）。
 *
 * 功能：
 * 1. 文本输入框 + 「选择变量」按钮
 * 2. 点击按钮弹出选择面板，按上游节点分组展示可用字段
 * 3. 每个字段显示为可点击的 Tag，点击插入 `{{node_id.field}}`
 * 4. 已插入的变量以 Tag 展示在按钮旁（可删除）
 * 5. 变量总数显示在按钮上
 * 6. 每个字段 Tag 显示类型图标 + 颜色（v2 新增）
 * 7. 优先读取 config.output_variables（用户自定义），无则 fallback 到静态表（v2 新增）
 *
 * antd 组件 → 原生 Tailwind ui 封装；@ant-design/icons → lucide-react。
 */
import { useState, useMemo, useRef, useCallback, Fragment } from 'react'
import { Button, Popover, Tag, Input, Badge, Tooltip } from '../../components/ui'
import { Code } from 'lucide-react'
import type { WorkflowNode } from '../../services/workflows-api'
import { computeUpstreamNodes } from './utils/dag-utils'
import { getEffectiveOutputVariables } from './utils/node-output-variables'
import type { NodeOutputField } from './utils/node-output-variables'
import type { VariableDefinition } from './utils/variable-types'
import {
  getTypeIcon,
  getTypeColor,
  getTypeLabel,
  formatConstraints,
} from './utils/variable-types'

/* ─── Types ─── */

export interface VariableSelectorProps {
  /** 当前文本值 */
  value: string
  /** 值变更回调 */
  onChange: (value: string) => void
  /** 当前编辑的节点 ID */
  currentNodeId: string
  /** 所有工作流节点 */
  allNodes: WorkflowNode[]
  /** 占位符文本 */
  placeholder?: string
  /** 文本域行数 */
  rows?: number
  /** 是否多行文本域 */
  textarea?: boolean
  /** 标签文本 */
  label?: string
  /** 是否必填（显示红色星号） */
  required?: boolean
}

/* ─── 上游字段的统一类型 ─── */

interface UpstreamField {
  name: string
  label: string
  type: string
  description: string
  /** 是否为用户自定义变量（来自 config.output_variables） */
  isUserDefined: boolean
  /** 约束信息（仅用户自定义变量有） */
  constraints: Record<string, unknown> | null
}

/* ─── 解析已插入的变量 ─── */

const VARIABLE_REGEX = /\{\{(\w+)\.(\w+)\}\}/g

interface ParsedVariable {
  raw: string
  nodeId: string
  field: string
  index: number
}

function parseVariables(text: string): ParsedVariable[] {
  const result: ParsedVariable[] = []
  let match: RegExpExecArray | null
  let idx = 0
  VARIABLE_REGEX.lastIndex = 0
  while ((match = VARIABLE_REGEX.exec(text)) !== null) {
    result.push({ raw: match[0], nodeId: match[1], field: match[2], index: idx++ })
  }
  return result
}

/* ─── 字段类型转换 ─── */

/**
 * 将静态表类型名（string/object/any/number/boolean）转换为变量类型系统的显示信息
 */
function mapLegacyType(type: string): { icon: string; color: string; label: string } {
  switch (type) {
    case 'string':
      return { icon: 'T', color: '#3B82F6', label: '文本' }
    case 'number':
      return { icon: '#', color: '#F59E0B', label: '数字' }
    case 'boolean':
      return { icon: '✔', color: '#8B5CF6', label: '布尔' }
    case 'object':
    case 'any':
    default:
      return { icon: '{}', color: '#64748B', label: type }
  }
}

/**
 * 获取变量类型的显示信息（兼容新旧类型系统）
 */
function getTypeDisplayInfo(type: string): { icon: string; color: string; label: string } {
  // 先尝试新类型系统
  const icon = getTypeIcon(type)
  if (icon !== '?') {
    return { icon, color: getTypeColor(type), label: getTypeLabel(type) }
  }
  // fallback 到旧类型系统
  return mapLegacyType(type)
}

/* ─── 转换上游节点为统一字段列表 ─── */

function convertToUpstreamFields(variable: VariableDefinition | NodeOutputField): UpstreamField {
  // 判断是否为用户自定义变量（有 constraints 字段）
  const isUserDefined = 'constraints' in variable

  const base: UpstreamField = {
    name: variable.name,
    label: variable.label,
    type: isUserDefined ? (variable as VariableDefinition).type : (variable as NodeOutputField).type,
    description: variable.description ?? '',
    isUserDefined,
    constraints: isUserDefined ? (variable as VariableDefinition).constraints ?? null : null,
  }

  return base
}

/* ─── 提取上游节点及其分组 ─── */

interface UpstreamGroup {
  nodeId: string
  nodeLabel: string
  nodeType: string
  color: string
  fields: UpstreamField[]
}

const NODE_COLORS: Record<string, string> = {
  start: '#10B981',
  end: '#EF4444',
  agent: '#3B82F6',
  tool: '#F59E0B',
  gateway: '#8B5CF6',
  parallel: '#06B6D4',
  human: '#F97316',
}

function getNodeColor(type: string): string {
  return NODE_COLORS[type] ?? '#64748B'
}

/* ─── 组件 ─── */

export default function VariableSelector({
  value,
  onChange,
  currentNodeId,
  allNodes,
  placeholder = '',
  rows = 3,
  textarea = true,
  label,
  required = false,
}: VariableSelectorProps) {
  const [popoverOpen, setPopoverOpen] = useState(false)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  /* ─── 计算上游节点分组 ─── */
  const upstreamGroups = useMemo<UpstreamGroup[]>(() => {
    const upstreamMap = computeUpstreamNodes(currentNodeId, allNodes)
    const groups: UpstreamGroup[] = []

    for (const [nodeId, node] of upstreamMap) {
      const fields = getEffectiveOutputVariables(node)
      // fields 可能是 VariableDefinition[] 或 NodeOutputField[]
      const upstreamFields = (fields as (VariableDefinition | NodeOutputField)[])
        .map(convertToUpstreamFields)
        .filter((f) => f.name) // 过滤空名

      if (upstreamFields.length === 0) continue
      groups.push({
        nodeId,
        nodeLabel: node.label || node.type,
        nodeType: node.type,
        color: getNodeColor(node.type),
        fields: upstreamFields,
      })
    }

    return groups
  }, [currentNodeId, allNodes])

  /* ─── 可用变量总数 ─── */
  const totalAvailableVars = useMemo(
    () => upstreamGroups.reduce((sum, g) => sum + g.fields.length, 0),
    [upstreamGroups],
  )

  /* ─── 插入变量 ─── */
  const handleInsertVariable = useCallback(
    (nodeId: string, field: string) => {
      const variable = `{{${nodeId}.${field}}}`
      const ta = inputRef.current
      if (ta) {
        const start = ta.selectionStart ?? value.length
        const end = ta.selectionEnd ?? value.length
        const newValue = value.substring(0, start) + variable + value.substring(end)
        onChange(newValue)
        requestAnimationFrame(() => {
          const pos = start + variable.length
          ta.setSelectionRange(pos, pos)
          ta.focus()
        })
      } else {
        onChange(value ? `${value}\n${variable}` : variable)
      }
      setPopoverOpen(false)
    },
    [value, onChange],
  )

  /* ─── 已解析的变量列表 ─── */
  const parsedVars = useMemo(() => parseVariables(value), [value])

  /* ─── 删除指定变量 ─── */
  const handleRemoveVariable = useCallback(
    (parsed: ParsedVariable) => {
      const newValue = value.replace(parsed.raw, '').trim()
      onChange(newValue)
    },
    [value, onChange],
  )

  /* ─── 渲染字段 Tag ─── */
  const renderFieldTag = (field: UpstreamField, group: UpstreamGroup) => {
    const typeInfo = getTypeDisplayInfo(field.type)
    const tooltipContent = (
      <div className="text-[11px]">
        <div><strong>{field.label}</strong> ({field.name})</div>
        <div className="text-[10px] mt-0.5">{field.description}</div>
        <div className="flex items-center gap-1 mt-1">
          <span
            className="inline-flex items-center justify-center w-3.5 h-3.5 rounded text-[8px] font-bold text-white"
            style={{ backgroundColor: typeInfo.color }}
          >
            {typeInfo.icon}
          </span>
          <span className="text-[10px]">类型: {typeInfo.label}</span>
        </div>
        {field.constraints && field.isUserDefined && (
          <div className="text-[10px] text-[#71717a] mt-0.5">
            约束: {formatConstraints(field.constraints)}
          </div>
        )}
        {field.isUserDefined && (
          <div className="text-[10px] text-[#3B82F6] mt-0.5">用户自定义变量</div>
        )}
      </div>
    )

    return (
      <Tooltip title={tooltipContent}>
        <Tag
          className="!m-0 !cursor-pointer !text-[11px] !px-1.5 !py-0.5 !rounded hover:!opacity-80 transition-opacity !inline-flex !items-center !gap-1"
          color="blue"
          onClick={() => handleInsertVariable(group.nodeId, field.name)}
        >
          {/* 类型图标 */}
          {/* 类型图标 */}
          {/* 类型图标 */}
          <span
            className="inline-flex items-center justify-center w-3.5 h-3.5 rounded text-[8px] font-bold text-white shrink-0"
            style={{ backgroundColor: typeInfo.color }}
          >
            {typeInfo.icon}
          </span>
          {field.label}
        </Tag>
      </Tooltip>
    )
  }

  /* ─── Popover 内容 ─── */
  const popoverContent = (
    <div className="w-72 max-h-72 overflow-y-auto">
      {upstreamGroups.length === 0 ? (
        <div className="text-xs text-[#71717a] text-center py-4">
          <Code className="text-base mb-2 block mx-auto" size={18} />
          暂无可用变量
          <div className="text-[10px] mt-1 text-[#CBD5E1]">
            请先在画布中连接上游节点
          </div>
        </div>
      ) : (
        <div className="space-y-0.5">
          {upstreamGroups.map((group) => (
            <div key={group.nodeId} className="mb-2.5 last:mb-0">
              {/* 节点头部 */}
              <div className="flex items-center gap-1.5 mb-1.5 px-0.5">
                <span
                  className="w-2 h-2 rounded-full inline-block shrink-0"
                  style={{ backgroundColor: group.color }}
                />
                <span className="text-xs font-medium text-[#fafafa] truncate">
                  {group.nodeLabel}
                </span>
                <span className="text-[10px] text-[#71717a] font-mono ml-auto shrink-0">
                  {group.nodeId}
                </span>
              </div>
              {/* 字段 Tag 列表 */}
              <div className="flex flex-wrap gap-1.5">
                {group.fields.map((field) => (
                  <Fragment key={field.name}>{renderFieldTag(field, group)}</Fragment>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )

  /* ─── 已使用变量数量（去重） ─── */
  const uniqueUsedCount = useMemo(
    () => new Set(parsedVars.map((p) => `${p.nodeId}.${p.field}`)).size,
    [parsedVars],
  )

  return (
    <div className="space-y-1.5">
      {/* 顶栏：label + 选择变量按钮 */}
      <div className="flex items-center justify-between">
        {label && (
          <label className="text-xs text-slate-400">
            {label}
            {required && <span className="text-red-500 ml-0.5">*</span>}
          </label>
        )}
        <Popover
          content={popoverContent}
          trigger="click"
          open={popoverOpen}
          onOpenChange={setPopoverOpen}
          title={
            <div className="flex items-center justify-between text-xs">
              <span className="font-medium text-[#fafafa]">选择变量</span>
              <span className="text-[#71717a]">
                {totalAvailableVars > 0
                  ? `${upstreamGroups.length} 个节点 · ${totalAvailableVars} 个字段`
                  : '无可用变量'}
              </span>
            </div>
          }
        >
          <Button
            className="!text-[11px] !flex !items-center !gap-1"
            icon={<Code size={12} />}
          >
            选择变量
            {totalAvailableVars > 0 && (
              <Badge
                count={totalAvailableVars}
                size="small"
                className="!ml-0.5"
              />
            )}
          </Button>
        </Popover>
      </div>

      {/* 文本输入框 */}
      <div className="relative">
        {textarea ? (
          <Input.TextArea
            ref={inputRef}
            value={value}
            onChange={(e) => onChange(e.target.value)}
            rows={rows}
            className="font-mono text-xs"
            placeholder={placeholder}
          />
        ) : (
          <Input
            value={value}
            onChange={(e) => onChange(e.target.value)}
            className="font-mono text-xs"
            placeholder={placeholder}
          />
        )}
      </div>

      {/* 已插入变量 Tag 列表 */}
      {parsedVars.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-[10px] text-[#71717a] shrink-0">
            已用变量 ({uniqueUsedCount})：
          </span>
          {Array.from(
            new Map<string, ParsedVariable>(
              parsedVars.map((p) => [`${p.nodeId}.${p.field}`, p]),
            ).entries(),
          ).map(([key, pv]) => (
            <Fragment key={key}>
              <Tag
                className="!m-0 !text-[10px] !px-1.5 !py-0 !rounded !flex !items-center !gap-0.5"
                color="processing"
                closable
                onClose={() => handleRemoveVariable(pv)}
              >
                <span className="font-mono">{pv.nodeId}.{pv.field}</span>
              </Tag>
            </Fragment>
          ))}
        </div>
      )}
    </div>
  )
}
