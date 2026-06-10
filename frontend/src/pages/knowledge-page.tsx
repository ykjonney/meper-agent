/**
 * Knowledge page — knowledge base document management.
 */
import { Button, Tag, Progress } from 'antd'
import { SearchOutlined, PlusOutlined, DatabaseOutlined, FileTextOutlined, LinkOutlined, FolderOutlined, MoreOutlined } from '@ant-design/icons'
import { useTheme } from '../contexts/ThemeContext'

const DOCUMENTS = [
  { name: '产品技术文档.pdf', type: 'PDF', size: '2.4 MB', chunks: 47, status: 'indexed', progress: 100 },
  { name: 'API 参考手册.md', type: 'Markdown', size: '856 KB', chunks: 23, status: 'indexed', progress: 100 },
  { name: '客户 FAQ 合集.txt', type: 'Text', size: '1.2 MB', chunks: 31, status: 'indexed', progress: 100 },
  { name: '内部知识库导出.docx', type: 'Word', size: '5.8 MB', chunks: 89, status: 'processing', progress: 65 },
  { name: '技术白皮书 v2.pdf', type: 'PDF', size: '3.1 MB', chunks: 56, status: 'indexed', progress: 100 },
  { name: '代码规范指南.md', type: 'Markdown', size: '128 KB', chunks: 8, status: 'error', progress: 42 },
]

const STATUS_STYLES: Record<string, { label: string; color: string; bg: string }> = {
  indexed: { label: '已索引', color: '#10B981', bg: '#D1FAE5' },
  processing: { label: '索引中', color: '#F59E0B', bg: '#FEF3C7' },
  error: { label: '失败', color: '#EF4444', bg: '#FEE2E2' },
}

export default function KnowledgePage() {
  const { t } = useTheme()

  return (
    <div className="animate-[fadeIn_0.3s_ease-out]">
      {/* Stats */}
      <div className="grid grid-cols-4 gap-4 mb-6">
        {[
          { label: '文档总数', value: '24' },
          { label: '文本块', value: '1,847' },
          { label: '向量维度', value: '1,536' },
          { label: '存储用量', value: '18.5 MB' },
        ].map((s) => (
          <div key={s.label} className="rounded-xl border border-gray-200 bg-white p-4">
            <div className="text-2xl font-semibold text-[#0F172A] mb-0.5">{s.value}</div>
            <div className="text-xs text-[#64748B]">{s.label}</div>
          </div>
        ))}
      </div>

      {/* Actions */}
      <div className="flex items-center justify-between gap-4 mb-4">
        <div className="relative">
          <SearchOutlined className="absolute left-3 top-1/2 -translate-y-1/2 text-[#94A3B8] text-sm" />
          <input type="text" placeholder="搜索文档..." className="pl-9 pr-4 py-2 rounded-lg border border-gray-200 text-sm focus:outline-none focus:ring-2 w-64" style={{ '--tw-ring-color': t.bg } as React.CSSProperties} />
        </div>
        <Button type="primary" icon={<PlusOutlined />}>上传文档</Button>
      </div>

      {/* Document list */}
      <div className="rounded-xl border border-gray-200 bg-white">
        <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between">
          <span className="font-semibold text-[#0F172A]">文档列表</span>
        </div>
        {DOCUMENTS.map((doc, i) => {
          const st = STATUS_STYLES[doc.status]
          return (
            <div key={i} className={`flex items-center justify-between px-5 py-3.5 hover:bg-[#F8FAFC] transition-colors duration-150 cursor-pointer ${i > 0 ? 'border-t border-gray-50' : ''}`}>
              <div className="flex items-center gap-3 min-w-0 flex-1">
                <div className="w-9 h-9 rounded-lg bg-[#F1F5F9] flex items-center justify-center text-[#475569] shrink-0">
                  {doc.type === 'PDF' ? <FileTextOutlined /> : doc.type === 'Markdown' ? <FileTextOutlined /> : <FileTextOutlined />}
                </div>
                <div className="min-w-0">
                  <div className="text-sm font-medium text-[#0F172A] truncate">{doc.name}</div>
                  <div className="text-xs text-[#64748B]">{doc.type} · {doc.size} · {doc.chunks} 块</div>
                </div>
              </div>
              <div className="flex items-center gap-4 ml-3">
                <Progress percent={doc.progress} size="small" className="!w-12 hidden sm:block" showInfo={false}
                  strokeColor={doc.status === 'error' ? '#EF4444' : doc.status === 'processing' ? '#F59E0B' : '#10B981'}
                  railColor="#F1F5F9"
                />
                <Tag className="!m-0 !px-2 !py-0.5 !text-xs !rounded" style={{ color: st.color, background: st.bg, borderColor: 'transparent' }}>
                  {st.label}
                </Tag>
                <button className="border-0 bg-transparent w-8 h-8 flex items-center justify-center rounded-md text-[#64748B] hover:text-[#0F172A] hover:bg-gray-50 transition-colors duration-150"><MoreOutlined /></button>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
