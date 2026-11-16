/**
 * WorkflowNodePalette — 左侧拖拽节点面板。
 *
 * Harness 菜单行语言：36px 行高、8px 圆角、hover 中性灰底（导航 hover
 * 不用彩色）；icon chip（8% 类型色底）与节点卡同源（node-type-configs
 * 取色自 canvas-converters.TYPE_META，单一事实源）。
 * 展开态：icon + 名称 + 右侧弱化描述（单行菜单行）。
 * 收缩态：仅 icon chip 列 + Tooltip 显示名称+描述。
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

  // 收缩态：窄列，仅 icon chip，Tooltip 补全名称/描述
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
                className="w-9 h-9 flex items-center justify-center rounded-lg cursor-grab active:cursor-grabbing hover:bg-well transition-colors"
              >
                <span
                  className="w-6 h-6 flex items-center justify-center rounded-[7px]"
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
    <div className="px-2 py-2 overflow-y-auto scrollbar-custom">
      <div className="space-y-0.5">
        {NODE_TYPE_KEYS.map((type) => {
          const cfg = NODE_TYPE_CONFIGS[type]
          return (
            <div
              key={type}
              draggable
              onDragStart={(e) => handleDragStart(e, type)}
              className="flex items-center gap-2.5 h-9 px-2 rounded-lg cursor-grab active:cursor-grabbing hover:bg-well transition-colors select-none"
              title={cfg.description}
            >
              {/* icon chip：与节点卡同源（8% 类型色底 + 彩 icon） */}
              <span
                className="shrink-0 w-6 h-6 flex items-center justify-center rounded-[7px]"
                style={{ color: cfg.color, backgroundColor: cfg.bg }}
              >
                {cfg.icon}
              </span>
              <span className="text-[12.5px] text-ink truncate">{cfg.label}</span>
              <span className="ml-auto text-[11px] text-ink-faint truncate">{cfg.description}</span>
            </div>
          )
        })}
      </div>
    </div>
  )
}
