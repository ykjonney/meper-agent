/**
 * VariableSelector — 变量选择器组件（增强版）。
 *
 * 功能：
 * 1. contentEditable 编辑器 + 「选择变量」按钮 + 「放大编辑」按钮
 * 2. 选中的变量在编辑器内显示为带类型样式的 chip（label · 短节点号），
 *    Backspace 整体删除；对外 value 仍是 `{{node_id.field}}` 字符串
 * 3. 点击「选择变量」弹出面板，按上游节点分组展示可用字段
 * 4. 点击「放大」打开大号编辑弹窗，弹窗内仍可选变量
 * 5. 每个字段 Tag 显示类型图标 + 颜色（v2）
 * 6. 优先读取 config.output_variables（用户自定义），无则 fallback 到静态表（v2）
 *
 * antd 组件 → 原生 Tailwind ui 封装；@ant-design/icons → lucide-react。
 */
import { useState, useMemo, useRef, useCallback, Fragment } from 'react'
import { Button, Popover, Tag, Badge, Tooltip, Modal } from '../../components/ui'
import { Code, Maximize2 } from 'lucide-react'
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
import VariableChipEditor, {
  type VariableChipEditorHandle,
  type VariableChipMeta,
} from './VariableChipEditor'

/* ─── Types ─── */

