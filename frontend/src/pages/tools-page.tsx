/**
 * Tools page — built-in tools + custom tool market (OpenAPI / Code / Prebuilt).
 *
 * Built-in tools are always available to every Agent.
 * Custom tools are created by users and configured per-Agent via tool-selector.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Spin, Empty, Tag, Button, Modal, Form, Input, Select, message, Tabs } from 'antd'
import type { TabsProps } from 'antd'
import {
  SearchOutlined, CodeOutlined, ReadOutlined, EditOutlined, ToolOutlined,
  PlusOutlined, ApiOutlined, DeleteOutlined, GlobalOutlined,
} from '@ant-design/icons'
import { useTheme } from '../contexts/ThemeContext'
import { toolsApi } from '../services/tools-api'
import { credentialsApi } from '../services/credentials-api'
import { normalizeError } from '../services/api-client'
import type { BuiltinTool, Tool } from '../services/tools-api'

const TOOL_ICONS: Record<string, typeof CodeOutlined> = {
  bash: CodeOutlined, read: ReadOutlined, write: EditOutlined,
}

const SOURCE_TAGS: Record<string, { color: string; label: string; icon: typeof ApiOutlined }> = {
  openapi: { color: 'blue', label: 'OpenAPI', icon: GlobalOutlined },
  code: { color: 'green', label: 'Code', icon: CodeOutlined },
  prebuilt: { color: 'purple', label: 'Prebuilt', icon: ToolOutlined },
}

export default function ToolsPage() {
  const [activeTab, setActiveTab] = useState('builtin')

  const tabItems: TabsProps['items'] = [
    { key: 'builtin', label: '内建工具', children: <BuiltinToolsTab /> },
    { key: 'custom', label: '自定义工具', children: <CustomToolsTab /> },
  ]

  return (
    <div className="animate-[fadeIn_0.3s_ease-out]">
      <Tabs
        activeKey={activeTab}
        onChange={setActiveTab}
        items={tabItems}
        className="!px-6 !pt-4"
      />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Tab 1: Built-in tools (read-only)
// ---------------------------------------------------------------------------

function BuiltinToolsTab() {
  const { t } = useTheme()
  const [searchName, setSearchName] = useState('')

  const { data: tools, isLoading } = useQuery({
    queryKey: ['builtin-tools'],
    queryFn: () => toolsApi.listBuiltins(),
  })

  const filtered = (tools ?? []).filter((tool) => {
    if (!searchName) return true
    const q = searchName.toLowerCase()
    return tool.name.toLowerCase().includes(q) || tool.description.toLowerCase().includes(q)
  })

  return (
    <div>
      <div className="flex items-center gap-4 mb-6">
        <div className="relative">
          <SearchOutlined className="absolute left-3 top-1/2 -translate-y-1/2 text-[#94A3B8] text-sm" />
          <input
            type="text"
            placeholder="搜索内建工具..."
            value={searchName}
            onChange={(e) => setSearchName(e.target.value)}
            className="pl-9 pr-4 py-2 rounded-lg border border-gray-200 text-sm focus:outline-none focus:ring-2 w-64"
            style={{ '--tw-ring-color': t.bg } as React.CSSProperties}
          />
        </div>
        <Tag className="!m-0 !px-2 !py-0.5 !text-xs !rounded"
          style={{ color: '#7C3AED', background: '#EDE9FE', borderColor: 'transparent' }}>
          内建工具
        </Tag>
      </div>

      {isLoading ? (
        <div className="flex justify-center py-20"><Spin size="large" /></div>
      ) : filtered.length === 0 ? (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无内建工具" className="py-20" />
      ) : (
        <div className="grid grid-cols-3 gap-4">
          {filtered.map((tool) => <BuiltinToolCard key={tool.name} tool={tool} />)}
        </div>
      )}
    </div>
  )
}

function BuiltinToolCard({ tool }: { tool: BuiltinTool }) {
  const { t } = useTheme()
  const Icon = TOOL_ICONS[tool.name] ?? ToolOutlined
  const paramNames = Object.keys((tool.parameters?.properties as Record<string, unknown>) ?? {})

  return (
    <div className="rounded-xl border border-gray-200 bg-white p-5 hover:shadow-sm transition-all duration-200">
      <div className="flex items-start gap-3 mb-3">
        <div className="w-10 h-10 rounded-lg flex items-center justify-center text-base shrink-0"
          style={{ background: t.bg, color: t.primary }}>
          <Icon />
        </div>
        <div className="min-w-0">
          <div className="text-sm font-medium text-[#0F172A]">{tool.name}</div>
          <div className="text-xs text-[#64748B] line-clamp-2">{tool.description}</div>
        </div>
      </div>
      <div className="pt-3 border-t border-gray-50">
        {paramNames.length > 0 ? (
          <div className="flex flex-wrap gap-1.5">
            {paramNames.map((p) => (
              <Tag key={p} className="!m-0 !px-2 !py-0.5 !text-[11px] !rounded"
                style={{ color: '#64748B', background: '#F1F5F9', borderColor: 'transparent' }}>
                {p}
              </Tag>
            ))}
          </div>
        ) : <span className="text-xs text-[#94A3B8]">无参数</span>}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Tab 2: Custom tools (CRUD — create OpenAPI/Code/Prebuilt tools)
// ---------------------------------------------------------------------------

function CustomToolsTab() {
  const queryClient = useQueryClient()
  const [createOpen, setCreateOpen] = useState(false)
  const [form] = Form.useForm()
  const [searchName, setSearchName] = useState('')

  // Load custom tools (openapi + code + prebuilt)
  const { data: allCustom, isLoading } = useQuery({
    queryKey: ['custom-tools-list'],
    queryFn: async () => {
      const [r1, r2, r3] = await Promise.all([
        toolsApi.list({ page: 1, page_size: 100, source: 'openapi' }),
        toolsApi.list({ page: 1, page_size: 100, source: 'code' }),
        toolsApi.list({ page: 1, page_size: 100, source: 'prebuilt' }),
      ])
      return [...r1.items, ...r2.items, ...r3.items]
    },
  })

  // Load credentials for the credential selector
  const { data: credData } = useQuery({
    queryKey: ['credentials-for-tools'],
    queryFn: () => credentialsApi.list(),
  })

  const createMutation = useMutation({
    mutationFn: toolsApi.createCustom,
    onSuccess: () => {
      message.success('工具创建成功')
      queryClient.invalidateQueries({ queryKey: ['custom-tools-list'] })
      queryClient.invalidateQueries({ queryKey: ['custom-tools'] })
      setCreateOpen(false)
      form.resetFields()
    },
    onError: (err) => message.error(normalizeError(err as never).message),
  })

  const deleteMutation = useMutation({
    mutationFn: toolsApi.remove,
    onSuccess: () => {
      message.success('工具已删除')
      queryClient.invalidateQueries({ queryKey: ['custom-tools-list'] })
      queryClient.invalidateQueries({ queryKey: ['custom-tools'] })
    },
    onError: (err) => message.error(normalizeError(err as never).message),
  })

  const handleDelete = (tool: Tool) => {
    Modal.confirm({
      title: '删除工具',
      content: `确定删除「${tool.name}」吗？引用此工具的 Agent 将失去该工具。`,
      okText: '删除', okType: 'danger', cancelText: '取消',
      onOk: () => deleteMutation.mutate(tool.id),
    })
  }

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields()
      // Parse JSON fields
      const inputSchema = values.input_schema ? JSON.parse(values.input_schema) : {}
      const config = values.config ? JSON.parse(values.config) : {}
      const endpoint = values.endpoint ? JSON.parse(values.endpoint) : {}
      createMutation.mutate({
        name: values.name,
        description: values.description || '',
        source: values.source,
        input_schema: inputSchema,
        credential_id: values.credential_id || '',
        config, endpoint,
        code: values.code || '',
        prebuilt_name: values.prebuilt_name || '',
      })
    } catch (err) {
      if (err instanceof SyntaxError) {
        message.error('JSON 格式错误：' + err.message)
      }
    }
  }

  const tools = (allCustom || []).filter(t => {
    if (!searchName) return true
    const q = searchName.toLowerCase()
    return t.name.toLowerCase().includes(q) || t.description.toLowerCase().includes(q)
  })

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <div className="relative">
            <SearchOutlined className="absolute left-3 top-1/2 -translate-y-1/2 text-[#94A3B8] text-sm" />
            <input
              type="text" placeholder="搜索自定义工具..." value={searchName}
              onChange={(e) => setSearchName(e.target.value)}
              className="pl-9 pr-4 py-2 rounded-lg border border-gray-200 text-sm focus:outline-none focus:ring-2 w-64"
            />
          </div>
        </div>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
          创建工具
        </Button>
      </div>

      {isLoading ? (
        <div className="flex justify-center py-20"><Spin size="large" /></div>
      ) : tools.length === 0 ? (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={<span>暂无自定义工具<br />点击「创建工具」添加 OpenAPI / Code / 预构建工具</span>}
          className="py-20"
        />
      ) : (
        <div className="grid grid-cols-3 gap-4">
          {tools.map((tool) => <CustomToolCard key={tool.id} tool={tool} onDelete={() => handleDelete(tool)} />)}
        </div>
      )}

      {/* Create Tool Modal */}
      <Modal
        title="创建自定义工具"
        open={createOpen}
        onCancel={() => { setCreateOpen(false); form.resetFields() }}
        onOk={handleSubmit}
        confirmLoading={createMutation.isPending}
        okText="创建" cancelText="取消"
        width={640}
      >
        <Form form={form} layout="vertical" initialValues={{ source: 'openapi' }}>
          <Form.Item label="名称" name="name" rules={[{ required: true, message: '请输入工具名称' }]}>
            <Input placeholder="如：github_list_issues" />
          </Form.Item>
          <Form.Item label="描述" name="description">
            <Input placeholder="如：列出 GitHub Issues" />
          </Form.Item>
          <Form.Item label="类型" name="source" rules={[{ required: true }]}>
            <Select options={[
              { value: 'openapi', label: 'OpenAPI（HTTP 请求工具）' },
              { value: 'code', label: 'Code（Python 代码工具）' },
              { value: 'prebuilt', label: 'Prebuilt（预构建工具）' },
            ]} />
          </Form.Item>

          {/* Credential selector */}
          <Form.Item label="认证凭据" name="credential_id">
            <Select
              allowClear placeholder="选择凭据（可选）"
              options={(credData?.items || []).map(c => ({
                value: c._id, label: `${c.name} (${c.type})`,
              }))}
            />
          </Form.Item>

          {/* LLM-visible params schema */}
          <Form.Item
            label="LLM 参数（JSON Schema）" name="input_schema"
            extra='如 {"type":"object","properties":{"query":{"type":"string"}},"required":["query"]}'
          >
            <Input.TextArea rows={3} placeholder='{"type":"object","properties":{}}' className="font-mono text-sm" />
          </Form.Item>

          {/* Source-specific fields */}
          <Form.Item noStyle shouldUpdate={(prev, cur) => prev.source !== cur.source}>
            {({ getFieldValue }) => {
              const source = getFieldValue('source')
              if (source === 'openapi') {
                return (
                  <Form.Item
                    label="Endpoint 配置（JSON）" name="endpoint"
                    extra='method/url/headers/params，支持 {{credential.xxx}} {{config.xxx}} 模板'
                  >
                    <Input.TextArea rows={5}
                      placeholder={'{"method":"GET","url":"https://api.example.com/{{config.path}}","headers":{"Authorization":"Bearer {{credential.token}}"}}'}
                      className="font-mono text-sm"
                    />
                  </Form.Item>
                )
              }
              if (source === 'code') {
                return (
                  <Form.Item label="Python 代码" name="code"
                    extra="定义一个函数，函数名和工具名一致，返回 str">
                    <Input.TextArea rows={8}
                      placeholder={'def my_tool(query: str) -> str:\n    return f"result: {query"}'}
                      className="font-mono text-sm"
                    />
                  </Form.Item>
                )
              }
              if (source === 'prebuilt') {
                return (
                  <Form.Item label="预构建工具名称" name="prebuilt_name" rules={[{ required: true, message: '请输入预构建工具名' }]}>
                    <Input placeholder="如：wikipedia_search" />
                  </Form.Item>
                )
              }
              return null
            }}
          </Form.Item>

          {/* Optional config */}
          <Form.Item label="参数（JSON，非敏感预设）" name="config"
            extra='如 {"owner":"myorg","timeout":30}，通过 {{config.xxx}} 在 endpoint 中引用'>
            <Input.TextArea rows={2} placeholder='{}' className="font-mono text-sm" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Sub-component: custom tool card
