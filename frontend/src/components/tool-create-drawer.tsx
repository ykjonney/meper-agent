/**
 * ToolCreateDrawer — create custom tools (OpenAPI / Code).
 *
 * Features:
 * - Manual mode: visual param editor + HTTP config form
 * - Import mode: paste OpenAPI spec to auto-fill params + endpoint
 * - Credential selector (from /credentials)
 * - Key-value editors for headers/params/config
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Drawer, Button, Input, Select, Radio, Segmented, message, Divider } from 'antd'
import { GlobalOutlined, CodeOutlined } from '@ant-design/icons'
import { toolsApi } from '../services/tools-api'
import { credentialsApi } from '../services/credentials-api'
import { normalizeError } from '../services/api-client'
import ParamEditor, { paramsToSchema } from './param-editor'
import type { ToolParam } from './param-editor'
import KeyValueEditor from './key-value-editor'
import type { KVPair } from './key-value-editor'

const { TextArea } = Input

export interface ToolCreateDrawerProps {
  open: boolean
  onClose: () => void
}

type CreateMode = 'manual' | 'openapi_import'
type ToolSource = 'openapi' | 'code'

export default function ToolCreateDrawer({ open, onClose }: ToolCreateDrawerProps) {
  const queryClient = useQueryClient()

  // ── Form state ──
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [source, setSource] = useState<ToolSource>('openapi')
  const [createMode, setCreateMode] = useState<CreateMode>('manual')
  const [credentialId, setCredentialId] = useState('')
  const [params, setParams] = useState<ToolParam[]>([])

  // HTTP config
  const [method, setMethod] = useState('GET')
  const [url, setUrl] = useState('')
  const [headers, setHeaders] = useState<KVPair[]>([])
  const [queryParams, setQueryParams] = useState<KVPair[]>([])
  const [config, setConfig] = useState<KVPair[]>([])

  // Code
  const [code, setCode] = useState('')

  // OpenAPI import
  const [openapiSpec, setOpenapiSpec] = useState('')

  // ── Queries ──
  const { data: credData } = useQuery({
    queryKey: ['credentials-for-tools'],
    queryFn: () => credentialsApi.list(),
    enabled: open,
  })

  // ── Mutation ──
  const createMutation = useMutation({
    mutationFn: toolsApi.createCustom,
    onSuccess: () => {
      message.success('工具创建成功')
      queryClient.invalidateQueries({ queryKey: ['custom-tools-list'] })
      queryClient.invalidateQueries({ queryKey: ['custom-tools'] })
      resetForm()
      onClose()
    },
    onError: (err) => message.error(normalizeError(err as never).message),
  })

  const resetForm = () => {
    setName(''); setDescription(''); setSource('openapi'); setCreateMode('manual')
    setCredentialId(''); setParams([])
    setMethod('GET'); setUrl(''); setHeaders([]); setQueryParams([]); setConfig([])
    setCode(''); setOpenapiSpec('')
  }

  // ── Parse OpenAPI spec ──
  const parseOpenApi = () => {
    try {
      const spec = JSON.parse(openapiSpec)
      const paths = spec.paths || {}
      // Take first path + method as the tool endpoint
      const firstPath = Object.keys(paths)[0]
      if (!firstPath) { message.warning('未找到 paths'); return }
      const pathItem = paths[firstPath]
      const firstMethod = Object.keys(pathItem).find(m => ['get', 'post', 'put', 'delete'].includes(m))
      if (!firstMethod) { message.warning('未找到 method'); return }
      const operation = pathItem[firstMethod]

      // Fill name + description
      if (operation.operationId && !name) setName(operation.operationId)
      if (operation.summary && !description) setDescription(operation.summary)
      setMethod(firstMethod.toUpperCase())
      const serverUrl = spec.servers?.[0]?.url || ''
      setUrl(serverUrl + firstPath)

      // Parse parameters
      const opParams = operation.parameters || []
      const toolParams: ToolParam[] = opParams.map((p: Record<string, unknown>) => ({
        name: p.name as string || '',
        type: (p.schema?.type as string || 'string') as ToolParam['type'],
        required: p.required as boolean || false,
        description: (p.description as string) || '',
      }))
      setParams(toolParams)
      message.success(`解析成功：${toolParams.length} 个参数`)
    } catch (err) {
      message.error('JSON 解析失败：' + (err as Error).message)
    }
  }

  // ── Submit ──
  const handleSubmit = () => {
    if (!name.trim()) { message.warning('请输入工具名称'); return }

    const inputSchema = paramsToSchema(params)

    // Convert KV pairs to dicts
    const kvToDict = (kvs: KVPair[]) => {
      const d: Record<string, string> = {}
      for (const kv of kvs) {
        if (kv.key.trim()) d[kv.key] = kv.value
      }
      return d
    }

    if (source === 'openapi') {
      if (!url.trim()) { message.warning('请输入 URL'); return }
      createMutation.mutate({
        name: name.trim(),
        description,
        source: 'openapi',
        input_schema: inputSchema,
        credential_id: credentialId,
        config: kvToDict(config),
        endpoint: {
          method,
          url,
          headers: kvToDict(headers),
          params: kvToDict(queryParams),
        },
      })
    } else {
      if (!code.trim()) { message.warning('请输入代码'); return }
      createMutation.mutate({
        name: name.trim(),
        description,
        source: 'code',
        input_schema: inputSchema,
        credential_id: credentialId,
        config: kvToDict(config),
        code,
      })
    }
  }

  return (
    <Drawer
      title="创建自定义工具"
      open={open}
      onClose={onClose}
      width={720}
      destroyOnClose
      extra={
        <div className="flex gap-2">
          <Button onClick={onClose}>取消</Button>
          <Button type="primary" onClick={handleSubmit} loading={createMutation.isPending}>
            创建
          </Button>
        </div>
      }
    >
      <div className="flex flex-col gap-5 pb-8">
        {/* ── Basic info ── */}
        <Section title="基本信息">
          <div className="space-y-3">
            <div>
              <Label required>工具名称</Label>
              <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="如: github_list_issues" showCount maxLength={100} />
            </div>
            <div>
              <Label>描述</Label>
              <Input value={description} onChange={(e) => setDescription(e.target.value)} placeholder="如: 列出指定仓库的 GitHub Issues" />
            </div>
            <div>
              <Label>工具类型</Label>
              <Segmented
                value={source}
                onChange={(val) => setSource(val as ToolSource)}
                options={[
                  { label: 'OpenAPI（HTTP 请求）', value: 'openapi', icon: <GlobalOutlined /> },
                  { label: 'Code（Python 代码）', value: 'code', icon: <CodeOutlined /> },
                ]}
                block
              />
            </div>
          </div>
        </Section>

        {/* ── Create mode (OpenAPI only) ── */}
        {source === 'openapi' && (
          <Section title="创建方式">
            <Radio.Group value={createMode} onChange={(e) => setCreateMode(e.target.value)}>
              <Radio value="manual">手动配置（逐个填参数）</Radio>
              <Radio value="openapi_import">导入 OpenAPI 规范</Radio>
            </Radio.Group>

            {createMode === 'openapi_import' && (
              <div className="mt-3">
                <Label>粘贴 OpenAPI JSON</Label>
                <TextArea
                  rows={8}
                  value={openapiSpec}
                  onChange={(e) => setOpenapiSpec(e.target.value)}
                  placeholder={'{\n  "openapi": "3.0.0",\n  "paths": {\n    "/search": {\n      "get": { ... }\n    }\n  }\n}'}
                  className="font-mono text-xs"
                />
                <Button className="mt-2" size="small" onClick={parseOpenApi}>解析并填充</Button>
                <p className="text-[11px] text-[#94A3B8] mt-1">
                  粘贴 OpenAPI 规范 JSON，解析后自动填充 URL、方法和参数。默认取第一个 path + method。
                </p>
              </div>
            )}
          </Section>
        )}

        {/* ── Credential ── */}
        <Section title="认证">
          <Label>关联凭据</Label>
          <Select
            allowClear
            value={credentialId || undefined}
            onChange={(val) => setCredentialId(val || '')}
            placeholder="选择凭据（可选）"
            className="w-full"
            options={(credData?.items || []).map((c) => ({
              value: c._id,
              label: `${c.name} (${c.type})`,
            }))}
          />
          <p className="text-[11px] text-[#94A3B8] mt-1">
            在凭据管理页面创建凭据（API Key / Token）。工具执行时通过 {'{{credential.xxx}}'} 模板引用。
          </p>
        </Section>

        {/* ── Parameters ── */}
        <Section title="LLM 参数" subtitle="LLM 调用工具时传入的参数（LLM 看到的参数描述）">
          <ParamEditor value={params} onChange={setParams} />
        </Section>

        {/* ── Execution config (OpenAPI) ── */}
        {source === 'openapi' && (
          <Section title="HTTP 配置" subtitle="用 {{config.xxx}} 引用预设参数，{{credential.xxx}} 引用凭据，{{param_name}} 引用 LLM 参数">
            <div className="space-y-4">
              <div className="grid grid-cols-[100px_1fr] gap-3 items-center">
                <Label required>请求方法</Label>
                <Select
                  value={method}
                  onChange={setMethod}
                  options={['GET', 'POST', 'PUT', 'DELETE'].map(m => ({ value: m, label: m }))}
                  className="w-32"
                />
              </div>
              <div>
                <Label required>URL</Label>
                <Input
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                  placeholder="https://api.example.com/{{config.path}}/resource"
                />
                <p className="text-[11px] text-[#94A3B8] mt-1">
                  <code className="text-[#6366F1]">{'{{config.xxx}}'}</code> 引用预设参数，{' '}
                  <code className="text-[#6366F1]">{'{{param_name}}'}</code> 引用 LLM 参数
                </p>
              </div>

              <Divider className="!my-2" />

              <div>
                <Label>Headers</Label>
                <KeyValueEditor
                  value={headers}
                  onChange={setHeaders}
                  keyPlaceholder="Header 名（如 Authorization）"
                  valuePlaceholder={'如: Bearer {{credential.token}}'}
                  emptyHint="暂无 Headers"
                />
              </div>

              <div>
                <Label>Query Params</Label>
                <KeyValueEditor
                  value={queryParams}
                  onChange={setQueryParams}
                  keyPlaceholder="参数名（如 state）"
                  valuePlaceholder={'如: {{state}}'}
                  emptyHint="暂无 Query Params"
                />
              </div>

              <div>
                <Label>预设参数（非敏感）</Label>
                <KeyValueEditor
                  value={config}
                  onChange={setConfig}
                  keyPlaceholder="参数名（如 owner）"
                  valuePlaceholder="如: myorg"
                  emptyHint="暂无预设参数"
                />
                <p className="text-[11px] text-[#94A3B8] mt-1">
                  这些参数在工具配置时预设，不暴露给 LLM。如默认仓库 owner、超时时间等。
                </p>
              </div>
            </div>
          </Section>
        )}

        {/* ── Code config ── */}
        {source === 'code' && (
          <Section title="Python 代码" subtitle="定义一个与工具同名的函数，返回 str。凭据经环境变量 CRED_xxx 注入">
            <TextArea
              rows={12}
              value={code}
              onChange={(e) => setCode(e.target.value)}
              placeholder={`def ${name || 'my_tool'}(query: str) -> str:\n    """\n    工具描述\n    """\n    import os\n    token = os.environ.get('CRED_token', '')\n    return f"result: {query}"`}
              className="font-mono text-sm"
            />
            <p className="text-[11px] text-[#94A3B8] mt-1">
              函数参数名需与上方 LLM 参数名一致。代码在沙箱中执行。
            </p>
          </Section>
        )}
      </div>
    </Drawer>
  )
}

// ── UI helpers ──

function Section({ title, subtitle, children }: { title: string; subtitle?: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="mb-3">
        <h3 className="text-sm font-semibold text-[#0F172A]">{title}</h3>
        {subtitle && <p className="text-[11px] text-[#94A3B8] mt-0.5">{subtitle}</p>}
      </div>
      {children}
    </div>
  )
}

function Label({ children, required }: { children: React.ReactNode; required?: boolean }) {
  return (
    <label className="block text-sm text-[#0F172A] mb-1.5">
      {children}
      {required && <span className="text-[#EF4444] ml-0.5">*</span>}
    </label>
  )
}