export interface VariableSelectorProps {
  /** 当前文本值（`文本{{node_id.field}}`） */
  value: string
  /** 值变更回调 */
  onChange: (value: string) => void
  /** 当前编辑的节点 ID */
  currentNodeId: string
  /** 所有工作流节点 */
  allNodes: WorkflowNode[]
  /** 占位符文本 */
  placeholder?: string
  /** 多行编辑器行数（仅影响最小高度） */
  rows?: number
  /** 是否多行（false=单行 chip 编辑器） */
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

/** 把 node_id（如 node_xxx_a3b2）缩成短码，便于在 chip / 弹窗里区分同类节点 */
function shortNodeId(nodeId: string): string {
  const parts = nodeId.split('_')
  const tail = parts.length > 1 ? parts[parts.length - 1] : nodeId
  return tail.slice(-4)
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
  const [enlargeOpen, setEnlargeOpen] = useState(false)
  const [enlargeValue, setEnlargeValue] = useState('')

  const editorRef = useRef<VariableChipEditorHandle>(null)
  const modalEditorRef = useRef<VariableChipEditorHandle>(null)

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

  /* ─── chip 显示元信息：key=`${nodeId}.${field}` ─── */
  const varMeta = useMemo<Map<string, VariableChipMeta>>(() => {
    const m = new Map<string, VariableChipMeta>()
    for (const g of upstreamGroups) {
      const short = shortNodeId(g.nodeId)
      for (const f of g.fields) {
        const ti = getTypeDisplayInfo(f.type)
        m.set(`${g.nodeId}.${f.name}`, {
          label: f.label,
          color: ti.color,
          icon: ti.icon,
          short,
        })
      }
    }
    return m
  }, [upstreamGroups])

  /* ─── 可用变量总数 ─── */
  const totalAvailableVars = useMemo(
    () => upstreamGroups.reduce((sum, g) => sum + g.fields.length, 0),
    [upstreamGroups],
  )

  /* ─── 插入变量（行内编辑器） ─── */
  const handleInsertVariable = useCallback((nodeId: string, field: string) => {
    editorRef.current?.insertAtCursor(nodeId, field)
    setPopoverOpen(false)
  }, [])

  /* ─── 插入变量（放大弹窗编辑器） ─── */
  const handleInsertInModal = useCallback((nodeId: string, field: string) => {
    modalEditorRef.current?.insertAtCursor(nodeId, field)
  }, [])

  /* ─── 放大弹窗开关 ─── */
  const openEnlarge = useCallback(() => {
    setEnlargeValue(value)
    setEnlargeOpen(true)
  }, [value])

  const confirmEnlarge = useCallback(() => {
    onChange(enlargeValue)
    setEnlargeOpen(false)
  }, [enlargeValue, onChange])

  /* ─── 渲染字段 Tag ─── */
  const renderFieldTag = (
    field: UpstreamField,
    group: UpstreamGroup,
    onInsert: (nodeId: string, field: string) => void,
  ) => {
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
          onClick={() => onInsert(group.nodeId, field.name)}
        >
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

  /* ─── 变量选择面板（行内 Popover 与放大弹窗共用） ─── */
  const renderUpstreamGroups = (
    onInsert: (nodeId: string, field: string) => void,
    containerCls = 'w-72 max-h-72',
  ) => (
    <div className={`overflow-y-auto scrollbar-custom ${containerCls}`}>
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
                <span
                  className="text-[10px] text-[#71717a] font-mono ml-auto shrink-0 cursor-help"
                  title={`节点 ID：${group.nodeId}`}
                >
                  #{shortNodeId(group.nodeId)}
                </span>
              </div>
              {/* 字段 Tag 列表 */}
              <div className="flex flex-wrap gap-1.5">
                {group.fields.map((field) => (
                  <Fragment key={field.name}>
                    {renderFieldTag(field, group, onInsert)}
                  </Fragment>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )

  const popoverTitle = (
    <div className="flex items-center justify-between text-xs">
      <span className="font-medium text-[#fafafa]">选择变量</span>
      <span className="text-[#71717a]">
        {totalAvailableVars > 0
          ? `${upstreamGroups.length} 个节点 · ${totalAvailableVars} 个字段`
          : '无可用变量'}
      </span>
    </div>
  )

  return (
    <div className="space-y-1.5">
      {/* 顶栏：label + 选择变量 + 放大 */}
      <div className="flex items-center justify-between gap-2">
        {label && (
          <label className="text-xs text-slate-400 shrink-0">
            {label}
            {required && <span className="text-red-500 ml-0.5">*</span>}
          </label>
        )}
        <div className="flex items-center gap-1.5 ml-auto">
          <Popover
            content={renderUpstreamGroups(handleInsertVariable)}
            trigger="click"
            open={popoverOpen}
            onOpenChange={setPopoverOpen}
            title={popoverTitle}
          >
            <Button
              className="!text-[11px] !flex !items-center !gap-1"
              icon={<Code size={12} />}
            >
              选择变量
              {totalAvailableVars > 0 && (
                <Badge count={totalAvailableVars} size="small" className="!ml-0.5" />
              )}
            </Button>
          </Popover>
          <Button
            className="!flex !items-center !gap-1 !text-[11px] !px-2"
            icon={<Maximize2 size={12} />}
            onClick={openEnlarge}
            title="放大编辑"
          >
            放大
          </Button>
        </div>
      </div>

      {/* chip 编辑器（行内） */}
      <VariableChipEditor
        ref={editorRef}
        value={value}
        onChange={onChange}
        varMeta={varMeta}
        multiline={textarea}
        minRows={rows}
        placeholder={placeholder}
      />

      {/* 放大编辑弹窗 */}
      <Modal
        open={enlargeOpen}
        title={label ? `${label}（放大编辑）` : '放大编辑'}
        width={720}
        okText="确定"
        cancelText="取消"
        onOk={confirmEnlarge}
        onCancel={() => setEnlargeOpen(false)}
      >
        <div className="space-y-3">
          <VariableChipEditor
            ref={modalEditorRef}
            value={enlargeValue}
            onChange={setEnlargeValue}
            varMeta={varMeta}
            multiline
            minRows={10}
            placeholder={placeholder}
          />
          <div>
            <div className="text-xs text-slate-400 mb-1.5">可用变量（点击插入到光标处）</div>
            {renderUpstreamGroups(handleInsertInModal, 'max-h-48')}
          </div>
        </div>
      </Modal>
    </div>
  )
}
