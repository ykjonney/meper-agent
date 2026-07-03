/**
 * WorkflowNodePalette — 左侧拖拽节点面板。
 *
 * Dify 风格：列出所有可添加的节点类型，支持拖拽到 canvas。
 * 展开态：彩色图标 + 名称 + 描述卡片。
 * 收缩态：仅彩色图标（垂直），hover 出 Tooltip 显示名称+描述。
 * 外层背景/边框由父容器提供，本组件只负责内容。
 */
import type { DragEvent } from 'react'
import { Tooltip } from '../../components/ui'
import { NODE_TYPE_CONFIGS, NODE_TYPE_KEYS } from './utils/node-type-configs'

/* ─── Drag data key ─── */
export const DRAG_NODE_TYPE_KEY = 'application/x-workflow-node-type'

interface WorkflowNodePaletteProps {
  /** 收缩态：仅显示图标列 + Tooltip。 */
  collapsed?: boolean
}

export default function WorkflowNodePalette({ collapsed = false }: WorkflowNodePaletteProps) {
  const handleDragStart = (e: DragEvent<HTMLDivElement>, type: string) => {
    e.dataTransfer.setData(DRAG_NODE_TYPE_KEY, type)
    e.dataTransfer.effectAllowed = 'copy'
  }

  // 收缩态：窄列，仅图标，Tooltip 补全名称/描述
  if (collapsed) {
    return (
      <div className="flex flex-col items-center gap-1 py-2">
        {NODE_TYPE_KEYS.map((type) => {
          const cfg = NODE_TYPE_CONFIGS[type]
          return (
            <Tooltip key={type} title={`${cfg.label}：${cfg.description}`}>
              <div
                draggable
                onDragStart={(e) => handleDragStart(e, type)}
                className="w-9 h-9 flex items-center justify-center rounded-md cursor-grab active:cursor-grabbing hover:bg-[#1E5EFF]/10 transition-colors"
              >
                <span
                  className="w-7 h-7 flex items-center justify-center rounded-md text-xs"
                  style={{ color: cfg.color, backgroundColor: cfg.bg }}
                >
                  {cfg.icon}
                </span>
              </div>
            </Tooltip>
          )
        })}
      </div>
    )
  }

  return (
    <div className="p-3 overflow-y-auto scrollbar-custom">
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
