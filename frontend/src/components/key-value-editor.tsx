/**
 * KeyValueEditor — dynamic key-value pair list.
 * Used for HTTP headers, query params, and preset config.
 */
import { Button, Input } from 'antd'
import { DeleteOutlined, PlusOutlined } from '@ant-design/icons'

export interface KVPair {
  key: string
  value: string
}

export interface KeyValueEditorProps {
  value: KVPair[]
  onChange: (pairs: KVPair[]) => void
  keyPlaceholder?: string
  valuePlaceholder?: string
  emptyHint?: string
}

export default function KeyValueEditor({
  value,
  onChange,
  keyPlaceholder = 'Key',
  valuePlaceholder = 'Value',
  emptyHint = '暂无条目',
}: KeyValueEditorProps) {
  const addPair = () => {
    onChange([...value, { key: '', value: '' }])
  }

  const removePair = (index: number) => {
    onChange(value.filter((_, i) => i !== index))
  }

  const updatePair = (index: number, field: 'key' | 'value', val: string) => {
    onChange(value.map((p, i) => (i === index ? { ...p, [field]: val } : p)))
  }

  return (
    <div className="space-y-2">
      {value.length === 0 ? (
        <div className="text-xs text-[#94A3B8] py-2 text-center bg-[#F8FAFC] rounded-lg border border-dashed border-[#E2E8F0]">
          {emptyHint}
        </div>
      ) : (
        value.map((pair, index) => (
          <div key={index} className="flex items-center gap-2">
            <Input
              size="small"
              value={pair.key}
              onChange={(e) => updatePair(index, 'key', e.target.value)}
              placeholder={keyPlaceholder}
              className="flex-1"
            />
            <span className="text-[#94A3B8] text-xs shrink-0">:</span>
            <Input
              size="small"
              value={pair.value}
              onChange={(e) => updatePair(index, 'value', e.target.value)}
              placeholder={valuePlaceholder}
              className="flex-1"
            />
            <Button
              size="small"
              type="text"
              danger
              icon={<DeleteOutlined />}
              onClick={() => removePair(index)}
              className="shrink-0"
            />
          </div>
        ))
      )}
      <Button
        size="small"
        type="dashed"
        icon={<PlusOutlined />}
        onClick={addPair}
        className="w-full"
      >
        添加
      </Button>
    </div>
  )
}
