/**
 * VariableListEditor — 变量列表编辑器组件。
 *
 * 功能：
 * 1. 以表格形式展示已有变量（name / label / type / actions）
 * 2. 添加变量按钮 → 弹出 Modal 使用 VariableTypeSelector 配置
 * 3. 编辑变量 → 弹出 Modal 预填
 * 4. 删除变量 → 确认后移除
 * 5. 支持外部传入初始值（编辑已有 workflow 时回填）
 */
import { useState } from 'react'
import { Button, Table, Modal, Tag, Tooltip } from 'antd'
import { PlusOutlined, EditOutlined, DeleteOutlined } from '@ant-design/icons'
import type { VariableDefinition, VariableTypeName } from './utils/variable-types'
import { getTypeColor, getTypeIcon, getTypeLabel } from './utils/variable-types'
import VariableTypeSelector from './VariableTypeSelector'

/* ─── Props ─── */

export interface VariableListEditorProps {
  /** 当前变量列表 */
  value?: VariableDefinition[]
  /** 值变更回调 */
  onChange: (variables: VariableDefinition[]) => void
  /** 节点类型名（用于默认变量） */
  nodeType?: string
  /** 是否只读（如 Tool 节点） */
  readonly?: boolean
}

/* ─── 默认变量名生成 ─── */

let _counter = 0
function generateVarName(nodeType?: string): string {
  _counter++
  const prefix = nodeType ?? 'var'
  return `${prefix}_${_counter}`
}

/* ─── Component ─── */

export default function VariableListEditor({
  value = [],
  onChange,
  nodeType,
  readonly = false,
}: VariableListEditorProps) {
  const [modalOpen, setModalOpen] = useState(false)
  const [editingIndex, setEditingIndex] = useState<number | null>(null)
  const [draft, setDraft] = useState<Partial<VariableDefinition>>({})

  /* ─── 打开添加 Modal ─── */
  const handleAdd = () => {
    setEditingIndex(null)
    setDraft({
      name: generateVarName(nodeType),
      label: '',
      type: 'text' as VariableTypeName,
      constraints: {},
    })
    setModalOpen(true)
  }

  /* ─── 打开编辑 Modal ─── */
  const handleEdit = (index: number) => {
    setEditingIndex(index)
    setDraft({ ...value[index] })
    setModalOpen(true)
  }

  /* ─── 删除变量 ─── */
  const handleDelete = (index: number) => {
    const newList = value.filter((_, i) => i !== index)
    onChange(newList)
  }

  /* ─── 保存（添加/编辑） ─── */
  const handleSave = () => {
    if (!draft.name) return
    const variable: VariableDefinition = {
      name: draft.name,
      label: draft.label || draft.name,
      type: (draft.type as VariableTypeName) ?? 'text',
      constraints: draft.constraints ?? {},
      description: draft.description,
      readonly: value[editingIndex ?? -1]?.readonly,
    }

    const newList = [...value]
    if (editingIndex !== null) {
      newList[editingIndex] = variable
    } else {
      newList.push(variable)
    }
    onChange(newList)
    setModalOpen(false)
    setDraft({})
  }

  /* ─── 表格列 ─── */
  const columns = [
    {
      title: '变量名',
      dataIndex: 'name',
      key: 'name',
      render: (name: string) => (
        <code className="text-xs font-mono text-[#0F172A]">{name}</code>
      ),
    },
    {
      title: '标签',
      dataIndex: 'label',
      key: 'label',
      render: (label: string) => (
        <span className="text-xs text-[#334155]">{label}</span>
      ),
    },
    {
      title: '类型',
      dataIndex: 'type',
      key: 'type',
      render: (type: string) => (
        <Tag
          className="!m-0 !text-[10px] !px-1.5 !py-0 !border-0"
          color={getTypeColor(type)}
        >
          {getTypeIcon(type)} {getTypeLabel(type)}
        </Tag>
      ),
    },
    {
      title: '操作',
      key: 'actions',
      width: 80,
      render: (_: unknown, record: VariableDefinition) => {
        if (record.readonly) {
          return (
            <Tooltip title="系统默认变量，不可编辑">
              <span className="text-[10px] text-[#94A3B8]">系统</span>
            </Tooltip>
          )
        }
        return (
          <div className="flex items-center gap-1">
            <Tooltip title="编辑">
              <Button
                type="text"
                size="small"
                icon={<EditOutlined />}
                onClick={() => handleEdit(value.findIndex((v) => v === record))}
                className="!text-[#64748B] !text-xs"
              />
            </Tooltip>
            <Tooltip title="删除">
              <Button
                type="text"
                size="small"
                danger
                icon={<DeleteOutlined />}
                onClick={() => handleDelete(value.findIndex((v) => v === record))}
                className="!text-xs"
              />
            </Tooltip>
          </div>
        )
      },
    },
  ]

  return (
    <div className="space-y-2">
      {/* 头部 */}
      <div className="flex items-center justify-between">
        <label className="text-xs text-[#64748B] font-medium">输出变量</label>
        {!readonly && (
          <Button
            size="small"
            type="dashed"
            icon={<PlusOutlined />}
            onClick={handleAdd}
            className="!text-[11px]"
          >
            添加变量
          </Button>
        )}
      </div>

      {/* 表格 */}
      {value.length > 0 ? (
        <Table
          dataSource={value}
          columns={columns}
          rowKey="name"
          pagination={false}
          size="small"
          className="!text-xs"
          rowClassName={() => '!text-xs'}
        />
      ) : (
        <div className="text-[10px] text-[#94A3B8] text-center py-3 border border-dashed border-gray-200 rounded">
          {readonly ? '无可配置的输出变量' : '暂无变量，点击上方按钮添加'}
        </div>
      )}

      {/* 添加/编辑 Modal */}
      <Modal
        title={editingIndex !== null ? '编辑变量' : '添加变量'}
        open={modalOpen}
        onOk={handleSave}
        onCancel={() => {
          setModalOpen(false)
          setDraft({})
        }}
        okText="保存"
        cancelText="取消"
        width={420}
        okButtonProps={{
          disabled: !draft.name,
        }}
        destroyOnClose
      >
        <VariableTypeSelector
          value={draft}
          onChange={setDraft}
          showMeta
          existingNames={value
            .filter((_, i) => i !== editingIndex)
            .map((v) => v.name)}
        />
      </Modal>
    </div>
  )
}
