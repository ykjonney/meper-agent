/**
 * Tools page — Skill tool registry with real backend integration.
 */
import { useState } from 'react'
import { Button, Tag, Spin, Empty, message } from 'antd'
import {
  SearchOutlined,
  MoreOutlined,
  PlusOutlined,
  FileTextOutlined,
  FolderOutlined,
} from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { useTheme } from '../contexts/ThemeContext'
import { toolsApi, toolKeys } from '../services/tools-api'
import SkillUploadModal from '../components/skill-upload-modal'

const STATUS_MAP: Record<string, { label: string; color: string; bg: string }> = {
  draft: { label: '草稿', color: '#64748B', bg: '#F1F5F9' },
  active: { label: '已启用', color: '#10B981', bg: '#ECFDF5' },
  inactive: { label: '已停用', color: '#F43F5E', bg: '#FFF1F2' },
}

export default function ToolsPage() {
  const { t } = useTheme()
  const navigate = useNavigate()
  const [uploadOpen, setUploadOpen] = useState(false)
  const [searchName, setSearchName] = useState('')

  const { data, isLoading, refetch } = useQuery({
    queryKey: toolKeys.list({ name: searchName || undefined }),
    queryFn: () => toolsApi.list({ name: searchName || undefined, page_size: 100 }),
  })

  const tools = data?.items ?? []

  return (
    <div className="animate-[fadeIn_0.3s_ease-out]">
      {/* Header */}
      <div className="flex items-center justify-between gap-4 mb-6">
        <div className="relative">
          <SearchOutlined className="absolute left-3 top-1/2 -translate-y-1/2 text-[#94A3B8] text-sm" />
          <input
            type="text"
            placeholder="搜索工具..."
            value={searchName}
            onChange={(e) => setSearchName(e.target.value)}
            className="pl-9 pr-4 py-2 rounded-lg border border-gray-200 text-sm focus:outline-none focus:ring-2 w-64"
            style={{ '--tw-ring-color': t.bg } as React.CSSProperties}
          />
        </div>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setUploadOpen(true)}>
          上传 Skill
        </Button>
      </div>

      {/* Tool grid */}
      {isLoading ? (
        <div className="flex justify-center py-20">
          <Spin size="large" />
        </div>
      ) : tools.length === 0 ? (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description="暂无工具，点击右上角上传 Skill"
          className="py-20"
        />
      ) : (
        <div className="grid grid-cols-3 gap-4">
          {tools.map((tool) => {
            const st = STATUS_MAP[tool.status] ?? STATUS_MAP.draft
            const isDirectory = tool.files.length > 0
            return (
              <div
                key={tool.id}
                className="rounded-xl border border-gray-200 bg-white p-5 hover:shadow-sm transition-all duration-200 cursor-pointer"
                onClick={() => navigate(`/tools/${tool.id}`)}
              >
                <div className="flex items-start justify-between mb-3">
                  <div className="flex items-center gap-3">
                    <div
                      className="w-10 h-10 rounded-lg flex items-center justify-center text-base"
                      style={{ background: t.bg, color: t.primary }}
                    >
                      {isDirectory ? <FolderOutlined /> : <FileTextOutlined />}
                    </div>
                    <div>
                      <div className="text-sm font-medium text-[#0F172A]">{tool.name}</div>
                      <div className="text-xs text-[#64748B] line-clamp-2">{tool.description}</div>
                    </div>
                  </div>
                  <button
                    className="border-0 bg-transparent w-8 h-8 flex items-center justify-center rounded-md text-[#64748B] hover:text-[#0F172A] hover:bg-gray-50 transition-colors duration-150"
                    onClick={(e) => {
                      e.stopPropagation()
                      message.info('更多操作菜单开发中')
                    }}
                  >
                    <MoreOutlined />
                  </button>
                </div>
                <div className="flex items-center justify-between pt-3 border-t border-gray-50">
                  <Tag
                    className="!m-0 !px-2 !py-0.5 !text-xs !rounded"
                    style={{ color: st.color, background: st.bg, borderColor: 'transparent' }}
                  >
                    {st.label}
                  </Tag>
                  <span className="text-xs text-[#94A3B8]">
                    {isDirectory ? `${tool.files.length} 文件` : `v${tool.version}`}
                  </span>
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
