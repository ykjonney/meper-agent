/**
 * ParamEditor — tool parameter editor (add/remove/edit params).
 * Replaces raw JSON Schema input with a visual form.
 * Auto-generates JSON Schema from the visual definition.
 */
import { useState } from 'react'
import { Button, Input, Select, Checkbox, Tag, Empty } from 'antd'
import { DeleteOutlined, PlusOutlined } from '@ant-design/icons'

export type ParamType = 'string' | 'integer' | 'number' | 'boolean'

export interface ToolParam {
  name: string
  type: ParamType
  required: boolean
  description: string
  enumValues?: string
}

export interface ParamEditorProps {
  value: ToolParam[]
  onChange: (params: ToolParam[]) => void
}

const TYPE_LABELS: Record<ParamType, string> = {
  string: '字符串',
  integer: '整数',
  number: '数字',
  boolean: '布尔',
}

export default function ParamEditor({ value, onChange }: ParamEditorProps) {
  const [adding, setAdding] = useState(false)
  const [newParam, setNewParam] = useState<ToolParam>({
    name: '', type: 'string', required: false, description: '',
  })

  const addParam = () => {
    if (!newParam.name.trim()) return
    onChange([...value, { ...newParam, name: newParam.name.trim() }])
    setNewParam({ name: '', type: 'string', required: false, description: '' })
    setAdding(false)
  }

  const removeParam = (index: number) => {
    onChange(value.filter((_, i) => i !== index))
  }

  return (
    <div>
      {/* Existing params */}
      <div className="space-y-1.5 mb-3">
        {value.length === 0 ? (
          <div className="text-xs text-[#94A3B8] py-3 text-center bg-[#F8FAFC] rounded-lg border border-dashed border-[#E2E8F0]">
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无参数" className="!my-2" />
          </div>
        ) : (
          <div className="border border-[#E2E8F0] rounded-lg overflow-hidden divide-y divide-[#F1F5F9]">
            {value.map((param, index) => (
              <div key={index} className="flex items-center gap-2 px-3 py-2 hover:bg-[#F8FAFC]">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-[#0F172A] truncate">{param.name}</span>
                    <Tag className="!m-0 !text-[10px] !px-1.5 !py-0 !rounded"
                      style={{ background: '#EFF6FF', color: '#2563EB', borderColor: 'transparent' }}>
                      {TYPE_LABELS[param.type]}
                    </Tag>
                    {param.required && (
                      <Tag className="!m-0 !text-[10px] !px-1.5 !py-0 !rounded"
                        style={{ background: '#FEF2F2', color: '#DC2626', borderColor: 'transparent' }}>
                        必填
                      </Tag>
                    )}
                  </div>
                  {param.description && (
                    <div className="text-xs text-[#94A3B8] mt-0.5 truncate">{param.description}</div>
                  )}
                </div>
                <Button
                  size="small" type="text" danger
                  icon={<DeleteOutlined />}
                  onClick={() => removeParam(index)}
                />
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Add new param form */}
      {adding ? (
        <div className="border border-[#93C5FD] rounded-lg p-3 bg-[#F0F7FF] space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs text-[#64748B] mb-1">参数名 *</label>
              <Input
                size="small"
                value={newParam.name}
                onChange={(e) => setNewParam({ ...newParam, name: e.target.value })}
                placeholder="如: query"
              />
            </div>
            <div>
              <label className="block text-xs text-[#64748B] mb-1">类型</label>
              <Select
                size="small"
                value={newParam.type}
                onChange={(val) => setNewParam({ ...newParam, type: val })}
                className="w-full"
                options={[
                  { value: 'string', label: '字符串' },
                  { value: 'integer', label: '整数' },
                  { value: 'number', label: '数字' },
                  { value: 'boolean', label: '布尔' },
                ]}
              />
            </div>
          </div>
          <div>
            <label className="block text-xs text-[#64748B] mb-1">说明（给 LLM 看的参数描述）</label>
            <Input
              size="small"
              value={newParam.description}
              onChange={(e) => setNewParam({ ...newParam, description: e.target.value })}
              placeholder="如: 搜索关键词"
            />
          </div>
          <div className="flex items-center justify-between">
            <Checkbox
              checked={newParam.required}
              onChange={(e) => setNewParam({ ...newParam, required: e.target.checked })}
            >
              <span className="text-xs text-[#64748B]">必填参数</span>
            </Checkbox>
            <div className="flex gap-2">
              <Button size="small" onClick={() => { setAdding(false); setNewParam({ name: '', type: 'string', required: false, description: '' }) }}>
                取消
              </Button>
              <Button size="small" type="primary" onClick={addParam} disabled={!newParam.name.trim()}>
                添加
              </Button>
            </div>
          </div>
        </div>
      ) : (
        <Button size="small" type="dashed" icon={<PlusOutlined />} onClick={() => setAdding(true)} className="w-full">
          添加参数
        </Button>
      )}
    </div>
  )
}
