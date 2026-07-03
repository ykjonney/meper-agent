/**
 * VariableChipEditor — contentEditable 变量编辑器。
 *
 * 变量在编辑器内显示为带样式的 chip（contenteditable=false 的 span），
 * 浏览器原生支持 Backspace 整体删除一个 chip。对外 value 仍序列化为
 * `{{nodeId.field}}` 字符串，与后端 executor / workflow-validator 契约一致。
 *
 * 非受控 DOM：React 不在每次 input 时重写 innerHTML（避免打断中文 IME），
 * 仅在外部 value 变化（切节点 / 撤销）时重建 DOM。chip 由命令式 DOM 构建，
 * 样式集中在 index.css 的 .var-chip（不依赖 Tailwind 扫描动态字符串）。
 */
import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useLayoutEffect,
  useRef,
  type ClipboardEvent as ReactClipboardEvent,
  type CSSProperties,
} from 'react'

const VARIABLE_REGEX = /\{\{(\w+)\.(\w+)\}\}/g
const ZERO_WIDTH_SPACE = '​'

/** 单个变量的显示元信息，由父组件从上游变量池构建。 */
export interface VariableChipMeta {
  label: string
  color: string
  icon: string
  /** 短节点号（用于 chip 文案「label · xxxx」），可选 */
  short?: string
}

export interface VariableChipEditorHandle {
  /** 在当前光标处插入一个变量 chip；光标不在编辑器内时追加到末尾。 */
  insertAtCursor: (nodeId: string, field: string) => void
  focus: () => void
}

export interface VariableChipEditorProps {
  /** `文本 + {{nodeId.field}}` 字符串 */
  value: string
  onChange: (value: string) => void
  /** key: `${nodeId}.${field}` → 显示元信息 */
  varMeta: Map<string, VariableChipMeta>
  placeholder?: string
  /** true=多行（可换行、按 minRows 设最小高度）；false=单行 */
  multiline?: boolean
  /** 多行时的最小行数 */
  minRows?: number
  className?: string
}

/* ─── 命令式 DOM 构建 ─── */

function createChipElement(
  nodeId: string,
  field: string,
  meta: VariableChipMeta | undefined,
): HTMLSpanElement {
  const chip = document.createElement('span')
  chip.className = 'var-chip'
  chip.contentEditable = 'false'
  chip.setAttribute('data-node-id', nodeId)
  chip.setAttribute('data-field', field)
  chip.setAttribute('spellcheck', 'false')

  const icon = document.createElement('span')
  icon.className = 'var-chip-icon'
  icon.style.backgroundColor = meta?.color ?? '#64748B'
  icon.textContent = meta?.icon ?? '?'
  chip.appendChild(icon)

  const label = document.createElement('span')
  label.className = 'var-chip-label'
  label.textContent = meta?.label ?? `${nodeId}.${field}`
  chip.appendChild(label)

  if (meta?.short) {
    const short = document.createElement('span')
    short.className = 'var-chip-short'
    short.textContent = `· ${meta.short}`
    chip.appendChild(short)
  }
  return chip
}

/** 把含 \n 的文本拆成「文本节点 + <br>」序列追加到 root。 */
function appendTextWithBreaks(root: HTMLElement, text: string) {
  const parts = text.split('\n')
  parts.forEach((part, i) => {
    if (i > 0) root.appendChild(document.createElement('br'))
    if (part) root.appendChild(document.createTextNode(part))
  })
}

/** 该 Range 的起点是否仍在 el 子树内（过滤 editor 重建后失效的旧 Range）。 */
function rangeConnectedTo(range: Range, el: HTMLElement): boolean {
  let node: Node | null = range.startContainer
  while (node) {
    if (node === el) return true
    node = node.parentNode
  }
  return false
}

