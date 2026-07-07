/**
 * DefaultInputEditor — 表格形式编辑 key-value 对。
 *
 * 用于配置触发器的默认输入参数。支持添加/删除/修改行。
 * 值输入框支持 `{{node_id.field}}` 模板语法提示。
 *
 * 作为受控组件使用，value/onChange 与 Record<string, any> 对接。
 */
import { useState, useEffect, useMemo } from 'react'
import { Button, Input, Tooltip, Typography, Popconfirm } from 'antd'
import {
  PlusOutlined,
  DeleteOutlined,
  QuestionCircleOutlined,
} from '@ant-design/icons'

const { Text } = Typography

interface Row {
  key: string
  value: string
}

interface Props {
  value?: Record<string, any>
  onChange?: (value: Record<string, any>) => void
  disabled?: boolean
}

/**
 * 将 Record 转换为 Row[] 以保持编辑顺序。
 */
function recordToRows(rec: Record<string, any> | undefined): Row[] {
  if (!rec || Object.keys(rec).length === 0) return []
  return Object.entries(rec).map(([key, v]) => ({
    key,
    value: typeof v === 'string' ? v : JSON.stringify(v),
  }))
}

/**
 * 将 Row[] 转换回 Record<string, any>。
 * 尝试将值 JSON.parse 为对象/数字/布尔；失败时保留为字符串。
 */
function rowsToRecord(rows: Row[]): Record<string, any> {
  const result: Record<string, any> = {}
  for (const row of rows) {
    const k = row.key.trim()
    if (!k) continue
    const raw = row.value
    // 尝试解析为 JSON（支持 number / boolean / object）
    try {
      if (
        raw === 'true' || raw === 'false' ||
        raw === 'null' ||
        /^-?\d+(\.\d+)?$/.test(raw) ||
        (raw.startsWith('{') && raw.endsWith('}')) ||
        (raw.startsWith('[') && raw.endsWith(']'))
      ) {
        result[k] = JSON.parse(raw)
      } else {
        result[k] = raw
      }
    } catch {
      result[k] = raw
    }
  }
  return result
}

const TEMPLATE_HINT = '支持模板变量：{{node_id.field}}，运行时将自动替换为对应节点输出。'

export default function DefaultInputEditor({
  value,
  onChange,
  disabled = false,
}: Props) {
  const [rows, setRows] = useState<Row[]>(() => recordToRows(value))

  // 外部 value 变化时同步（仅在首次或外部重置时）
  useEffect(() => {
    setRows(recordToRows(value))
    // 仅初始化；后续由本地编辑驱动
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const emitChange = (nextRows: Row[]) => {
    setRows(nextRows)
    onChange?.(rowsToRecord(nextRows))
  }

  const updateRow = (index: number, patch: Partial<Row>) => {
    const next = rows.map((r, i) => (i === index ? { ...r, ...patch } : r))
    emitChange(next)
  }

  const addRow = () => {
    emitChange([...rows, { key: '', value: '' }])
  }

  const removeRow = (index: number) => {
    emitChange(rows.filter((_, i) => i !== index))
  }

  const invalidKeys = useMemo(() => {
    const seen = new Set<string>()
    const dup = new Set<string>()
    for (const r of rows) {
      const k = r.key.trim()
      if (!k) continue
      if (seen.has(k)) dup.add(k)
      seen.add(k)
    }
    return dup
  }, [rows])

  return (
    <div className="flex flex-col gap-2">
      {/* 表头 */}
      <div className="flex items-center gap-2 px-1">
        <Text className="text-xs font-medium text-[#64748B] w-[140px] shrink-0">
          参数名
        </Text>
        <div className="flex-1 flex items-center gap-1">
          <Text className="text-xs font-medium text-[#64748B]">值</Text>
          <Tooltip title={TEMPLATE_HINT}>
            <QuestionCircleOutlined className="text-[10px] text-[#94A3B8] cursor-help" />
          </Tooltip>
        </div>
        <span className="w-8 shrink-0" />
      </div>

      {/* 行 */}
      {rows.length === 0 ? (
        <div className="border border-dashed border-[#E2E8F0] rounded-lg px-3 py-4 text-center text-[11px] text-[#94A3B8]">
          暂无默认参数，点击下方按钮添加
        </div>
      ) : (
        rows.map((row, idx) => {
          const trimmed = row.key.trim()
          const isDup = trimmed && invalidKeys.has(trimmed)
          return (
            <div key={idx} className="flex items-center gap-2">
              <Input
                value={row.key}
                onChange={(e) => updateRow(idx, { key: e.target.value })}
                placeholder="参数名"
                disabled={disabled}
                status={isDup ? 'error' : undefined}
                className="!w-[140px] !shrink-0 !font-mono !text-xs"
              />
              <Input
                value={row.value}
                onChange={(e) => updateRow(idx, { value: e.target.value })}
                placeholder='字符串、数字或 {{node.field}}'
                disabled={disabled}
                className="!flex-1 !font-mono !text-xs"
              />
              <Popconfirm
                title="删除该参数？"
                onConfirm={() => removeRow(idx)}
                okText="删除"
                cancelText="取消"
                disabled={disabled}
              >
                <Button
                  type="text"
                  danger
                  size="small"
                  icon={<DeleteOutlined />}
                  disabled={disabled}
                  className="!w-8 !shrink-0"
                />
              </Popconfirm>
            </div>
          )
        })
      )}

      <Button
        type="dashed"
        icon={<PlusOutlined />}
        onClick={addRow}
        disabled={disabled}
        block
        size="small"
      >
        添加参数
      </Button>
    </div>
  )
}
