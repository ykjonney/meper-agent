/**
 * HumanNodeConfig — 人工审批节点配置面板。
 *
 * 系统固定提供三个审批行为，无需用户配置：
 *   1. approve  — 通过
 *   2. reject   — 驳回
 *   3. comment  — 审批人留言（可选，approval 时给出意见）
 *
 * 审批标题 / 描述支持变量引用 {{node.field}}，运行时由 HumanNodeExecutor
 * 解析后展示给审批人，让审批人看到上游节点的实际输出。
 *
 * 审批结果以 {decision, comment, approver, decided_at} 结构写入
 *   variables[human_decision_<node_id>]
 * 供下游 Gateway 节点条件分支消费。
 *
 * antd 组件 → 原生 Tailwind ui 封装；@ant-design/icons → lucide-react。
 */
import { Select, Tag } from '../../../components/ui'
import VariableSelector from '../VariableSelector'
import HelpHint from '../HelpHint'
import type { WorkflowNode } from '../../../services/workflows-api'

interface Props {
  config: Record<string, unknown>
  onChange: (c: Record<string, unknown>) => void
  currentNodeId: string
  allNodes: WorkflowNode[]
}

const TIMEOUT_ACTIONS = [
  { label: '自动通过', value: 'auto_approve' },
  { label: '自动驳回', value: 'auto_reject' },
  { label: '自动跳过', value: 'auto_skip' },
  { label: '标记失败', value: 'fail' },
]

export default function HumanNodeConfig({ config, onChange, currentNodeId, allNodes }: Props) {
  return (
    <div className="space-y-3">
      {/* ── 审批标题（支持变量引用） ── */}
      <div>
        <label className="block text-xs text-slate-400 mb-1">审批标题</label>
        <VariableSelector
          value={typeof config?.title === 'string' ? config.title : ''}
          onChange={(val) => onChange({ ...(config ?? {}), title: val })}
          currentNodeId={currentNodeId}
          allNodes={allNodes}
          placeholder="请审批以下内容"
          textarea={false}
          rows={1}
        />
      </div>

      {/* ── 审批内容（Markdown，支持变量引用，可插入上游节点输出） ── */}
      <div>
        <VariableSelector
          label="审批内容"
          labelExtra={
            <HelpHint text="给审批人看的正文，支持 Markdown 与上游节点变量（如 {{node_id.field}}），运行时先解析变量再渲染。" />
          }
          value={typeof config?.description === 'string' ? config.description : ''}
          onChange={(val) => onChange({ ...(config ?? {}), description: val })}
          currentNodeId={currentNodeId}
          allNodes={allNodes}
          rows={4}
          placeholder="需要人工审批的内容（Markdown），可插入上游节点变量，如：\n## 质检报告\n请审核 {{node_id.report}}"
        />
      </div>

      {/* ── 审批行为（系统固定三个：approve / reject / comment） ── */}
      <div>
        <label className="block text-xs text-slate-400 mb-1.5 flex items-center gap-1">
          审批行为
          <HelpHint text="审批完成后，审批结论、意见、审批人和审批时间会写入流程变量，供下游节点引用。" />
        </label>
        <div className="space-y-1.5">
          <div className="flex items-center gap-2 px-2.5 py-1.5 rounded border border-[#27272a] bg-[#1e1e22]">
            <Tag color="success">通过</Tag>
            <span className="text-xs text-slate-400 flex-1">
              审批人点击后，任务继续执行
            </span>
          </div>
          <div className="flex items-center gap-2 px-2.5 py-1.5 rounded border border-[#27272a] bg-[#1e1e22]">
            <Tag color="error">驳回</Tag>
            <span className="text-xs text-slate-400 flex-1">
              审批人点击后，任务标记为失败并终止
            </span>
          </div>
          <div className="flex items-center gap-2 px-2.5 py-1.5 rounded border border-[#27272a] bg-[#1e1e22]">
            <Tag color="purple">意见</Tag>
            <span className="text-xs text-slate-400 flex-1">
              审批人在通过或驳回时填写，可留空
            </span>
          </div>
        </div>
      </div>

      {/* ── 超时时间 ── */}
      <div>
        <label className="block text-xs text-slate-400 mb-1">超时时间 (分钟)</label>
        <input
          className="w-full px-2 py-1.5 rounded border border-[#27272a] bg-[#121214] text-[#fafafa] text-sm focus:outline-none focus:border-[#8B5CF6]"
          type="number"
          value={typeof config?.timeout_minutes === 'number' ? config.timeout_minutes : 60}
          onChange={(e) =>
            onChange({ ...(config ?? {}), timeout_minutes: parseInt(e.target.value) || 60 })
          }
          min={1}
          max={1440}
        />
      </div>

      {/* ── 超时动作 ── */}
      <div>
        <label className="block text-xs text-slate-400 mb-1">超时动作</label>
        <Select
          className="w-full"
          value={typeof config?.timeout_action === 'string' ? config.timeout_action : 'fail'}
          onChange={(val) => onChange({ ...(config ?? {}), timeout_action: val ?? 'fail' })}
          options={TIMEOUT_ACTIONS}
        />
      </div>
    </div>
  )
}
