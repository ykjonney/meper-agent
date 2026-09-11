import { useEffect, useId, useRef, useState } from 'react';

/**
 * Mermaid diagram block — renders ```mermaid fenced code as SVG.
 *
 * Used by the wiki page viewer (the wiki guide mandates a visual element
 * per page: table or Mermaid). Robustness measures:
 *
 * - Renders into an off-screen host div passed as mermaid's container —
 *   otherwise mermaid appends its temp measurement div (`d{id}`) to
 *   document.body, and the failure path leaves it behind, inflating the
 *   page height (giant blank area below the app).
 * - LLM-generated diagrams frequently contain syntax landmines — footnote
 *   markers `[^1]` inside node labels, ASCII parens, truncated arrows
 *   `--|x|` — so rendering retries once with a sanitized copy.
 * - `suppressErrorRendering` stops mermaid from dumping its own
 *   "Syntax error in text" SVG into the body; errors render in the
 *   readable amber box below instead.
 *
 * mermaid is imported dynamically so its ~1MB bundle only loads when a
 * diagram is actually present.
 */
export function MermaidBlock({ code }: { code: string }) {
  const reactId = useId().replace(/[^a-zA-Z0-9]/g, '');
  const hostRef = useRef<HTMLDivElement>(null);
  const [svg, setSvg] = useState<string>('');
  const [error, setError] = useState<string>('');
  const seq = useRef(0);

  useEffect(() => {
    let cancelled = false;
    const attempt = ++seq.current;
    (async () => {
      const host = hostRef.current;
      if (!host) return;
      try {
        const mermaid = (await import('mermaid')).default;
        mermaid.initialize({
          startOnLoad: false,
          theme: 'dark',
          securityLevel: 'strict',
          suppressErrorRendering: true,
        });
        // 第三个参数 = 渲染容器：临时 div 挂进屏幕外 host，不碰 body 布局。
        const render = (text: string, suffix: string) =>
          mermaid.render(`mmd-${reactId}-${attempt}${suffix}`, text, host);
        try {
          const { svg: out } = await render(code, '');
          if (!cancelled) {
            setSvg(out);
            setError('');
          }
        } catch (rawExc) {
          // 第二次机会：清洗常见 LLM 语法雷后再渲染。
          try {
            const { svg: out } = await render(sanitizeMermaid(code), 'r');
            if (!cancelled) {
              setSvg(out);
              setError('');
            }
          } catch (exc) {
            if (!cancelled) setError(String((exc as Error)?.message ?? rawExc));
          }
        }
      } catch (exc) {
        if (!cancelled) setError(String((exc as Error)?.message ?? exc));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [code, reactId]);

  // 兜底清扫：清掉历史版本残留在 body 末尾的 mermaid 临时容器。
  useEffect(() => {
    document.querySelectorAll('body > [id^="dmmd-"]').forEach((el) => el.remove());
  }, [svg, error]);

  return (
    <>
      {/* 屏幕外渲染 host：position:fixed 的元素永不参与文档可滚动区域
          （absolute + ICB 包含块会短暂逃逸 app 壳层的 overflow-hidden，
          渲染瞬间可能把窗口撑出滚动区）；visibility:hidden 保留测量布局 */}
      <div
        ref={hostRef}
        aria-hidden
        style={{
          position: "fixed",
          left: "-99999px",
          top: 0,
          width: "960px",
          visibility: "hidden",
          pointerEvents: "none",
        }}
      />
      {error ? (
        <div className="my-3 rounded-lg border border-amber-800/50 bg-amber-950/20 p-3">
          <p className="text-[11px] text-amber-400 mb-1 font-semibold">
            Mermaid 图解析失败：{error}
          </p>
          <pre className="text-[11px] text-[#a1a1aa] whitespace-pre-wrap font-mono">{code}</pre>
        </div>
      ) : !svg ? (
        <div className="my-3 h-16 animate-pulse rounded-lg bg-[#27272a]" />
      ) : (
        // SVG output is produced locally by mermaid under securityLevel: strict.
        <div
          className="my-3 overflow-x-auto rounded-lg border border-[#27272a] bg-[#18181b] p-3 [&_svg]:mx-auto [&_svg]:max-w-full [&_svg]:h-auto"
          dangerouslySetInnerHTML={{ __html: svg }}
        />
      )}
    </>
  );
}

/**
 * Strip the syntax landmines LLMs keep putting inside mermaid labels:
 * - footnote markers ``[^1]`` (nested brackets are a hard parse error)
 * - backticks / leading markdown heading hashes
 * - ASCII parens in labels (break nodes; circle ``((x))`` syntax preserved)
 * - truncated arrows ``--|label|`` → ``-->|label|`` (mermaid 11 rejects
 *   pipe labels on two-dash open links — verified against 11.17.2)
 */
function sanitizeMermaid(src: string): string {
  return src
    .replace(/\[\^\w+\]/g, '')
    .replace(/`/g, '')
    .replace(/^#+\s*/gm, '')
    .replace(/(?<!\()\(([^()]*)\)(?!\))/g, '（$1）')
    .replace(/(?<!-)--(?=\|)/g, '-->');
}
