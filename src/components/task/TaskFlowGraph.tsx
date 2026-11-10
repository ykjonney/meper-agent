/**
 * TaskFlowGraph — 执行流程「节点图」视图（流程区切换视图）。
 *
 * 在只读 @xyflow/react 画布上渲染工作流的节点图，并按 task 的执行进度
 * 给每个节点叠执行态高亮（已完成/执行中/失败/审批中/待执行）。
 *
 * 复用 WorkflowDesigner 的纯转换器（toXyflowNodes / deriveXyflowEdgesFromNodes）
 * 与 WorkflowBaseNode 渲染器，但只读：不可拖拽、不可连线、不可删除。
 *
 * 图结构需二次请求 workflowsApi.get(workflow_id)（TaskDetail 只带 workflow_id）。
 * 版本漂移说明：拉的是该 workflow 的最新草稿，若任务跑完后图被改动，node_id 可能对不上；
 * 此时该节点按「待执行」展示（无高亮），不影响其余节点。
 */
import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ReactFlow, Background, BackgroundVariant, Controls, type Node, type Edge } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { Loader2, AlertTriangle } from 'lucide-react'
import { workflowsApi, workflowKeys } from '../../services/workflows-api'
import type { TaskDetail } from '../../services/tasks-api'
import { toXyflowNodes, deriveXyflowEdgesFromNodes } from '../../features/workflow-editor/utils/canvas-converters'
import WorkflowBaseNode from '../../features/workflow-editor/custom-nodes/WorkflowBaseNode'
import { getNodeExecState, hasTaskRejectSignal, computeSupersededEventIdxs, STATE_COLOR, type NodeExecState } from './task-flow-utils'

/** 只读节点类型注册表（复用 WorkflowBaseNode） */
const nodeTypes = { workflow: WorkflowBaseNode }

export interface TaskFlowGraphProps {
  task: TaskDetail
  theme?: 'light' | 'dark'
  /** 把 task.workflow_id（可能是 registry id wfr_...）解析为可拉 /workflows/{id} 的模板 id（wf_...） */
  resolveTemplateId?: (maybeRegistryId: string) => string
}

