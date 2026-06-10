/**
 * API Keys page — manage API keys and webhook endpoints for external integrations.
 *
 * Aligned with Story 8-4: API key detail page and webhook management UI.
 */
import { useState } from 'react'
import { Button, Tag, Tooltip, Switch } from 'antd'
import { SearchOutlined, PlusOutlined, KeyOutlined, CopyOutlined, EyeOutlined, EyeInvisibleOutlined, DeleteOutlined, MoreOutlined, LinkOutlined, EditOutlined, ApiOutlined, ClockCircleOutlined } from '@ant-design/icons'
import { useTheme } from '../contexts/ThemeContext'

const API_KEYS = [
  { name: '生产环境密钥', key: 'sk-af-8a3f2b1c', prefix: 'sk-af-8a3f', model: 'GPT-4', created: '2026-03-15', lastUsed: '2 分钟前', status: 'active', scope: '全部' },
  { name: '测试环境密钥', key: 'sk-af-7e2d9f4a', prefix: 'sk-af-7e2d', model: 'Claude 3', created: '2026-04-01', lastUsed: '1 小时前', status: 'active', scope: '对话' },
  { name: '开发调试密钥', key: 'sk-af-1c5b4d8e', prefix: 'sk-af-1c5b', model: 'Gemini', created: '2026-05-10', lastUsed: '3 天前', status: 'active', scope: 'Agent' },
  { name: '旧版 API 密钥', key: 'sk-af-9f3a6c2d', prefix: 'sk-af-9f3a', model: 'GPT-3.5', created: '2026-01-20', lastUsed: '30 天前', status: 'revoked', scope: '全部' },
]

const WEBHOOKS = [
  { name: '执行完成通知', url: 'https://hooks.company.com/agent-flow/completed', events: ['task.completed'], status: 'active', lastSent: '2 分钟前' },
  { name: '异常告警', url: 'https://hooks.company.com/agent-flow/error', events: ['task.failed', 'agent.error'], status: 'active', lastSent: '1 小时前' },
  { name: '日志归档', url: 'https://hooks.company.com/agent-flow/logs', events: ['task.completed', 'task.started'], status: 'inactive', lastSent: '3 天前' },
]