/** 序列化 DOM → `文本{{nodeId.field}}` 字符串（兼容 <br> 与 <div>/<p> 换行）。 */
function serialize(root: HTMLElement): string {
  let out = ''
  const walk = (parent: Node) => {
    parent.childNodes.forEach((node) => {
      if (node.nodeType === Node.TEXT_NODE) {
        out += (node.textContent ?? '').replace(new RegExp(ZERO_WIDTH_SPACE, 'g'), '')
      } else if (node.nodeType === Node.ELEMENT_NODE) {
        const el = node as HTMLElement
        if (el.classList.contains('var-chip')) {
          const n = el.getAttribute('data-node-id') ?? ''
          const f = el.getAttribute('data-field') ?? ''
          out += `{{${n}.${f}}}`
        } else if (el.tagName === 'BR') {
          out += '\n'
        } else if (el.tagName === 'DIV' || el.tagName === 'P') {
          if (out.length > 0 && !out.endsWith('\n')) out += '\n'
          walk(el)
        } else {
          walk(el)
        }
      }
    })
  }
  walk(root)
  return out
}

/** 反序列化：把字符串渲染进 root，变量段查 varMeta 渲染 chip，未知变量 fallback 显示 nodeId.field。 */
function renderValue(
  root: HTMLElement,
  value: string,
  varMeta: Map<string, VariableChipMeta>,
) {
  root.textContent = ''
  VARIABLE_REGEX.lastIndex = 0
  let last = 0
  let m: RegExpExecArray | null
  while ((m = VARIABLE_REGEX.exec(value)) !== null) {
    if (m.index > last) appendTextWithBreaks(root, value.slice(last, m.index))
    const [, nodeId, field] = m
    root.appendChild(createChipElement(nodeId, field, varMeta.get(`${nodeId}.${field}`)))
    last = VARIABLE_REGEX.lastIndex
  }
  if (last < value.length) appendTextWithBreaks(root, value.slice(last))
}

/* ─── 组件 ─── */

const VariableChipEditor = forwardRef<
  VariableChipEditorHandle,
  VariableChipEditorProps
