import { DownOutlined, ShrinkOutlined } from '@ant-design/icons'
import { Button } from 'antd'
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'

import type { RecommendedGroup, RecommendedItem } from '../types'

const QUICK_ACTIONS_GAP = 6

interface QuickActionsBarProps {
  items: RecommendedItem[]
  /** 推荐项分类分组：每组收进一个组按钮，点击弹出思考云团气泡 */
  groups?: RecommendedGroup[]
  disabled: boolean
  onSelect: (item: RecommendedItem) => void
}

/** 收起态渲染序列：未分组条目在前、分组按钮在后（分组按钮各占一个测量单元）。 */
type QuickEntry =
  | { kind: 'item'; item: RecommendedItem }
  | { kind: 'group'; group: RecommendedGroup; groupIndex: number }

/**
 * 快捷操作条：默认单行展示（未分组按钮 + 分组按钮），放不下的收纳进行尾「⋯」；
 * 点击「⋯」在容器内展开为多行平铺（无弹出层，窄屏/嵌入场景不裁剪）。
 * 分组展开为悬浮在操作条上方的云团气泡（绝对定位不挤压布局），
 * 同时只展开一个分组；再点按钮 / 点外部 / ESC 收起。
 * 单行可容纳数量由隐藏量尺行按真实按钮宽度测得，随容器宽度自适应。
 */
