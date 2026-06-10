/**
 * Skills page — manage agent skills (Markdown Skill files).
 *
 * Skills are the user-authored half of the unified tool pool
 * (source = "markdown").  MCP-sourced tools live under /mcp.
 */
import { useState } from 'react'
import { Button, Tag, Select, Tooltip, Switch, Spin, Empty, message, Popconfirm } from 'antd'
import {
  PlusOutlined,
  SearchOutlined,
  FileTextOutlined,
  FolderOutlined,
  MoreOutlined,
  EditOutlined,
  DeleteOutlined,
} from '@ant-design/icons'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { useTheme } from '../contexts/ThemeContext'
import { toolsApi, toolKeys, type ToolStatus } from '../services/tools-api'
import SkillUploadModal from '../components/skill-upload-modal'

/* ─── Source mappings (only markdown/custom sources on this page) ─── */
const SOURCE_STYLES: Record<string, { label: string; color: string; bg: string }> = {
  markdown: { label: 'Markdown', color: '#2563EB', bg: '#DBEAFE' },
  custom: { label: '自定义', color: '#7C3AED', bg: '#EDE9FE' },
}

/* ─── Status mappings ─── */
const STATUS_LABEL: Record<string, string> = {
  draft: '草稿',
  active: '已启用',
  inactive: '已停用',
}