>(function VariableChipEditor(
  {
    value,
    onChange,
    varMeta,
    placeholder = '',
    multiline = true,
    minRows = 3,
    className = '',
  },
  ref,
) {
  const editorRef = useRef<HTMLDivElement>(null)
  // 初始为 null：首次挂载时强制渲染（否则 value===初始值 会跳过 DOM 构建）
  const lastSerializedRef = useRef<string | null>(null)
  // 记录 editor 内最后的光标 Range。点击外部「选择变量」按钮时 editor 失焦，
  // 此时 window.getSelection() 不再可靠，插入前用保存的 Range 恢复光标位置。
  const lastRangeRef = useRef<Range | null>(null)
  const composingRef = useRef(false)

  /* 初始化 + 外部 value 变化时重建 DOM（用户输入引起的等值变化不重建） */
  useLayoutEffect(() => {
    const el = editorRef.current
    if (!el) return
    if (value !== lastSerializedRef.current) {
      renderValue(el, value, varMeta)
      lastSerializedRef.current = value
    }
  }, [value, varMeta])

  /* 实时保存 editor 内的光标位置，供失焦后的插入操作恢复 */
  useEffect(() => {
    const handler = () => {
      const el = editorRef.current
      const sel = window.getSelection()
      if (el && sel && sel.rangeCount && el.contains(sel.anchorNode)) {
        lastRangeRef.current = sel.getRangeAt(0).cloneRange()
      }
    }
    document.addEventListener('selectionchange', handler)
    return () => document.removeEventListener('selectionchange', handler)
  }, [])

  /* 读取 DOM → 序列化 → onChange；空内容清理残留 <br> 以触发 placeholder */
  const syncChange = useCallback(() => {
    const el = editorRef.current
    if (!el) return
    const serialized = serialize(el)
    if (serialized === '' && el.childNodes.length > 0) {
      el.textContent = ''
    }
    lastSerializedRef.current = serialized
    onChange(serialized)
  }, [onChange])

  const handleInput = useCallback(() => {
    if (composingRef.current) return
    syncChange()
  }, [syncChange])

  const handleCompositionStart = useCallback(() => {
    composingRef.current = true
  }, [])
  const handleCompositionEnd = useCallback(() => {
    composingRef.current = false
    syncChange()
  }, [syncChange])

  /* 粘贴：强制纯文本（\n → <br>），防富文本污染编辑器 */
  const handlePaste = useCallback(
    (e: ReactClipboardEvent<HTMLDivElement>) => {
      e.preventDefault()
      const text = e.clipboardData.getData('text/plain')
      const el = editorRef.current
      if (!el) return
      const sel = window.getSelection()
      if (!sel || !sel.rangeCount || !el.contains(sel.anchorNode)) {
        appendTextWithBreaks(el, text)
      } else {
        const range = sel.getRangeAt(0)
        range.deleteContents()
        const frag = document.createDocumentFragment()
        text.split('\n').forEach((part, i) => {
          if (i > 0) frag.appendChild(document.createElement('br'))
          if (part) frag.appendChild(document.createTextNode(part))
        })
        range.insertNode(frag)
        const lastNode = frag.lastChild
        if (lastNode) {
          range.setStartAfter(lastNode)
          range.collapse(true)
          sel.removeAllRanges()
          sel.addRange(range)
        }
      }
      syncChange()
    },
    [syncChange],
  )

  /* 暴露命令式 API 给父组件（变量选择面板插入用） */
  useImperativeHandle(
    ref,
    (): VariableChipEditorHandle => ({
      insertAtCursor: (nodeId: string, field: string) => {
        const el = editorRef.current
        if (!el) return
        const meta = varMeta.get(`${nodeId}.${field}`)
        const chip = createChipElement(nodeId, field, meta)
        const zws = document.createTextNode(ZERO_WIDTH_SPACE)
        const sel = window.getSelection()

        // 优先用失焦前保存的光标；其次用当前选区；都没有则追加末尾。
        // 点击外部「选择变量」时 editor 已失焦，必须靠 saved range 恢复位置。
        const saved = lastRangeRef.current
        let range: Range | null = null
        if (saved && rangeConnectedTo(saved, el)) range = saved
        else if (sel && sel.rangeCount && el.contains(sel.anchorNode)) {
          range = sel.getRangeAt(0)
        }

        el.focus()
        if (!range || !sel) {
          el.appendChild(chip)
          el.appendChild(zws)
        } else {
          sel.removeAllRanges()
          sel.addRange(range)
          range.deleteContents()
          range.insertNode(zws)
          range.insertNode(chip)
          range.setStartAfter(zws)
          range.collapse(true)
          lastRangeRef.current = range.cloneRange()
          sel.removeAllRanges()
          sel.addRange(range)
        }
        syncChange()
      },
      focus: () => editorRef.current?.focus(),
    }),
    [varMeta, syncChange],
  )

  const baseCls =
    'var-editor w-full rounded-md border border-[#27272a] bg-[#121214] text-[#fafafa] ' +
    'px-2.5 py-1.5 text-xs leading-relaxed font-mono ' +
    'focus:outline-none focus:border-[#1E5EFF] focus:ring-1 focus:ring-[#1E5EFF]/30 transition-colors ' +
    'scrollbar-custom ' +
    className

  const sizeStyle: CSSProperties = multiline
    ? { minHeight: `calc(${minRows} * 1.625em + 0.75rem)` }
    : { minHeight: '2rem', whiteSpace: 'nowrap', overflowX: 'auto' }

  return (
    <div
      ref={editorRef}
      className={baseCls}
      contentEditable
      suppressContentEditableWarning
      spellCheck={false}
      data-placeholder={placeholder}
      style={sizeStyle}
      onInput={handleInput}
      onCompositionStart={handleCompositionStart}
      onCompositionEnd={handleCompositionEnd}
      onPaste={handlePaste}
    />
  )
})

export default VariableChipEditor