export function QuickActionsBar({ items, groups, disabled, onSelect }: QuickActionsBarProps) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const panelRef = useRef<HTMLDivElement | null>(null)
  // antd Button 可渲染为 a/button，ref 是联合类型——只用到 offset 布局属性
  const groupBtnRefs = useRef(new Map<number, HTMLElement>())
  const ghostRefs = useRef(new Map<number, HTMLButtonElement>())
  const [expanded, setExpanded] = useState(false)
  const [openGroup, setOpenGroup] = useState<number | null>(null)
  const [cloudLeft, setCloudLeft] = useState<number | null>(null)
  const safeGroups = groups ?? []
  const [visibleCount, setVisibleCount] = useState(items.length + safeGroups.length)

  const entries: QuickEntry[] = [
    ...items.map((item): QuickEntry => ({ kind: 'item', item })),
    ...safeGroups.map((group, groupIndex): QuickEntry => ({ kind: 'group', group, groupIndex })),
  ]

  const registerGhost = useCallback((index: number) => {
    return (el: HTMLButtonElement | null) => {
      if (el) ghostRefs.current.set(index, el)
      else ghostRefs.current.delete(index)
    }
  }, [])

  const measure = useCallback(() => {
    const container = containerRef.current
    if (!container) return
    const total = entries.length
    const moreGhost = ghostRefs.current.get(-1)
    const moreWidth = moreGhost ? moreGhost.offsetWidth + QUICK_ACTIONS_GAP : 0
    const available = container.clientWidth
    let used = 0
    let fit = 0
    for (let index = 0; index < total; index++) {
      const ghost = ghostRefs.current.get(index)
      if (!ghost) break
      const width = ghost.offsetWidth
      const nextUsed = fit === 0 ? width : used + QUICK_ACTIONS_GAP + width
      // 后面还有按钮放不下时，行尾要给「⋯」预留位置
      const reserve = index < total - 1 ? moreWidth : 0
      if (nextUsed + reserve > available) break
      used = nextUsed
      fit = index + 1
    }
    setVisibleCount(fit)
  }, [items, groups])

  useEffect(() => {
    setExpanded(false)
    setOpenGroup(null)
  }, [items, groups])

  // 仅单行折叠态需要测量；「⋯」展开态按钮全部平铺，无需量尺。
  // 分组云团是绝对定位悬浮层，不影响主行折叠态——照常测量。
  useLayoutEffect(() => {
    if (!expanded) measure()
  }, [expanded, measure])

  useEffect(() => {
    const container = containerRef.current
    if (!container || typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(() => {
      if (!expanded) measure()
    })
    observer.observe(container)
    return () => observer.disconnect()
  }, [expanded, measure])

  // 云团气泡水平定位：水平中心尽量对准触发的分组按钮，clamp 防左右溢出
  useLayoutEffect(() => {
    if (openGroup === null) {
      setCloudLeft(null)
      return
    }
    const container = containerRef.current
    const panel = panelRef.current
    const btn = groupBtnRefs.current.get(openGroup)
    if (!container || !panel || !btn) return
    const anchor = btn.offsetLeft + btn.offsetWidth / 2
    const half = Math.min(panel.offsetWidth / 2, 150)
    const maxLeft = container.clientWidth - panel.offsetWidth - 4
    setCloudLeft(Math.max(4, Math.min(anchor - half, maxLeft)))
  }, [openGroup, expanded])

  // 点击操作条外部 / ESC 收起云团气泡（容器内点击由按钮自身逻辑处理）
  useEffect(() => {
    if (openGroup === null) return
    const onPointerDown = (event: MouseEvent) => {
      const target = event.target as Node | null
      if (target && containerRef.current?.contains(target)) return
      setOpenGroup(null)
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpenGroup(null)
    }
    document.addEventListener('mousedown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('mousedown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [openGroup])

  if (entries.length === 0) return null

  const collapsed = !expanded
  const hiddenCount = entries.length - visibleCount
  const openGroupData = openGroup !== null ? safeGroups[openGroup] : undefined

  /** 条目点击：发送并整体还原单行。 */
  const handleItemSelect = (item: RecommendedItem) => {
    setExpanded(false)
    setOpenGroup(null)
    onSelect(item)
  }

  /** 分组按钮点击：弹出/切换/收起云团气泡。 */
  const handleGroupToggle = (groupIndex: number) => {
    setOpenGroup((prev) => (prev === groupIndex ? null : groupIndex))
  }

  return (
    <div
      ref={containerRef}
      className="composer-quick-actions"
      data-collapsed={collapsed || undefined}
    >
      <div className="quick-actions-measure" aria-hidden>
        {entries.map((entry, index) => (
          <Button
            key={`measure:${index}`}
            className={`quick-action${entry.kind === 'group' ? ' quick-action-group' : ''}`}
            ref={registerGhost(index)}
            tabIndex={-1}
          >
            {entry.kind === 'item' ? entry.item.label : `${entry.group.title} ▾`}
          </Button>
        ))}
        <Button className="quick-action quick-action-more" ref={registerGhost(-1)} tabIndex={-1}>
          ⋯
        </Button>
      </div>
      {entries.map((entry, index) => {
        if (collapsed && index >= visibleCount) return null
        if (entry.kind === 'item') {
          return (
            <Button
              key={`${index}:${entry.item.label}`}
              className="quick-action"
              disabled={disabled}
              onClick={() => handleItemSelect(entry.item)}
            >
              {entry.item.label}
            </Button>
          )
        }
        const active = openGroup === entry.groupIndex
        return (
          <Button
            key={`group:${entry.groupIndex}:${entry.group.title}`}
            className={`quick-action quick-action-group${active ? ' active' : ''}`}
            disabled={disabled}
            aria-expanded={active}
            ref={(el) => {
              if (el) groupBtnRefs.current.set(entry.groupIndex, el)
              else groupBtnRefs.current.delete(entry.groupIndex)
            }}
            onClick={() => handleGroupToggle(entry.groupIndex)}
          >
            {entry.group.title}
            <DownOutlined className="quick-action-group-caret" />
          </Button>
        )
      })}
      {collapsed && hiddenCount > 0 ? (
        <Button
          className="quick-action quick-action-more"
          aria-label="展开更多快捷操作"
          disabled={disabled}
          onClick={() => setExpanded(true)}
        >
          ⋯
        </Button>
      ) : null}
      {!collapsed ? (
        <Button
          className="quick-action quick-action-collapse"
          aria-label="收起快捷操作"
          title="收起"
          disabled={disabled}
          onClick={() => {
            setExpanded(false)
            setOpenGroup(null)
          }}
        >
          <ShrinkOutlined />
        </Button>
      ) : null}
      {openGroupData ? (
        <div
          ref={panelRef}
          className="quick-action-group-panel"
          role="dialog"
          aria-label={openGroupData.title}
          style={cloudLeft !== null ? { left: cloudLeft } : undefined}
        >
          {openGroupData.items.length > 0 ? (
            <div className="quick-action-group-panel-items">
              {openGroupData.items.map((item, index) => (
                <Button
                  key={`${index}:${item.label}`}
                  className="quick-action"
                  disabled={disabled}
                  onClick={() => handleItemSelect(item)}
                >
                  {item.label}
                </Button>
              ))}
            </div>
          ) : (
            <div className="quick-action-group-panel-empty">该分组暂无内容</div>
          )}
        </div>
      ) : null}
    </div>
  )
}
