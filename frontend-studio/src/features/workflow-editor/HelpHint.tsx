/**
 * HelpHint — 帮助图标 + 悬停气泡说明。
 *
 * 配置面板的辅助文案收纳于此（不再常显），字段标题旁挂一个 ? 图标，
 * 悬停展开气泡。定位策略（区别于 ui Tooltip 的“触发器居中”）：
 * - portal 到 document.body + fixed 定位——脱离配置面板滚动容器的
 *   overflow 裁剪；
 * - 气泡左缘对齐图标、向右展开——右栏面板（w-96）里的图标若居中定位，
 *   气泡左半会溢出面板盖到画布上；
 * - 下方放不下翻到上方，整体夹在视口内。
 */
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { HelpCircle } from 'lucide-react'

interface Props {
  /** 说明文案 */
  text: string
}

const GAP = 6
const MARGIN = 8

export default function HelpHint({ text }: Props) {
  const [open, setOpen] = useState(false)
  const triggerRef = useRef<HTMLSpanElement>(null)
  const tipRef = useRef<HTMLDivElement>(null)
  const [coords, setCoords] = useState<{ top: number; left: number } | null>(null)

  const measure = useCallback(() => {
    const trig = triggerRef.current
    if (!trig) return
    const r = trig.getBoundingClientRect()
    const w = tipRef.current?.offsetWidth ?? 224
    const h = tipRef.current?.offsetHeight ?? 0
    // 左缘对齐触发器，向右展开（不居中——见文件头注释）。
    let left = r.left
    let top = r.bottom + GAP
    // 下方放不下且上方够 → 翻到上方。
    if (top + h > window.innerHeight - MARGIN && r.top - h - GAP >= MARGIN) {
      top = r.top - h - GAP
    }
    if (top < MARGIN) top = MARGIN
    left = Math.max(MARGIN, Math.min(left, window.innerWidth - w - MARGIN))
    setCoords({ top, left })
  }, [])

  // 展开后测量定位；面板滚动/视口变化时跟随重算。
  useLayoutEffect(() => {
    if (!open) return
    measure()
  }, [open, measure, text])

  useEffect(() => {
    if (!open) return
    window.addEventListener('resize', measure)
    window.addEventListener('scroll', measure, true)
    return () => {
      window.removeEventListener('resize', measure)
      window.removeEventListener('scroll', measure, true)
    }
  }, [open, measure])

  return (
    <span
      ref={triggerRef}
      className="relative inline-flex"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
    >
      <HelpCircle
        size={11}
        className="text-[#71717a] cursor-help transition-colors hover:text-[#a1a1aa]"
      />
      {open &&
        createPortal(
          <div
            ref={tipRef}
            style={
              coords
                ? { position: 'fixed', top: coords.top, left: coords.left, zIndex: 210 }
                : { position: 'fixed', left: -9999, top: -9999, visibility: 'hidden' }
            }
            className="w-56 rounded-md border border-[#3f3f46] bg-[#09090b] px-2.5 py-2 text-left text-[10px] leading-relaxed text-[#d4d4d8] shadow-lg pointer-events-none"
          >
            {text}
          </div>,
          document.body,
        )}
    </span>
  )
}