export function TaskFlowGraph({ task, theme = 'dark', resolveTemplateId }: TaskFlowGraphProps) {
  // task.workflow_id 存的是 registry 条目 id（wfr_...），需先解析为模板文档 id（wf_...）
  // 才能命中 GET /workflows/{id}。解析失败（无 registry 数据）时回退原值。
  const templateId = useMemo(
    () => (resolveTemplateId ? resolveTemplateId(task.workflow_id) : task.workflow_id),
    [task.workflow_id, resolveTemplateId],
  )

  const { data: wf, isLoading, isError } = useQuery({
    queryKey: workflowKeys.detail(templateId),
    queryFn: () => workflowsApi.get(templateId),
    enabled: !!templateId,
    staleTime: 60_000,
    retry: 1,
  })

  // 推导每个 node_id 的执行状态：扫描 timeline 的 node_* 事件 + checkpoint.paused_at_node
  // + variables[node_id].decision（存量 reject 事件无 node_id 的兜底）
  // + 任务级拒绝信号（存量超时事件无 node_id 的兜底）
  // rewind 废弃的旧轮 node_complete/node_failed 先剔除，否则重跑窗口内
  // 节点仍显示旧轮的「已完成 / 失败」
  const stateByNode = useMemo(() => {
    const map = new Map<string, NodeExecState>()
    const timeline = task.timeline ?? []
    const supersededIdxs = computeSupersededEventIdxs(timeline)
    const eventsByNode = new Map<string, typeof timeline>()
    timeline.forEach((evt, idx) => {
      const nodeId = typeof evt.data?.node_id === 'string' ? evt.data.node_id : undefined
      if (!nodeId || supersededIdxs.has(idx)) return
      if (!eventsByNode.has(nodeId)) eventsByNode.set(nodeId, [])
      eventsByNode.get(nodeId)!.push(evt)
    })
    const pausedNode = task.checkpoint?.paused_at_node
    const taskRejected = hasTaskRejectSignal(timeline)
    for (const [nodeId, evts] of eventsByNode) {
      const nodeVars = task.variables?.[nodeId]
      const decision =
        nodeVars && typeof nodeVars === 'object' && typeof (nodeVars as { decision?: unknown }).decision === 'string'
          ? (nodeVars as { decision: string }).decision
          : undefined
      map.set(nodeId, getNodeExecState(evts, nodeId === pausedNode, decision, taskRejected))
    }
    return map
  }, [task.timeline, task.checkpoint, task.variables])

  const { nodes, edges } = useMemo(() => {
    if (!wf?.nodes) return { nodes: [] as Node[], edges: [] as Edge[] }
    // 循环体成员不在画布渲染（与编辑器 WorkflowCanvas 同规则）：成员是
    // loop 节点的内部实现，以 loop 卡片内的步骤行（loopSteps）展示。
    // 直接平铺全量节点会把循环体拆散显示（成员游离在 loop 节点外）。
    const memberIds = new Set<string>()
    for (const n of wf.nodes) {
      if (n.type !== 'loop') continue
      for (const m of (((n.config as Record<string, unknown>).body as string[] | undefined) ?? [])) {
        memberIds.add(m)
      }
    }
    const canvasNodes = wf.nodes.filter((n) => !memberIds.has(n.node_id))
    // allNodes 传全量：loop 卡片的 loopSteps 解析需要被隐藏的体成员。
    const baseNodes = toXyflowNodes(canvasNodes, undefined, wf.nodes)
    // 叠执行态高亮：用 xyflow node.style 的 border + boxShadow，不改 WorkflowBaseNode
    const decorated = baseNodes.map((n) => {
      const state = stateByNode.get(n.id) ?? 'pending'
      const color = STATE_COLOR[state]
      const isExecuting = state === 'executing'
      return {
        ...n,
        // executing 节点边框加粗 + 阴影脉冲感；其余按状态色描边
        style: {
          border: `2px solid ${color}`,
          boxShadow: isExecuting ? `0 0 0 3px ${color}33` : undefined,
        },
        className: isExecuting ? 'task-node--executing' : undefined,
      } as Node
    })
    // 边也基于过滤集推导：体成员间的内部边不渲染（成员本就不在画布上）。
    const baseEdges = deriveXyflowEdgesFromNodes(canvasNodes)
    return { nodes: decorated, edges: baseEdges }
  }, [wf, stateByNode])

  if (isLoading) {
    return (
      <div className="h-[360px] flex items-center justify-center text-ink-dim text-xs">
        <Loader2 className="w-4 h-4 animate-spin mr-2" /> 加载流程图…
      </div>
    )
  }

  if (isError || !wf?.nodes) {
    const unresolved = !templateId
    return (
      <div className={`h-[360px] flex flex-col items-center justify-center text-xs gap-1.5 text-center px-4 ${
        theme === 'dark' ? 'text-ink-dim' : 'text-slate-500'
      }`}>
        <AlertTriangle className="w-4 h-4 text-amber-400" />
        <span>流程图加载失败</span>
        <span className="text-[11px]">
          {unresolved
            ? '无法解析工作流模板（注册表数据缺失）'
            : `工作流模板 ${templateId} 不存在或已被删除`}
        </span>
        <span className="text-[11px] text-ink-dim">请查看下方时间线了解执行进度</span>
      </div>
    )
  }

  return (
    <div className="h-[360px] w-full rounded-lg border border-line overflow-hidden bg-page relative">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        panOnDrag
        zoomOnScroll
        fitView
        fitViewOptions={{ padding: 0.2 }}
        minZoom={0.1}
        maxZoom={1.5}
        proOptions={{ hideAttribution: true }}
      >
        <Controls
          showInteractive={false}
          className={`!rounded-lg !border !shadow-sm ${theme === 'dark' ? '!border-line !bg-panel' : '!border-gray-200 !bg-white'}`}
        />
        <Background
          variant={BackgroundVariant.Dots}
          gap={20}
          size={1}
          color={theme === 'dark' ? '#27272a' : '#E2E8F0'}
        />
      </ReactFlow>

      {/* 图例：状态 → 颜色 */}
      <div className="absolute top-2 left-2 z-10 flex flex-wrap gap-x-3 gap-y-1 px-2.5 py-1.5 rounded-md bg-panel/90 border border-line backdrop-blur-sm">
        {(['executing', 'completed', 'waiting', 'failed', 'rejected', 'pending'] as NodeExecState[]).map((s) => (
          <span key={s} className="inline-flex items-center gap-1 text-[11px] text-ink-dim">
            <span className="w-2 h-2 rounded-full" style={{ backgroundColor: STATE_COLOR[s] }} />
            {LEGEND_LABEL[s]}
          </span>
        ))}
      </div>
    </div>
  )
}

const LEGEND_LABEL: Record<NodeExecState, string> = {
  executing: '执行中',
  completed: '已完成',
  waiting: '审批中',
  failed: '失败',
  rejected: '已拒绝',
  pending: '待执行',
}

export default TaskFlowGraph
