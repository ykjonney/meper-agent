/**
 * WorkflowNodePalette — 左侧拖拽节点面板。
 *
 * Dify 风格：列出所有可添加的节点类型，支持拖拽到 canvas。
 * 每个节点显示为带彩色图标的卡片。
 */
import type { DragEvent } from 'react'
import { NODE_TYPE_CONFIGS, NODE_TYPE_KEYS } from './utils/node-type-configs'

/* ─── Drag data key ─── */
export const DRAG_NODE_TYPE_KEY = 'application/x-workflow-node-type'

export default function WorkflowNodePalette() {
  const handleDragStart = (e: DragEvent<HTMLDivElement>, type: string) => {
    e.dataTransfer.setData(DRAG_NODE_TYPE_KEY, type)
    e.dataTransfer.effectAllowed = 'copy'
  }

  return (
    <div className="bg-[#18181b] border-r border-[#27272a] p-3 overflow-y-auto">
      <div className="text-xs font-medium text-[#fafafa] mb-3">节点类型</div>
      <div className="space-y-1.5">
        {NODE_TYPE_KEYS.map((type) => {
          const cfg = NODE_TYPE_CONFIGS[type]
          return (
            <div
              key={type}
              draggable
              onDragStart={(e) => handleDragStart(e, type)}
              className="flex items-center gap-2.5 px-2.5 py-2 rounded-lg border border-[#27272a]/60 bg-[#121214] cursor-grab active:cursor-grabbing hover:border-[#1E5EFF] hover:bg-[#1E5EFF]/10 transition-all select-none"
              title={cfg.description}
            >
              {/* 彩色图标 */}
              <span
                className="w-7 h-7 flex items-center justify-center rounded-md text-xs"
                style={{ color: cfg.color, backgroundColor: cfg.bg }}
              >
                {cfg.icon}
              </span>
              <div className="min-w-0">
                <div className="text-xs font-medium text-[#fafafa]">{cfg.label}</div>
                <div className="text-[10px] text-[#71717a] truncate">{cfg.description}</div>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