export default function ApiKeysPage() {
  const { t } = useTheme()
  const [visible, setVisible] = useState<Record<number, boolean>>({})

  const toggleVisible = (i: number) => setVisible((prev) => ({ ...prev, [i]: !prev[i] }))

  return (
    <div className="animate-[fadeIn_0.3s_ease-out]">
      {/* Stats */}
      <div className="grid grid-cols-4 gap-4 mb-6">
        {[
          { label: '活跃密钥', value: API_KEYS.filter(k => k.status === 'active').length.toString() },
          { label: '今日调用', value: '12,847' },
          { label: 'Webhook', value: WEBHOOKS.filter(w => w.status === 'active').length.toString() },
          { label: '本月用量', value: '284K' },
        ].map((s) => (
          <div key={s.label} className="rounded-xl border border-gray-200 bg-white p-4">
            <div className="text-2xl font-semibold text-[#0F172A] mb-0.5">{s.value}</div>
            <div className="text-xs text-[#64748B]">{s.label}</div>
          </div>
        ))}
      </div>

      {/* ══════════ API Keys Section ══════════ */}
      <div className="flex items-center justify-between gap-4 mb-4">
        <div className="flex items-center gap-2">
          <KeyOutlined style={{ color: t.primary }} />
          <span className="font-semibold text-sm text-[#0F172A]">API 密钥</span>
        </div>
        <Button type="primary" icon={<PlusOutlined />} size="small">创建密钥</Button>
      </div>

      <div className="rounded-xl border border-gray-200 bg-white mb-6">
        {API_KEYS.map((apiKey, i) => (
          <div key={apiKey.key} className={`flex items-center justify-between px-5 py-4 hover:bg-[#F8FAFC] transition-colors duration-150 ${i > 0 ? 'border-t border-gray-50' : ''}`}>
            <div className="flex items-center gap-3 min-w-0 flex-1">
              <div className="w-9 h-9 rounded-lg flex items-center justify-center text-base shrink-0" style={{ background: t.bg, color: t.primary }}>
                <KeyOutlined />
              </div>
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium text-[#0F172A]">{apiKey.name}</span>
                  <Tag className="!m-0 !px-1.5 !py-0 !text-[10px] !rounded" style={{ color: '#64748B', background: '#F1F5F9', borderColor: 'transparent' }}>{apiKey.scope}</Tag>
                </div>
                <div className="flex items-center gap-2 text-xs text-[#64748B] mt-0.5">
                  <span className="font-mono bg-[#F8FAFC] px-2 py-0.5 rounded border border-gray-100 inline-flex items-center gap-2">
                    {visible[i] ? apiKey.key : apiKey.prefix + '...' + apiKey.key.slice(-4)}
                    <button onClick={() => toggleVisible(i)} className="border-0 bg-transparent text-[#94A3B8] hover:text-[#0F172A] cursor-pointer text-xs">
                      {visible[i] ? <EyeInvisibleOutlined /> : <EyeOutlined />}
                    </button>
                  </span>
                  <Tooltip title="复制密钥">
                    <button className="border-0 bg-transparent text-[#94A3B8] hover:text-[#0F172A] cursor-pointer text-xs"><CopyOutlined /></button>
                  </Tooltip>
                </div>
              </div>
            </div>
            <div className="flex items-center gap-4 ml-3 shrink-0">
              <div className="text-right">
                <div className="text-xs text-[#64748B]">{apiKey.model}</div>
                <div className="text-[11px] text-[#94A3B8]">{apiKey.lastUsed}</div>
              </div>
              <Tag className="!m-0 !px-2 !py-0.5 !text-xs !rounded" style={{
                color: apiKey.status === 'active' ? '#10B981' : '#94A3B8',
                background: apiKey.status === 'active' ? '#D1FAE5' : '#F1F5F9',
                borderColor: 'transparent',
              }}>
                {apiKey.status === 'active' ? '活跃' : '已吊销'}
              </Tag>
              <Tooltip title="删除">
                <button className="border-0 bg-transparent w-8 h-8 flex items-center justify-center rounded-md text-[#64748B] hover:text-[#EF4444] hover:bg-gray-50 transition-colors duration-150"><DeleteOutlined /></button>
              </Tooltip>
            </div>
          </div>
        ))}
      </div>

      {/* ══════════ Webhooks Section ══════════ */}
      <div className="flex items-center justify-between gap-4 mb-4">
        <div className="flex items-center gap-2">
          <LinkOutlined style={{ color: t.primary }} />
          <span className="font-semibold text-sm text-[#0F172A]">Webhook 配置</span>
        </div>
        <Button type="primary" icon={<PlusOutlined />} size="small">添加 Webhook</Button>
      </div>

      <div className="rounded-xl border border-gray-200 bg-white">
        {/* Table header */}
        <div className="grid grid-cols-[1fr_120px_80px] gap-4 px-5 py-3 bg-[#F8FAFC] border-b border-gray-100 text-xs font-medium text-[#64748B]">
          <span>名称 / 端点</span>
          <span>状态</span>
          <span></span>
        </div>

        {WEBHOOKS.map((wh, i) => (
          <div key={wh.name} className={`grid grid-cols-[1fr_120px_80px] gap-4 px-5 py-3.5 items-center hover:bg-[#F8FAFC] transition-colors duration-150 ${i > 0 ? 'border-t border-gray-50' : ''}`}>
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <ApiOutlined className="text-[#94A3B8] text-xs" />
                <span className="text-sm font-medium text-[#0F172A]">{wh.name}</span>
              </div>
              <div className="flex items-center gap-2 mt-0.5">
                <code className="text-[11px] font-mono text-[#64748B] bg-[#F8FAFC] px-1.5 py-0.5 rounded border border-gray-100 truncate max-w-[320px] block">{wh.url}</code>
                <Tooltip title="编辑">
                  <button className="border-0 bg-transparent text-[#94A3B8] hover:text-[#0F172A] cursor-pointer text-xs"><EditOutlined /></button>
                </Tooltip>
              </div>
              <div className="flex items-center gap-1 mt-0.5">
                {wh.events.map((ev) => (
                  <Tag key={ev} className="!m-0 !px-1.5 !py-0 !text-[10px] !rounded font-mono" style={{ color: '#64748B', background: '#F1F5F9', borderColor: 'transparent' }}>{ev}</Tag>
                ))}
                <span className="text-[10px] text-[#94A3B8] ml-1 flex items-center gap-0.5">
                  <ClockCircleOutlined /> {wh.lastSent}
                </span>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <Switch size="small" checked={wh.status === 'active'} style={{ background: wh.status === 'active' ? t.primary : undefined }} />
              <span className="text-xs text-[#64748B]">{wh.status === 'active' ? '启用' : '停用'}</span>
            </div>
            <button className="border-0 bg-transparent w-8 h-8 flex items-center justify-center rounded-md text-[#64748B] hover:text-[#0F172A] hover:bg-gray-50 transition-colors duration-150"><MoreOutlined /></button>
          </div>
        ))}
      </div>
    </div>
  )
}
