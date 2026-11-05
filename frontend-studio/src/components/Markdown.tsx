import { isValidElement, memo, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeHighlight from 'rehype-highlight';
import { Check, Copy } from 'lucide-react';

import { EChartBlock } from './EChartBlock';
import { MermaidBlock } from './MermaidBlock';

/**
 * Streaming-aware Markdown renderer for chat bubbles.
 *
 * Both user and agent messages are rendered as Markdown so pasted formatted
 * text and AI answers (code blocks, lists, tables, headings) render nicely.
 *
 * The tricky part of rendering *partial* content during a stream is that an
 * incomplete fenced code block (```) will swallow everything after it until
 * the fence closes. `closeIncompleteBlocks` patches that up before parsing
 * so the bubble stays readable while tokens are still arriving.
 *
 * ```echarts fenced blocks (render_chart tool or hand-written by the agent)
 * render as charts via EChartBlock; a partial option shows a
 * "rendering…" placeholder until the JSON is complete.
 *
 * Fenced code blocks render with a language tag + one-click copy header
 * (v3.2 Workbench §4.7 代码块增强).
 */

export interface MarkdownProps {
  /** Raw markdown text. May be partial (mid-stream). */
  content: string;
}

/** 递归提取 React 子树里的纯文本（highlight 后 code 内是多级 span）。 */
function extractText(node: unknown): string {
  if (node == null || typeof node === 'boolean') return '';
  if (typeof node === 'string' || typeof node === 'number') return String(node);
  if (Array.isArray(node)) return node.map(extractText).join('');
  if (isValidElement(node)) return extractText((node.props as { children?: unknown }).children);
  return '';
}

/** 带语言标签 + 复制按钮的代码块容器。 */
function CodeBlock({ language, children, ...preProps }: {
  language: string;
  children?: React.ReactNode;
  [key: string]: unknown;
}) {
  const [copied, setCopied] = useState(false);
  const raw = extractText(children);
  const copy = () => {
    navigator.clipboard?.writeText(raw).catch(() => {});
    setCopied(true);
    setTimeout(() => setCopied(false), 1600);
  };
  return (
    <div className="af-codeblock">
      <div className="af-codeblock-head">
        <span className="af-codeblock-lang">{language || 'code'}</span>
        <button
          type="button"
          onClick={copy}
          className="af-codeblock-copy"
          title="复制代码"
        >
          {copied ? <Check className="w-3 h-3" /> : <Copy className="w-3 h-3" />}
          {copied ? '已复制' : '复制'}
        </button>
      </div>
      <pre {...preProps}>{children}</pre>
    </div>
  );
}

export const Markdown = memo(function Markdown({ content }: MarkdownProps) {
  const safe = closeIncompleteBlocks(content ?? '');
  return (
    <div className="prose-chat">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[[rehypeHighlight, { detect: true, ignoreMissing: true }]]}
        components={{
          // Open external links in a new tab; keep relative links as-is.
          a: ({ node, ...props }) => (
            <a {...props} target={props.href?.startsWith('http') ? '_blank' : undefined} rel="noreferrer" />
          ),
          // ```echarts / ```chart → chart; ```mermaid → diagram (wiki pages
          // mandate a visual element per the wiki guide).
          code: ({ className, children, ...props }) => {
            const language = /language-([^\s]+)/.exec(className ?? '')?.[1];
            if (language === 'echarts' || language === 'chart') {
              return <EChartBlock option={String(children).replace(/\n$/, '')} />;
            }
            if (language === 'mermaid') {
              return <MermaidBlock code={String(children).replace(/\n$/, '')} />;
            }
            return (
              <code className={className} {...props}>
                {children}
              </code>
            );
          },
          // Unwrap <pre> around chart/diagram blocks (they bring their own container);
          // plain code blocks get the language+copy chrome.
          pre: ({ children, ...props }) => {
            const child = Array.isArray(children) ? children[0] : children;
            if (
              isValidElement(child) &&
              (child.type === EChartBlock || child.type === MermaidBlock)
            ) {
              return child;
            }
            const lang =
              isValidElement(child)
                ? /language-([^\s]+)/.exec(String((child.props as { className?: string }).className ?? ''))?.[1] ?? ''
                : '';
            return <CodeBlock language={lang} {...props}>{children}</CodeBlock>;
          },
        }}
      >
        {safe}
      </ReactMarkdown>
    </div>
  );
});

/**
 * Patch a partial markdown string so it renders cleanly mid-stream.
 *
 * Counts unmatched ``` fences: if there is an odd number of fences the last
 * block was never closed, so we append a closing fence. This is the single
 * most common cause of "the whole rest of the message turned into a code
 * block" while streaming.
 */
function closeIncompleteBlocks(src: string): string {
  // Tally fenced-code-block delimiters (lines that start with ```).
  // A fence may be followed by a language tag, e.g. ```ts.
  const fenceMatches = src.match(/^`{3,}/gm);
  const openFences = fenceMatches ? fenceMatches.length % 2 : 0;
  let out = src;
  if (openFences) {
    out += '\n```\n';
  }
  return out;
}
