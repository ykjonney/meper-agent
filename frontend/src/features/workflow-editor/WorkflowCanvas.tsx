/**
 * WorkflowCanvas — 画布组件。
 *
 * 使用 @xyflow/react 的 ReactFlow，包含：
 * - 自定义节点注册（WorkflowBaseNode）
 * - 拖拽添加节点（DnD）
 * - Minimap + Controls
 * - 选中事件回调
 * - 拖线操作 → 更新 source 节点的 config.next_nodes
 * - 点击边高亮 + Delete/Backspace 删除
 *
 * 注意：边不再作为独立状态管理，而是从节点的 next_nodes 推导而来。
 */
import { useCallback, useRef, useState, useEffect, useMemo } from 'react'
import {
  ReactFlow,
  MiniMap,
  Controls,
  Background,
  BackgroundVariant,
  applyNodeChanges,
  useOnSelectionChange,
  type OnNodesChange,
  type OnEdgesChange,
  type OnConnect,
  type Node,
  type Edge,
  type Connection,
  type NodeChange,
  type EdgeChange,
  type ReactFlowInstance,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'

import WorkflowBaseNode from './custom-nodes/WorkflowBaseNode'
import { DRAG_NODE_TYPE_KEY } from './WorkflowNodePalette'
import { toXyflowNodes, type WorkflowNodeData, deriveXyflowEdgesFromNodes, syncEdgeChangesToNodes } from './utils/canvas-converters'
import { generateNodeId, getDefaultNodeConfig } from './utils/node-defaults'
import { NODE_TYPE_CONFIGS } from './utils/node-type-configs'
import type { WorkflowNode } from '../../services/workflows-api'

/* ─── 内部组件：在 ReactFlow 内部监听节点选中事件 ── */
function SelectionHandler({ workflowNodes, onSelectNode }: {
  workflowNodes: WorkflowNode[]
  onSelectNode: (node: WorkflowNode | null) => void
}) {
  const prevSelectedRef = useRef<string | null>(null)

  useOnSelectionChange({
    onChange: ({ nodes: selectedNodes }) => {
      // 节点选中
      if (selectedNodes.length > 0) {
        const xyNode = selectedNodes[0]
        prevSelectedRef.current = xyNode.id
        const found = workflowNodes.find((n) => n.node_id === xyNode.id)
        if (found) {
          onSelectNode(found)
        }
      } else {
        const stillExists = prevSelectedRef.current
          ? workflowNodes.some((n) => n.node_id === prevSelectedRef.current)
          : false
        if (!stillExists) {
          prevSelectedRef.current = null
          onSelectNode(null)
        }
      }
    },
  })
  return null
}

/* ─── 自定义节点类型注册表 ── */
const nodeTypes = {
  workflow: WorkflowBaseNode,
}

/* ─── Props ─── */
export interface WorkflowCanvasProps {
  workflowNodes: WorkflowNode[]
  selectedNodeId: string | null
  onNodesChange: (nodes: WorkflowNode[]) => void
  onSelectNode: (node: WorkflowNode | null) => void
}

export default function WorkflowCanvas({
  workflowNodes,
  selectedNodeId,
  onNodesChange: onWorkflowNodesChange,
  onSelectNode,
}: WorkflowCanvasProps) {
  const rfInstance = useRef<ReactFlowInstance | null>(null)

  /* ─── xyflow nodes: 从 workflowNodes 同步 ─── */
  const [xyflowNodes, setXyflowNodes] = useState<Node[]>(
    () => toXyflowNodes(workflowNodes, selectedNodeId) as Node[],
  )

  // 同步外部 workflowNodes 到内部 xyflowNodes
  const prevSyncHashRef = useRef('')
  useEffect(() => {
    const hash = workflowNodes
      .map((n) => `${n.node_id}:${n.label}:${JSON.stringify(n.config)}`)
      .join('|')
    if (hash !== prevSyncHashRef.current) {
      prevSyncHashRef.current = hash
      const newNodes = toXyflowNodes(workflowNodes, selectedNodeId) as Node[]
      setXyflowNodes((prev) =>
        newNodes.map((nn) => {
          const existing = prev.find((p) => p.id === nn.id)
          return existing ? { ...nn, position: existing.position } : nn
        }),
      )
    }
  }, [workflowNodes, selectedNodeId])

  /* ─── 追踪选中的边（受控模式下 React Flow 不会回写 selected 属性） ─── */
  const [selectedEdgeIds, setSelectedEdgeIds] = useState<Set<string>>(new Set())

  /* ─── 边点击 → 手动追踪选中状态 ─── */
  const handleEdgeClick = useCallback(
    (_: React.MouseEvent, edge: Edge) => {
      setSelectedEdgeIds(new Set([edge.id]))
    },
    [],
  )

  /* ─── 面板/节点点击 → 清除边选中 ─── */
  const handlePaneClick = useCallback(() => {
    onSelectNode(null)
    setSelectedEdgeIds(new Set())
  }, [onSelectNode])

  /* ─── xyflow edges: 从 workflowNodes 的 config 推导，注入 selected 样式 ─── */
  const xyflowEdges = useMemo<Edge[]>(
    () =>
      deriveXyflowEdgesFromNodes(workflowNodes).map((e) => {
        const isSelected = selectedEdgeIds.has(e.id)
        const isCondition = e.className?.includes('workflow-edge--condition')
        return {
          ...e,
          selected: isSelected,
          style: isSelected
            ? { stroke: '#3B82F6', strokeWidth: 2.5 }
            : isCondition
              ? { stroke: '#8B5CF6', strokeWidth: 2 }
              : { stroke: '#94A3B8', strokeWidth: 1.5 },
        }
      }),
    [workflowNodes, selectedEdgeIds],
  )

  /* ─── 内部节点位置变更（包括拖拽） ─── */
  // 忽略 remove 类型：节点删除只通过配置面板的「删除节点」按钮（带确认弹窗）
  const handleNodesChange: OnNodesChange = useCallback(
    (changes: NodeChange[]) => {
      const safeChanges = changes.filter((c) => c.type !== 'remove')
      if (safeChanges.length > 0) {
        setXyflowNodes((prev) => applyNodeChanges(safeChanges, prev) as Node[])
      }
    },
    [],
  )

  /* ── 拖拽结束 → 同步位置回 workflowNodes ─── */
  const handleNodeDragStop = useCallback(
    (_: React.MouseEvent | React.TouchEvent, node: Node) => {
      const updatedNodes = workflowNodes.map((n) =>
        n.node_id === node.id
          ? { ...n, position: { x: Math.round(node.position.x), y: Math.round(node.position.y) } }
          : n,
      )
      onWorkflowNodesChange(updatedNodes)
    },
    [workflowNodes, onWorkflowNodesChange],
  )

  /* ─── 拖线连接 → 更新 source 节点的 config.next_nodes ─── */
  const handleConnect: OnConnect = useCallback(
    (connection: Connection) => {
      if (!connection.source || !connection.target) return
      const updatedNodes = syncEdgeChangesToNodes(
        'add',
        workflowNodes,
        connection.source,
        connection.target,
      )
      onWorkflowNodesChange(updatedNodes)
    },
    [workflowNodes, onWorkflowNodesChange],
  )

  /* ─── 节点点击 ─── */
  const handleNodeClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      const foundNode = workflowNodes.find((n) => n.node_id === node.id)
      if (foundNode) {
        onSelectNode(foundNode)
      }
      // 点击节点时清除边选中
      setSelectedEdgeIds(new Set())
    },
    [workflowNodes, onSelectNode],
  )

  /* ── 拖拽添加节点 ─── */
  const handleInit = useCallback((instance: ReactFlowInstance) => {
    rfInstance.current = instance
  }, [])

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.dataTransfer.dropEffect = 'copy'
  }, [])

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault()
      const type = e.dataTransfer.getData(DRAG_NODE_TYPE_KEY)
      if (!type || !NODE_TYPE_CONFIGS[type]) return

      const instance = rfInstance.current
      if (!instance) return

      const position = instance.screenToFlowPosition({
        x: e.clientX,
        y: e.clientY,
      })

      const newNode: WorkflowNode = {
        node_id: generateNodeId(),
        type,
        label: NODE_TYPE_CONFIGS[type].label,
        config: getDefaultNodeConfig(type),
        position: { x: Math.round(position.x), y: Math.round(position.y) },
      }

      const updatedNodes = [...workflowNodes, newNode]
      onWorkflowNodesChange(updatedNodes)
      onSelectNode(newNode)
    },
    [workflowNodes, onWorkflowNodesChange, onSelectNode],
  )

  /* ─── 删除边 → 从 source 节点的 next_nodes 中移除 ─── */
  // 选中边后按 Delete/Backspace → 同步回 source 节点
  const handleEdgesChange: OnEdgesChange = useCallback(
    (changes: EdgeChange[]) => {
      let updatedNodes = workflowNodes
      let changed = false
      for (const change of changes) {
        if (change.type === 'remove') {
          const edge = xyflowEdges.find((e) => e.id === change.id)
          if (edge?.source && edge?.target) {
            updatedNodes = syncEdgeChangesToNodes('remove', updatedNodes, edge.source, edge.target)
            changed = true
          }
        }
      }
      if (changed) {
        onWorkflowNodesChange(updatedNodes)
      }
    },
    [workflowNodes, xyflowEdges, onWorkflowNodesChange],
  )

  /* ─── 键盘删除边（受控模式下 deleteKeyCode 不可靠，手动监听） ─── */
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key !== 'Delete' && e.key !== 'Backspace') return
      // 如果焦点在输入框内，不拦截
      const tag = (e.target as HTMLElement)?.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || (e.target as HTMLElement)?.isContentEditable) return
      if (selectedEdgeIds.size === 0) return

      e.preventDefault()
      let updatedNodes = workflowNodes
      for (const edgeId of selectedEdgeIds) {
        const edge = xyflowEdges.find((e) => e.id === edgeId)
        if (edge?.source && edge?.target) {
          updatedNodes = syncEdgeChangesToNodes('remove', updatedNodes, edge.source, edge.target)
        }
      }
      onWorkflowNodesChange(updatedNodes)
      setSelectedEdgeIds(new Set())
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [selectedEdgeIds, workflowNodes, xyflowEdges, onWorkflowNodesChange])

  return (
    <div className="w-full h-full">
      <ReactFlow
        nodes={xyflowNodes}
        edges={xyflowEdges}
        onNodesChange={handleNodesChange}
        onEdgesChange={handleEdgesChange}
        onConnect={handleConnect}
        onNodeClick={handleNodeClick}
        onEdgeClick={handleEdgeClick}
        onPaneClick={handlePaneClick}
        onNodeDragStop={handleNodeDragStop}
        onInit={handleInit}
        onDragOver={handleDragOver}
        onDrop={handleDrop}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        snapToGrid
        snapGrid={[20, 20]}
        minZoom={0.1}
        maxZoom={2}
        selectNodesOnDrag={false}
        multiSelectionKeyCode={null}
      >
        <SelectionHandler workflowNodes={workflowNodes} onSelectNode={onSelectNode} />
        <Controls
          showInteractive={false}
          className="!rounded-lg !border !border-gray-200 !shadow-sm"
        />
        <MiniMap
          nodeColor={(n) => {
            const meta = (n.data as unknown as WorkflowNodeData)
            return meta?.typeColor ?? '#94A3B8'
          }}
          maskColor="rgba(0,0,0,0.08)"
          className="!rounded-lg !border !border-gray-200"
          style={{ width: 150, height: 100 }}
        />
        <Background
          variant={BackgroundVariant.Dots}
          gap={20}
          size={1}
          color="#E2E8F0"
        />
      </ReactFlow>
    </div>
  )
}
