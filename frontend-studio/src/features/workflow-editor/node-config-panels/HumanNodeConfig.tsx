/**
 * HumanNodeConfig — 人工审批节点配置面板。
 *
 * 系统固定提供三个审批行为，无需用户配置：
 *   1. approve  — 通过
 *   2. reject   — 驳回
 *   3. comment  — 审批人留言（可选，approval 时给出意见）
 *
 * 审批结果以 {decision, comment, approver, decided_at} 结构写入
 *   variables[human_decision_<node_id>]
 * 供下游 Gateway 节点条件分支消费。
 *
 * antd 组件 → 原生 Tailwind ui 封装；@ant-design/icons → lucide-react。
 */
import { Select, Tag } from '../../../components/ui'

interface Props {
  config: Record<string, unknown>
  onChange: (c: Record<string, unknown>) => void
}

const TIMEOUT_ACTIONS = [
  { label: '自动通过', value: 'auto_approve' },
  { label: '自动驳回', value: 'auto_reject' },
  { label: '自动跳过', value: 'auto_skip' },
  { label: '标记失败', value: 'fail' },
]

export default function HumanNodeConfig({ config, onChange }: Props) {
  return (
    <div className="space-y-3">
      {/* ── 审批标题 ── */}
      <div>
        <label className="block text-xs text-slate-400 mb-1">审批标题</label>
        <input
          className="w-full px-2 py-1.5 rounded border border-[#27272a] bg-[#121214] text-[#fafafa] text-sm focus:outline-none focus:border-[#8B5CF6]"
          value={typeof config?.title === 'string' ? config.title : ''}
          onChange={(e) => onChange({ ...(config ?? {}), title: e.target.value })}
          placeholder="请审批以下内容"
        />
      </div>

      {/* ── 审批描述 ── */}
      <div>
        <label className="block text-xs text-slate-400 mb-1">审批描述</label>
        <textarea
          className="w-full px-2 py-1.5 rounded border border-[#27272a] bg-[#121214] text-[#fafafa] text-sm resize-y focus:outline-none focus:border-[#8B5CF6]"
          value={typeof config?.description === 'string' ? config.description : ''}
          onChange={(e) => onChange({ ...(config ?? {}), description: e.target.value })}
          rows={3}
          placeholder="描述需要人工审批的内容..."
        />
      </div>

      {/* ── 审批行为（系统固定三个：approve / reject / comment） ── */}
      <div>
        <label className="block text-xs text-slate-400 mb-1.5">审批行为</label>
        <div className="space-y-1.5">
          <div className="flex items-center gap-2 px-2.5 py-1.5 rounded border border-[#27272a] bg-[#1e1e22]">
            <Tag color="success">通过</Tag>
            <span className="text-xs text-slate-400 flex-1">
              审批人点击后，任务继续执行，decision=<code className="font-mono text-[#a78bfa]">approve</code>
            </span>
          </div>
          <div className="flex items-center gap-2 px-2.5 py-1.5 rounded border border-[#27272a] bg-[#1e1e22]">
            <Tag color="error">驳回</Tag>
            <span className="text-xs text-slate-400 flex-1">
              审批人点击后，任务标记为 FAILED，decision=<code className="font-mono text-[#a78bfa]">reject</code>
            </span>
          </div>
          <div className="flex items-center gap-2 px-2.5 py-1.5 rounded border border-[#27272a] bg-[#1e1e22]">
            <Tag color="purple">意见</Tag>
            <span className="text-xs text-slate-400 flex-1">
              审批人在通过/驳回时填写，可空，comment 写入 variables
            </span>
          </div>
        </div>
        <div className="text-[10px] text-[#71717a] mt-1.5">
          审批完成后，<code className="font-mono">variables.human_decision_&lt;node_id&gt;</code> 包含
          decision / comment / approver / decided_at 四个字段
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