export default function SkillsPage() {
  const { t } = useTheme()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState<'all' | ToolStatus>('all')
  const [uploadOpen, setUploadOpen] = useState(false)

  /* Fetch all tools, filter to markdown-source on client */
  const { data, isLoading, refetch } = useQuery({
    queryKey: toolKeys.list({ page_size: 100 }),
    queryFn: () => toolsApi.list({ page_size: 100 }),
  })

  const allSkills = (data?.items ?? []).filter((tool) => tool.source === 'markdown')

  /* Apply search + status filter on client */
  const filtered = allSkills.filter((s) => {
    const matchSearch =
      !search ||
      s.name.toLowerCase().includes(search.toLowerCase()) ||
      s.description.toLowerCase().includes(search.toLowerCase())
    const matchStatus = statusFilter === 'all' || s.status === statusFilter
    return matchSearch && matchStatus
  })

  /* Stats derived from the full list */
  const stats = [
    { label: 'Skill 总数', value: allSkills.length.toString() },
    { label: '已启用', value: allSkills.filter((s) => s.status === 'active').length.toString() },
    {
      label: '草稿',
      value: allSkills.filter((s) => s.status === 'draft').length.toString(),
    },
    {
      label: '目录包',
      value: allSkills.filter((s) => s.files.length > 0).length.toString(),
    },
  ]

  /* Toggle status mutation */
  const toggleMutation = useMutation({
    mutationFn: ({ id, next }: { id: string; next: ToolStatus }) =>
      toolsApi.update(id, { status: next }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: toolKeys.lists() })
      message.success('状态已更新')
    },
    onError: (err: unknown) => {
      const error = err as { message?: string }
      message.error(error?.message ?? '更新失败')
    },
  })

  /* Delete mutation */
  const deleteMutation = useMutation({
    mutationFn: (id: string) => toolsApi.remove(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: toolKeys.lists() })
      message.success('已删除')
    },
    onError: (err: unknown) => {
      const error = err as { message?: string }
      message.error(error?.message ?? '删除失败')
    },
  })

  const handleToggle = (skill: (typeof allSkills)[number]) => {
    const next: ToolStatus = skill.status === 'active' ? 'inactive' : 'active'
    toggleMutation.mutate({ id: skill.id, next })
  }

  const handleDelete = (skill: (typeof allSkills)[number]) => {
    deleteMutation.mutate(skill.id)
  }

  return (
    <div className="animate-[fadeIn_0.3s_ease-out]">
      {/* Stats row */}
      <div className="grid grid-cols-4 gap-4 mb-6">
        {stats.map((s) => (
          <div key={s.label} className="rounded-xl border border-gray-200 bg-white p-4">
            <div className="text-2xl font-semibold text-[#0F172A] mb-0.5">{s.value}</div>
            <div className="text-xs text-[#64748B]">{s.label}</div>
          </div>
        ))}
      </div>

      {/* Search / action bar */}
      <div className="flex items-center justify-between gap-4 mb-6">
        <div className="flex items-center gap-3">
          <div className="relative">
            <SearchOutlined className="absolute left-3 top-1/2 -translate-y-1/2 text-[#94A3B8] text-sm" />
            <input
              type="text"
              placeholder="搜索 Skill..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-9 pr-4 py-2 rounded-lg border border-gray-200 text-sm focus:outline-none focus:ring-2 w-64"
              style={{ '--tw-ring-color': t.bg } as React.CSSProperties}
            />
          </div>
          <Select
            value={statusFilter}
            onChange={(v) => setStatusFilter(v as 'all' | ToolStatus)}
            className="w-28"
            options={[
              { value: 'all', label: '全部状态' },
              { value: 'draft', label: '草稿' },
              { value: 'active', label: '已启用' },
              { value: 'inactive', label: '已停用' },
            ]}
          />
        </div>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setUploadOpen(true)}>
          创建 Skill
        </Button>
      </div>

      {/* Skill cards */}
      {isLoading ? (
        <div className="flex justify-center py-20">
          <Spin size="large" />
        </div>
      ) : filtered.length === 0 ? (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={search || statusFilter !== 'all' ? '没有匹配的 Skill' : '暂无 Skill，点击右上角创建'}
          className="py-20"
        />
      ) : (
        <div className="grid grid-cols-3 gap-4">
          {filtered.map((skill) => {
            const srcStyle = SOURCE_STYLES[skill.source] ?? SOURCE_STYLES.markdown
            const isDirectory = skill.files.length > 0
            return (
              <div
                key={skill.id}
                className="rounded-xl border border-gray-200 bg-white p-5 hover:shadow-sm transition-all duration-200 cursor-pointer"
                onClick={() => navigate(`/tools/${skill.id}`)}
              >
                {/* Header */}
                <div className="flex items-start justify-between mb-3">
                  <div className="flex items-center gap-3 min-w-0">
                    <div
                      className="w-10 h-10 rounded-lg flex items-center justify-center text-base shrink-0"
                      style={{ background: t.bg, color: t.primary }}
                    >
                      {isDirectory ? <FolderOutlined /> : <FileTextOutlined />}
                    </div>
                    <div className="min-w-0">
                      <div className="text-sm font-medium text-[#0F172A] truncate">{skill.name}</div>
                      <div className="text-xs text-[#64748B] truncate max-w-[160px]">
                        {skill.description || '(无描述)'}
                      </div>
                    </div>
                  </div>
                  <button
                    className="border-0 bg-transparent w-8 h-8 flex items-center justify-center rounded-md text-[#64748B] hover:text-[#0F172A] hover:bg-gray-50 transition-colors duration-150 shrink-0"
                    onClick={(e) => {
                      e.stopPropagation()
                      message.info('更多操作菜单开发中')
                    }}
                  >
                    <MoreOutlined />
                  </button>
                </div>

                {/* Source + file-count tags */}
                <div className="flex items-center gap-2 mb-3">
                  <Tag
                    className="!m-0 !px-2 !py-0.5 !text-[11px] !rounded"
                    style={{ color: srcStyle.color, background: srcStyle.bg, borderColor: 'transparent' }}
                  >
                    {srcStyle.label}
                  </Tag>
                  {isDirectory && (
                    <span className="text-[11px] text-[#94A3B8]">{skill.files.length} 文件</span>
                  )}
                  <span className="text-[11px] text-[#94A3B8]">v{skill.version}</span>
                </div>

                {/* Footer: status switch + actions */}
                <div
                  className="flex items-center justify-between pt-3 border-t border-gray-50"
                  onClick={(e) => e.stopPropagation()}
                >
                  <div className="flex items-center gap-2">
                    <Switch
                      size="small"
                      checked={skill.status === 'active'}
                      loading={toggleMutation.isPending && toggleMutation.variables?.id === skill.id}
                      onChange={() => handleToggle(skill)}
                      style={{ background: skill.status === 'active' ? t.primary : undefined }}
                    />
                    <span className="text-xs text-[#64748B]">{STATUS_LABEL[skill.status]}</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <Tooltip title="编辑">
                      <button
                        className="border-0 bg-transparent w-7 h-7 flex items-center justify-center rounded text-[#94A3B8] hover:text-[#0F172A] hover:bg-gray-50 transition-colors duration-150 text-xs"
                        onClick={() => navigate(`/tools/${skill.id}`)}
                      >
                        <EditOutlined />
                      </button>
                    </Tooltip>
                    <Popconfirm
                      title="确认删除"
                      description={`删除 Skill "${skill.name}"？`}
                      okText="删除"
                      cancelText="取消"
                      okButtonProps={{ danger: true }}
                      onConfirm={() => handleDelete(skill)}
                    >
                      <Tooltip title="删除">
                        <button className="border-0 bg-transparent w-7 h-7 flex items-center justify-center rounded text-[#94A3B8] hover:text-[#F43F5E] hover:bg-rose-50 transition-colors duration-150 text-xs">
                          <DeleteOutlined />
                        </button>
                      </Tooltip>
                    </Popconfirm>
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      )}

      <SkillUploadModal
        open={uploadOpen}
        onClose={() => setUploadOpen(false)}
        onSuccess={() => refetch()}
      />
    </div>
  )
}
