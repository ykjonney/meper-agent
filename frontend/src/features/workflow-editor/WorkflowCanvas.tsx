/**
 * WorkflowCanvas — 画布组件。
 *
 * 使用 @xyflow/react 的 ReactFlow，包含：
 * - 自定义节点注册（WorkflowBaseNode）
 * - 拖拽添加节点（DnD）
 * - Minimap + Controls
 * - 选中事件回调
 * - 拖线操作 → 更新 source 节点的 config.next_nodes
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
  type OnConnect,
  type Node,
  type Edge,
  type Connection,
  type NodeChange,
  type ReactFlowInstance,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'

import WorkflowBaseNode from './custom-nodes/WorkflowBaseNode'
import { DRAG_NODE_TYPE_KEY } from './WorkflowNodePalette'
import { toXyflowNodes, type WorkflowNodeData, deriveXyflowEdgesFromNodes, syncEdgeChangesToNodes } from './utils/canvas-converters'
import { generateNodeId, getDefaultNodeConfig } from './utils/node-defaults'
import { NODE_TYPE_CONFIGS } from './utils/node-type-configs'
import type { WorkflowNode } from '../../services/workflows-api'

/* ─── 内部组件：在 ReactFlow 内部监听选中事件 ─── */
function SelectionHandler({ workflowNodes, onSelectNode }: {
  workflowNodes: WorkflowNode[]
  onSelectNode: (node: WorkflowNode | null) => void
}) {
  // 追踪上次选中，避免 sync effect 替换节点引用后 React Flow 清空选中
  // 触发误报 onSelectNode(null) 导致配置面板消失
  const prevSelectedRef = useRef<string | null>(null)

  useOnSelectionChange({
    onChange: ({ nodes: selectedNodes }) => {
      if (selectedNodes.length > 0) {
        const xyNode = selectedNodes[0]
        prevSelectedRef.current = xyNode.id
        const found = workflowNodes.find((n) => n.node_id === xyNode.id)
        if (found) {
          onSelectNode(found)
        }
      } else {
        // React Flow 在节点引用被替换（sync effect）时会短暂清空选中，
        // 如果 workflowNodes 中仍存在上次选中的节点，说明是同步引起的，忽略
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

/* ─── 自定义节点类型注册表 ─── */
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
  // 使用 config 内容 hash 而非节点数量，确保配置变更（如添加 output_variables）后画布同步更新
  // 注意：保留现有 xyflow 节点的拖拽位置，不覆盖
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
          // 保留 xyflow 中的拖拽位置，仅更新数据
          return existing ? { ...nn, position: existing.position } : nn
        }),
      )
    }
  }, [workflowNodes, selectedNodeId])

  /* ─── xyflow edges: 从 workflowNodes 的 config 推导 ─── */
  const xyflowEdges = useMemo<Edge[]>(
    () => deriveXyflowEdgesFromNodes(workflowNodes),
    [workflowNodes],
  )

  /* ─── 内部节点位置变更（包括拖拽） ─── */
  const handleNodesChange: OnNodesChange = useCallback(
    (changes: NodeChange[]) => {
      setXyflowNodes((prev) => applyNodeChanges(changes, prev) as Node[])
    },
    [],
  )

  /* ─── 拖拽结束 → 同步位置回 workflowNodes ─── */
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
      // 通过 syncEdgeChangesToNodes 更新 source 节点
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
    },
    [workflowNodes, onSelectNode],
  )

  const handlePaneClick = useCallback(() => {
    onSelectNode(null)
  }, [onSelectNode])

  /* ─── 拖拽添加节点 ─── */
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

      // 用 screenToFlowPosition 精确转换屏幕坐标 → 画布坐标
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
  // 这里不使用 onEdgesChange，而是在 xyflow edges 的删除操作中拦截
  // 删除边的操作通过节点配置面板完成

  return (
    <div className="w-full h-full">
      <ReactFlow
        nodes={xyflowNodes}
        edges={xyflowEdges}
        onNodesChange={handleNodesChange}
        onConnect={handleConnect}
        onNodeClick={handleNodeClick}
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
