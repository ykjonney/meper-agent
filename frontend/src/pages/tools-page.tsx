/**
 * Tools page — display built-in tools (bash / read / write).
 *
 * Built-in tools are always available to every Agent.
 * Skill management lives on the /skills page; MCP tools on /mcp.
 */
import { useState } from 'react'
import { Spin, Empty, Tag } from 'antd'
import {
  SearchOutlined,
  CodeOutlined,
  ReadOutlined,
  EditOutlined,
  ToolOutlined,
} from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { useTheme } from '../contexts/ThemeContext'
import { toolsApi } from '../services/tools-api'
import type { BuiltinTool } from '../services/tools-api'

/* ─── Icon mapping for known built-in tools ─── */
const TOOL_ICONS: Record<string, typeof CodeOutlined> = {
  bash: CodeOutlined,
  read: ReadOutlined,
  write: EditOutlined,
}

export default function ToolsPage() {
  const { t } = useTheme()
  const [searchName, setSearchName] = useState('')

  const { data: tools, isLoading } = useQuery({
    queryKey: ['builtin-tools'],
    queryFn: () => toolsApi.listBuiltins(),
  })

  const filtered = (tools ?? []).filter((tool) => {
    if (!searchName) return true
    const q = searchName.toLowerCase()
    return (
      tool.name.toLowerCase().includes(q) ||
      tool.description.toLowerCase().includes(q)
    )
  })

  return (
    <div className="animate-[fadeIn_0.3s_ease-out]">
      {/* Header */}
      <div className="flex items-center justify-between gap-4 mb-6">
        <div className="flex items-center gap-3">
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
          <Tag
            className="!m-0 !px-2 !py-0.5 !text-xs !rounded"
            style={{ color: '#7C3AED', background: '#EDE9FE', borderColor: 'transparent' }}
          >
            内建工具
          </Tag>
        </div>
      </div>

      {/* Tool grid */}
      {isLoading ? (
        <div className="flex justify-center py-20">
          <Spin size="large" />
        </div>
      ) : filtered.length === 0 ? (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description="暂无内建工具"
          className="py-20"
        />
      ) : (
        <div className="grid grid-cols-3 gap-4">
          {filtered.map((tool) => (
            <BuiltinToolCard key={tool.name} tool={tool} />
          ))}
        </div>
      )}
    </div>
  )
}

/* ─── Sub-component: single builtin tool card ─── */

function BuiltinToolCard({ tool }: { tool: BuiltinTool }) {
  const { t } = useTheme()
  const Icon = TOOL_ICONS[tool.name] ?? ToolOutlined

  // Extract parameter names from JSON Schema
  const paramNames = Object.keys(
    (tool.parameters?.properties as Record<string, unknown>) ?? {}
  )

  return (
    <div className="rounded-xl border border-gray-200 bg-white p-5 hover:shadow-sm transition-all duration-200">
      <div className="flex items-start gap-3 mb-3">
        <div
          className="w-10 h-10 rounded-lg flex items-center justify-center text-base shrink-0"
          style={{ background: t.bg, color: t.primary }}
        >
          <Icon />
        </div>
        <div className="min-w-0">
          <div className="text-sm font-medium text-[#0F172A]">{tool.name}</div>
          <div className="text-xs text-[#64748B] line-clamp-2">{tool.description}</div>
        </div>
      </div>

      {/* Parameters */}
      <div className="pt-3 border-t border-gray-50">
        {paramNames.length > 0 ? (
          <div className="flex flex-wrap gap-1.5">
            {paramNames.map((p) => (
              <Tag
                key={p}
                className="!m-0 !px-2 !py-0.5 !text-[11px] !rounded"
                style={{ color: '#64748B', background: '#F1F5F9', borderColor: 'transparent' }}
              >
                {p}
              </Tag>
            ))}
          </div>
        ) : (
          <span className="text-xs text-[#94A3B8]">无参数</span>
        )}
      </div>
    </div>
  )
}