// ---------------------------------------------------------------------------

function CustomToolCard({ tool, onDelete }: { tool: Tool; onDelete: () => void }) {
  const tag = SOURCE_TAGS[tool.source] || { color: 'default', label: tool.source, icon: ToolOutlined }
  const Icon = tag.icon
  const paramNames = Object.keys(
    (tool.input_schema?.properties as Record<string, unknown>) ?? {}
  )

  return (
    <div className="rounded-xl border border-gray-200 bg-white p-5 hover:shadow-sm transition-all duration-200">
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-start gap-3 min-w-0">
          <div className="w-10 h-10 rounded-lg flex items-center justify-center text-base shrink-0"
            style={{ background: '#F1F5F9', color: '#6366F1' }}>
            <Icon />
          </div>
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium text-[#0F172A]">{tool.name}</span>
              <Tag color={tag.color} className="!m-0 !text-[10px]">{tag.label}</Tag>
            </div>
            <div className="text-xs text-[#64748B] line-clamp-2 mt-0.5">{tool.description}</div>
          </div>
        </div>
        <Button danger icon={<DeleteOutlined />} size="small" onClick={onDelete} />
      </div>

      {paramNames.length > 0 && (
        <div className="pt-3 border-t border-gray-50">
          <div className="flex flex-wrap gap-1.5">
            {paramNames.map((p) => (
              <Tag key={p} className="!m-0 !px-2 !py-0.5 !text-[11px] !rounded"
                style={{ color: '#64748B', background: '#F1F5F9', borderColor: 'transparent' }}>
                {p}
              </Tag>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
