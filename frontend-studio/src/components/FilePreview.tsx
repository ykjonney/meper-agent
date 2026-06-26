/**
 * FilePreview — 会话/任务文件的智能预览渲染器。
 *
 * 按文件名扩展名 + mime 智能分流渲染：
 * - .md / .markdown → <Markdown> 渲染（标题/列表/表格/代码高亮）
 * - .html / .htm    → iframe sandbox 沙箱渲染，弹窗内「渲染 / 源码」可切换
 * - .json           → JSON.parse 美化 + 语法高亮（失败回退源码）
 * - 图片            → <img> 直显
 * - .txt / .csv / .log 等文本 → <pre> 纯文本
 * - 其它二进制      → 提示下载
 *
 * 由父组件传入已加载的 text/imageData，本组件不负责拉取（保持单一职责）。
 */
import { useState, useMemo } from 'react';
import { FileWarning, Code2, Eye } from 'lucide-react';
import { Markdown } from './Markdown';

export type PreviewKind = 'markdown' | 'html' | 'json' | 'image' | 'text' | 'binary';

export interface FilePreviewProps {
  /** 文件名（含扩展名），用于判断渲染类型 */
  filename: string;
  /** mime 类型（可选，作为辅助判断） */
  mime?: string;
  /** 文本类内容（md/html/json/text）。图片类为 undefined。 */
  text?: string;
  /** 图片 dataURL / blobURL */
  imageUrl?: string;
}

/** 按文件名 + mime 判定渲染类型 */
export function detectPreviewKind(filename: string, mime?: string): PreviewKind {
  const name = filename.toLowerCase();
  const ext = name.slice(name.lastIndexOf('.') + 1);
  if (ext === 'md' || ext === 'markdown') return 'markdown';
  if (ext === 'html' || ext === 'htm') return 'html';
  if (ext === 'json' || mime === 'application/json') return 'json';
  if (mime?.startsWith('image/') || ['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'bmp'].includes(ext)) return 'image';
  if (mime?.startsWith('text/') || ['txt', 'csv', 'log', 'tsv', 'yaml', 'yml', 'ini', 'conf'].includes(ext)) return 'text';
  return 'binary';
}

export function FilePreview({ filename, mime, text, imageUrl }: FilePreviewProps) {
  const kind = detectPreviewKind(filename, mime);

  // 可滚动类型（md/json/text）：外层 overflow-auto 滚动，内容自然撑高
  const scrollCls = 'overflow-auto flex-1 min-h-0 scrollbar-custom';

  switch (kind) {
    case 'markdown':
      return (
        <div className={scrollCls}>
          <Markdown content={text ?? ''} />
        </div>
      );
    case 'html':
      // html 需填满弹窗高度（iframe 自适应），不用滚动容器
      return <HtmlPreview source={text ?? ''} />;
    case 'json':
      return (
        <div className={scrollCls}>
          <JsonPreview raw={text ?? ''} />
        </div>
      );
    case 'image':
      return imageUrl ? (
        <div className={scrollCls}>
          <img src={imageUrl} alt={filename} className="max-w-full h-auto rounded-md mx-auto" />
        </div>
      ) : null;
    case 'text':
      return (
        <pre className={`text-[11px] text-[#d4d4d8] whitespace-pre-wrap font-mono leading-relaxed ${scrollCls}`}>
          {text}
        </pre>
      );
    case 'binary':
    default:
      return (
        <div className="flex flex-col items-center justify-center py-12 text-[#71717a] gap-2">
          <FileWarning className="w-6 h-6" />
          <span className="text-xs">该文件类型不支持预览，请下载查看</span>
        </div>
      );
  }
}

/* ─── HTML 预览：渲染 / 源码 切换 ─── */

function HtmlPreview({ source }: { source: string }) {
  const [mode, setMode] = useState<'render' | 'source'>('render');
  return (
    <div className="flex-1 flex flex-col gap-2 min-h-0">
      <div className="flex items-center gap-1 p-0.5 rounded-md bg-[#121214] border border-[#27272a] self-start shrink-0">
        <button
          onClick={() => setMode('render')}
          className={`px-2 py-1 rounded text-[11px] font-semibold transition cursor-pointer flex items-center gap-1 ${
            mode === 'render' ? 'bg-[#1E5EFF] text-white' : 'text-[#71717a] hover:text-white'
          }`}
        >
          <Eye className="w-3 h-3" /> 渲染
        </button>
        <button
          onClick={() => setMode('source')}
          className={`px-2 py-1 rounded text-[11px] font-semibold transition cursor-pointer flex items-center gap-1 ${
            mode === 'source' ? 'bg-[#1E5EFF] text-white' : 'text-[#71717a] hover:text-white'
          }`}
        >
          <Code2 className="w-3 h-3" /> 源码
        </button>
      </div>
      {mode === 'render' ? (
        // 用相对定位容器 + iframe 绝对定位填满，使 iframe 高度自适应弹窗（跟随拖拽缩放），
        // 不依赖外层 flex 高度链，对任意父容器都稳定生效。
        <div className="relative flex-1 min-h-[240px] rounded-md border border-[#27272a] bg-white overflow-hidden">
          <iframe
            title="html-preview"
            sandbox="allow-same-origin"
            srcDoc={source}
            className="absolute inset-0 w-full h-full bg-white"
          />
        </div>
      ) : (
        <pre className="text-[11px] text-[#d4d4d8] whitespace-pre-wrap font-mono leading-relaxed flex-1 overflow-auto min-h-0">
          {source}
        </pre>
      )}
    </div>
  );
}

/* ─── JSON 预览：格式化 + 语法高亮 ─── */

/** JSON token 着色（轻量自实现，避免引入额外依赖） */
function highlightJson(jsonStr: string): { __html: string } {
  // 转义 HTML 特殊字符，防 XSS
  const escaped = jsonStr
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
  // 用正则给不同 token 着色：key / string / number / boolean / null
  const colored = escaped.replace(
    /("(\\u[a-zA-Z0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)/g,
    (match) => {
      let cls = 'text-emerald-400'; // number
      if (/^"/.test(match)) {
        cls = /:$/.test(match) ? 'text-[#1E5EFF]' : 'text-amber-300'; // key : vs string
      } else if (/true|false/.test(match)) {
        cls = 'text-purple-400'; // boolean
      } else if (/null/.test(match)) {
        cls = 'text-rose-400'; // null
      }
      return `<span class="${cls}">${match}</span>`;
    },
  );
  return { __html: colored };
}

function JsonPreview({ raw }: { raw: string }) {
  const { formatted, parseError } = useMemo(() => {
    try {
      return { formatted: JSON.stringify(JSON.parse(raw), null, 2), parseError: null as string | null };
    } catch {
      return { formatted: raw, parseError: 'JSON 格式无效，显示原始内容' };
    }
  }, [raw]);

  return (
    <div className="flex flex-col gap-2">
      {parseError && (
        <div className="text-[10px] text-amber-400 bg-amber-500/10 border border-amber-500/20 rounded px-2 py-1">
          {parseError}
        </div>
      )}
      <pre
        className="text-[11px] whitespace-pre-wrap font-mono leading-relaxed"
        dangerouslySetInnerHTML={highlightJson(formatted)}
      />
    </div>
  );
}

export default FilePreview;
