/** 代码编辑器（工具表单专用）——从 ToolMarketPage 拆出，行为不变。 */
import { useMemo, useRef, useState } from 'react'
import { Maximize2, Minimize2 } from 'lucide-react'
import hljs from 'highlight.js/lib/core'
import pythonLang from 'highlight.js/lib/languages/python'
import 'highlight.js/styles/github-dark.css'

hljs.registerLanguage('python', pythonLang)

const CODE_FONT = 'font-mono text-[12.5px] leading-[1.55] tracking-normal';

/** 代码编辑器：透明文字 textarea 叠 highlight.js 高亮回显层（GitHub Dark，
 * 与页面主题无关——代码区固定深色是编辑器惯例）。Tab 插入缩进；
 * 右上角可放大为中窗口编辑（Esc / 再点恢复）。 */
export function CodeEditor({ value, onChange, placeholder }: {
  value: string; onChange: (v: string) => void; placeholder: string;
}) {
  const taRef = useRef<HTMLTextAreaElement>(null);
  const preRef = useRef<HTMLPreElement>(null);
  const [focused, setFocused] = useState(false);
  const [expanded, setExpanded] = useState(false);

  const highlighted = useMemo(() => {
    try {
      return hljs.highlight(value, { language: 'python', ignoreIllegals: true }).value;
    } catch {
      return '';
    }
  }, [value]);

  const editorBody = (
    <>
      {/* 放大 / 恢复 */}
      <button onClick={() => setExpanded(!expanded)}
        title={expanded ? '恢复编辑区（Esc）' : '放大编辑'}
        className="absolute top-1.5 right-1.5 z-20 p-1 rounded text-[#8b949e] hover:text-white hover:bg-[#30363d] cursor-pointer">
        {expanded ? <Minimize2 size={13} /> : <Maximize2 size={13} />}
      </button>
      {/* 高亮回显层（不响应鼠标，仅渲染） */}
      <pre ref={preRef} aria-hidden
        className={`absolute inset-0 m-0 p-3 overflow-auto pointer-events-none whitespace-pre-wrap break-words text-[#c9d1d9] ${CODE_FONT}`}>
        <code className="hljs language-python" dangerouslySetInnerHTML={{ __html: highlighted || '&nbsp;' }} />
      </pre>
      {/* 输入层：文字透明只留光标 */}
      <textarea ref={taRef} value={value} onChange={(e) => onChange(e.target.value)}
        onFocus={() => setFocused(true)} onBlur={() => setFocused(false)}
        onScroll={() => { if (preRef.current && taRef.current) preRef.current.scrollTop = taRef.current.scrollTop; }}
        onKeyDown={(e) => {
          if (e.key === 'Escape' && expanded) {
            e.preventDefault();
            setExpanded(false);
            return;
          }
          if (e.key !== 'Tab') return;
          e.preventDefault();
          const ta = e.currentTarget;
          const { selectionStart: s, selectionEnd: en } = ta;
          const next = value.slice(0, s) + '    ' + value.slice(en);
          onChange(next);
          requestAnimationFrame(() => ta.setSelectionRange(s + 4, s + 4));
        }}
        spellCheck={false}
        placeholder={placeholder}
        className={`code-editor-input relative z-10 w-full p-3 bg-transparent text-transparent caret-white outline-none whitespace-pre-wrap break-words placeholder:text-[#484f58] ${
          expanded ? 'flex-1 min-h-0' : 'min-h-[150px] resize-y'
        } ${CODE_FONT}`} />
    </>
  );

  if (expanded) {
    // 放大态：居中大窗口（约 2/3 视口），不是全屏
    return (
      <div className="fixed inset-0 z-[60] flex items-center justify-center">
        <div className="relative flex flex-col w-[62vw] max-w-[860px] h-[62vh] rounded-xl border border-[#30363d] bg-[#0d1117] overflow-hidden shadow-2xl">
          {editorBody}
        </div>
      </div>
    );
  }
  return (
    <div className={`relative rounded-lg border overflow-hidden bg-[#0d1117] transition-colors ${
      focused ? 'border-blue-600' : 'border-[#30363d]'
    }`}>
      {editorBody}
    </div>
  );
}

/** 示例：天气查询（同一需求两种实现，一键填完全部四步表单） **/

