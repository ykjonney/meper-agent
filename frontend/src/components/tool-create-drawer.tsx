/**
 * ToolCreateDrawer — create custom tools (OpenAPI / Code).
 *
 * Credential model: tool DECLARES what credential it needs (type + fields).
 * Agent config binds the actual credential at use time.
 *
 * Param model: only one kind of params — defined here, LLM fills them at call time.
 * No "preset config" — fixed values go directly in URL/headers.
 */
import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Drawer, Button, Input, Select, Radio, Segmented, message, Divider } from 'antd'
import { GlobalOutlined, CodeOutlined } from '@ant-design/icons'
import { toolsApi } from '../services/tools-api'
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
type CredentialType = 'none' | 'api_key' | 'bearer' | 'basic'

// 凭据类型 → 默认字段名
const CRED_FIELD_PRESETS: Record<string, string[]> = {
  none: [],
  api_key: ['api_key'],
  bearer: ['token'],
  basic: ['username', 'password'],
}

export default function ToolCreateDrawer({ open, onClose }: ToolCreateDrawerProps) {
  const queryClient = useQueryClient()

  // ── Form state ──
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [source, setSource] = useState<ToolSource>('openapi')
  const [createMode, setCreateMode] = useState<CreateMode>('manual')
  const [credentialType, setCredentialType] = useState<CredentialType>('none')
  const [credentialFields, setCredentialFields] = useState<string[]>([])
  const [params, setParams] = useState<ToolParam[]>([])

  // HTTP config
  const [method, setMethod] = useState('GET')
  const [url, setUrl] = useState('')
  const [headers, setHeaders] = useState<KVPair[]>([])
  const [queryParams, setQueryParams] = useState<KVPair[]>([])

  // Code
  const [code, setCode] = useState('')

  // OpenAPI import
  const [openapiSpec, setOpenapiSpec] = useState('')

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
    setCredentialType('none'); setCredentialFields([]); setParams([])
    setMethod('GET'); setUrl(''); setHeaders([]); setQueryParams([])
    setCode(''); setOpenapiSpec('')
  }

  const handleCredentialTypeChange = (type: CredentialType) => {
    setCredentialType(type)
    setCredentialFields(CRED_FIELD_PRESETS[type] ? [...CRED_FIELD_PRESETS[type]] : [])
  }

  // ── Parse OpenAPI spec ──
  const parseOpenApi = () => {
    try {
      const spec = JSON.parse(openapiSpec)
      const paths = spec.paths || {}
      const firstPath = Object.keys(paths)[0]
      if (!firstPath) { message.warning('未找到 paths'); return }
      const pathItem = paths[firstPath]
      const firstMethod = Object.keys(pathItem).find(m => ['get', 'post', 'put', 'delete'].includes(m))
      if (!firstMethod) { message.warning('未找到 method'); return }
      const operation = pathItem[firstMethod]
      if (operation.operationId && !name) setName(operation.operationId)
      if (operation.summary && !description) setDescription(operation.summary)
      setMethod(firstMethod.toUpperCase())
      const serverUrl = spec.servers?.[0]?.url || ''
      setUrl(serverUrl + firstPath)
      const opParams = operation.parameters || []
      const toolParams: ToolParam[] = opParams.map((p: Record<string, unknown>) => ({
        name: p.name as string || '',
        type: (p.schema?.type as string || 'string') as ToolParam['type'],
        required: p.required as boolean || false,
        description: (p.description as string) || '',
      }))
      setParams(toolParams)
      // Auto-detect auth from OpenAPI security
      const security = operation.security || spec.security || []
      if (security.some((s: Record<string, unknown>) => s.bearerAuth || s.BearerAuth)) {
        handleCredentialTypeChange('bearer')
      } else if (security.some((s: Record<string, unknown>) => s.api_key || s.ApiKeyAuth)) {
        handleCredentialTypeChange('api_key')
      }
      message.success(`解析成功：${toolParams.length} 个参数`)
    } catch (err) {
      message.error('JSON 解析失败：' + (err as Error).message)
    }
  }

  // ── Submit ──
  const handleSubmit = () => {
    if (!name.trim()) { message.warning('请输入工具名称'); return }
    const inputSchema = paramsToSchema(params)
    const kvToDict = (kvs: KVPair[]) => {
      const d: Record<string, string> = {}
      for (const kv of kvs) { if (kv.key.trim()) d[kv.key] = kv.value }
      return d
    }

    if (source === 'openapi') {
      if (!url.trim()) { message.warning('请输入 URL'); return }
      createMutation.mutate({
        name: name.trim(), description, source: 'openapi',
        input_schema: inputSchema,
        credential_type: credentialType,
        credential_fields: credentialFields,
        endpoint: {
          method, url,
          headers: kvToDict(headers),
          params: kvToDict(queryParams),
        },
      })
    } else {
      if (!code.trim()) { message.warning('请输入代码'); return }
      createMutation.mutate({
        name: name.trim(), description, source: 'code',
        input_schema: inputSchema,
        credential_type: credentialType,
        credential_fields: credentialFields,
        code,
      })
    }
  }

  // ── Credential hint for templates ──
  const credHint = credentialFields.length > 0
    ? `用 {{credential.${credentialFields[0]}}} 引用凭据`
    : ''

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
          <Button type="primary" onClick={handleSubmit} loading={createMutation.isPending}>创建</Button>
        </div>
      }
    >
      <div className="flex flex-col gap-5 pb-8">
        {/* ── 基本信息 ── */}
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

        {/* ── 创建方式 (OpenAPI only) ── */}
        {source === 'openapi' && (
          <Section title="创建方式">
            <Radio.Group value={createMode} onChange={(e) => setCreateMode(e.target.value)}>
              <Radio value="manual">手动配置</Radio>
              <Radio value="openapi_import">导入 OpenAPI 规范</Radio>
            </Radio.Group>
            {createMode === 'openapi_import' && (
              <div className="mt-3">
                <Label>粘贴 OpenAPI JSON</Label>
                <TextArea rows={6} value={openapiSpec} onChange={(e) => setOpenapiSpec(e.target.value)}
                  placeholder={'{\n  "openapi": "3.0.0",\n  "paths": { ... }\n}'} className="font-mono text-xs" />
                <Button className="mt-2" size="small" onClick={parseOpenApi}>解析并填充</Button>
                <p className="text-[11px] text-[#94A3B8] mt-1">解析后自动填充 URL、方法和参数。</p>
              </div>
            )}
          </Section>
        )}

        {/* ── 凭据声明 ── */}
        <Section title="凭据" subtitle="声明工具需要什么类型的凭据。用户在 Agent 配置时绑定实际凭据值。">
          <div className="space-y-3">
            <div>
              <Label>凭据类型</Label>
              <Select
                value={credentialType}
                onChange={(val) => handleCredentialTypeChange(val as CredentialType)}
                className="w-full"
                options={[
                  { value: 'none', label: '无需认证' },
                  { value: 'api_key', label: 'API Key' },
                  { value: 'bearer', label: 'Bearer Token' },
                  { value: 'basic', label: 'Basic Auth' },
                ]}
              />
            </div>
            {credentialType !== 'none' && (
              <div>
                <Label>凭据字段名</Label>
                <p className="text-[11px] text-[#94A3B8] mb-2">
                  这些字段名用于在 URL / Headers 中用 <code className="text-[#6366F1]">{'{{credential.字段名}}'}</code> 引用凭据值。
                  选择类型后会自动填充默认字段名，可修改。
                </p>
                <div className="flex flex-wrap gap-2">
                  {credentialFields.map((field, i) => (
                    <div key={i} className="flex items-center gap-1 bg-[#F1F5F9] rounded-lg px-3 py-1.5">
                      <code className="text-xs text-[#0F172A]">{field}</code>
                      <button
                        className="text-[#94A3B8] hover:text-[#EF4444] ml-1"
                        onClick={() => setCredentialFields(credentialFields.filter((_, idx) => idx !== i))}
                      >✕</button>
                    </div>
                  ))}
                  <Input
                    size="small"
                    placeholder="添加字段名"
                    className="w-32"
                    onPressEnter={(e) => {
                      const val = (e.target as HTMLInputElement).value.trim()
                      if (val && !credentialFields.includes(val)) {
                        setCredentialFields([...credentialFields, val])
                      }
                      (e.target as HTMLInputElement).value = ''
                    }}
                  />
                </div>
              </div>
            )}
          </div>
        </Section>

        {/* ── 参数定义 ── */}
        <Section title="参数定义" subtitle="定义工具的输入参数。LLM 调用时填入。在 URL 中用 {{参数名}} 引用。">
          <ParamEditor value={params} onChange={setParams} />
        </Section>

        {/* ── HTTP 配置 (OpenAPI) ── */}
        {source === 'openapi' && (
          <Section title="HTTP 配置" subtitle={credHint || '用 {{参数名}} 引用上方定义的参数'}>
            <div className="space-y-4">
              <div className="grid grid-cols-[100px_1fr] gap-3 items-center">
                <Label required>请求方法</Label>
                <Select value={method} onChange={setMethod}
                  options={['GET', 'POST', 'PUT', 'DELETE'].map(m => ({ value: m, label: m }))}
                  className="w-32" />
              </div>
              <div>
                <Label required>URL</Label>
                <Input value={url} onChange={(e) => setUrl(e.target.value)}
                  placeholder="https://api.example.com/{{path_param}}/resource" />
                <p className="text-[11px] text-[#94A3B8] mt-1">
                  <code className="text-[#6366F1]">{'{{参数名}}'}</code> 引用参数定义中的参数
                  {credentialFields.length > 0 && <>, <code className="text-[#6366F1]">{'{{credential.xxx}}'}</code> 引用凭据</>}
                </p>
              </div>
              <Divider className="!my-2" />
              <div>
                <Label>Headers</Label>
                <KeyValueEditor value={headers} onChange={setHeaders}
                  keyPlaceholder="Header 名"
                  valuePlaceholder={credentialFields.length > 0 ? `如: Bearer {{credential.${credentialFields[0]}}}` : 'Header 值'}
                  emptyHint="暂无 Headers" />
              </div>
              <div>
                <Label>Query Params</Label>
                <KeyValueEditor value={queryParams} onChange={setQueryParams}
                  keyPlaceholder="参数名" valuePlaceholder={'{{参数名}}'}
                  emptyHint="暂无 Query Params" />
              </div>
            </div>
          </Section>
        )}

        {/* ── Code ── */}
        {source === 'code' && (
          <Section title="Python 代码" subtitle="参数名自动从上方参数定义生成。凭据经环境变量 CRED_xxx 注入">
            {params.length > 0 && (
              <div className="mb-2 px-3 py-2 bg-[#F0F7FF] rounded-lg border border-[#93C5FD]">
                <p className="text-[11px] text-[#2563EB] mb-1">自动生成的函数签名：</p>
                <code className="text-xs text-[#0F172A] font-mono">
                  def {name || 'my_tool'}({params.map(p => p.name).join(', ')}) -&gt; str:
                </code>
              </div>
            )}
            {credentialFields.length > 0 && (
              <div className="mb-2 px-3 py-2 bg-[#FFFBEB] rounded-lg border border-[#FCD34D]">
                <p className="text-[11px] text-[#92400E]">凭据通过环境变量注入：</p>
                {credentialFields.map(f => (
                  <code key={f} className="text-xs text-[#0F172A] font-mono block">
                    os.environ['CRED_{f}']
                  </code>
                ))}
              </div>
            )}
            <TextArea rows={10} value={code} onChange={(e) => setCode(e.target.value)}
              placeholder={`# 在下方编写函数体\n# 参数名与上方参数定义一致\n\ndef ${name || 'my_tool'}(${params.map(p => p.name).join(', ')}) -> str:\n    return "result"`}
              className="font-mono text-sm" />
            <p className="text-[11px] text-[#94A3B8] mt-1">
              代码在 Docker 沙箱中执行。
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
      {children}{required && <span className="text-[#EF4444] ml-0.5">*</span>}
    </label>
  )
}
