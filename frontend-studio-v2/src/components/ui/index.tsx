/**
 * af/ui — 共享 UI 组件层（v2 统一组件库）。
 *
 * 使用规则：
 * 1. 页面禁止直写 hex/重复样式 — 颜色用 token（var(--color-*)），结构用这里的组件。
 * 2. 改这里的组件 = 全站生效；影响面 = grep 组件名即可知。
 * 3. 组件视觉基线 = 已确认的预览稿（home-dashboard / all-pages-review）。
 */
import type { ReactNode } from 'react';
import { FlowMark } from '../shell/FlowMark';

/* ── Pill：语义状态标签 ─────────────────────────────────────── */
export type PillTone = 'success' | 'brand' | 'warning' | 'danger' | 'neutral' | 'running';
export function Pill({ tone = 'neutral', children }: { tone?: PillTone; children: ReactNode }) {
  const map: Record<PillTone, string> = {
    success: 'background:var(--color-success-soft);color:var(--color-success)',
    brand: 'background:var(--color-brand-soft);color:var(--color-brand)',
    warning: 'background:var(--color-warning-soft);color:var(--color-warning)',
    danger: 'background:var(--color-danger-soft);color:var(--color-danger)',
    neutral: 'background:var(--color-panel);border:1px solid var(--color-line);color:var(--color-ink-dim)',
    running: 'background:var(--color-brand-soft);color:var(--color-brand)',
  };
  return <span className="af-pill" style={{ display: 'inline-flex', borderRadius: 99, padding: '2px 10px', fontSize: 10, fontWeight: 700, ...css(map[tone]) }}>{children}</span>;
}

/* ── Dot：状态灯点 ──────────────────────────────────────────── */
export function Dot({ tone = 'neutral' }: { tone?: PillTone }) {
  const c: Record<PillTone, string> = {
    success: 'var(--color-success)', brand: 'var(--color-brand)', running: 'var(--color-brand)',
    warning: 'var(--color-warning)', danger: 'var(--color-danger)', neutral: 'var(--color-ink-faint)',
  };
  return <span style={{ width: 7, height: 7, borderRadius: 99, background: c[tone], display: 'inline-block', flex: 'none' }} />;
}

/* ── Meter：进度条（alt = 图表次色）────────────────────────── */
export function Meter({ pct, alt, pulse }: { pct?: number; alt?: boolean; pulse?: boolean }) {
  return (
    <div style={{ height: 5, background: 'var(--color-brand-soft)', borderRadius: 99, overflow: 'hidden' }}>
      <i
        className={pulse ? 'af-pulse-bar' : undefined}
        style={{
          display: 'block', height: '100%', borderRadius: 99,
          width: pulse ? '100%' : `${Math.max(2, Math.min(100, pct ?? 0))}%`,
          background: alt ? 'var(--color-chart-alt)' : 'linear-gradient(90deg, var(--color-brand-grad-from), var(--color-brand-grad-to))',
        }}
      />
    </div>
  );
}

/* ── Panel：白卡区块（标题 + more 链接 + 内容）──────────────── */
export function Panel({ title, more, onMore, children, style }: {
  title: ReactNode; more?: string; onMore?: () => void; children: ReactNode; style?: React.CSSProperties;
}) {
  return (
    <section className="af-card" style={{ padding: '16px 18px', flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', ...style }}>
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: 12 }}>
        <b style={{ fontSize: 15 }}>{title}</b>
        {more && onMore && (
          <span onClick={onMore} style={{ marginLeft: 'auto', fontSize: 12, color: 'var(--color-brand)', fontWeight: 600, cursor: 'pointer' }}>{more}</span>
        )}
      </div>
      {children}
    </section>
  );
}

/* ── KpiCard：KPI 大数字卡 ──────────────────────────────────── */
export function KpiCard({ icon, label, value, unit, sub, tone, onClick }: {
  icon: string; label: string; value: ReactNode; unit?: string; sub?: ReactNode;
  tone?: 'brand' | 'danger'; onClick?: () => void;
}) {
  const danger = tone === 'danger' && Number(value) > 0;
  return (
    <div className="af-card" onClick={onClick} style={{
      flex: 1, padding: '14px 17px', borderRadius: 16, cursor: onClick ? 'pointer' : 'default',
      transition: 'transform .15s', ...(onClick ? { ':hover': {} } as never : {}),
    }}>
      <div style={{ fontSize: 12, color: 'var(--color-ink-dim)', display: 'flex', alignItems: 'center', gap: 6 }}>
        <span>{icon}</span> {label}
      </div>
      <div style={{ fontSize: 29, fontWeight: 800, marginTop: 4, lineHeight: 1, color: danger ? 'var(--color-danger)' : tone === 'brand' ? 'var(--color-brand)' : 'var(--color-ink)' }}>
        {value}{unit && <small style={{ fontSize: 13, fontWeight: 600, color: 'var(--color-ink-dim)' }}> {unit}</small>}
      </div>
      {sub && <div style={{ fontSize: 11.5, marginTop: 3, fontWeight: 700, color: danger ? 'var(--color-danger)' : 'var(--color-success)' }}>{sub}</div>}
    </div>
  );
}

/* ── Toggle：开关 ───────────────────────────────────────────── */
export function Toggle({ on, onClick }: { on: boolean; onClick?: () => void }) {
  return (
    <span
      onClick={onClick}
      style={{
        width: 29, height: 17, borderRadius: 99, display: 'inline-block', verticalAlign: 'middle', cursor: 'pointer',
        background: on ? 'var(--color-brand)' : 'var(--color-ink-faint)', position: 'relative', transition: 'background .15s',
      }}
    >
      <i style={{ position: 'absolute', top: 2, width: 13, height: 13, borderRadius: '50%', background: '#fff', left: on ? 14 : 2, transition: 'left .15s' }} />
    </span>
  );
}

/* ── PageHeader：工作区页头（标题 + Tab + actions）──────────── */
export interface PageTab { key: string; label: string; count?: number }
export function PageHeader({ title, tabs, active, onTab, actions }: {
  title: string; tabs?: PageTab[]; active?: string; onTab?: (k: string) => void; actions?: ReactNode;
}) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 16 }}>
      <h2 style={{ margin: 0, fontSize: 19, fontWeight: 800 }}>{title}</h2>
      {tabs && (
        <div className="af-tabs">
          {tabs.map((t) => (
            <span key={t.key} className={`af-tab ${active === t.key ? 'af-tab-on' : ''}`} onClick={() => onTab?.(t.key)}>
              {t.label}{t.count !== undefined && ` · ${t.count}`}
            </span>
          ))}
        </div>
      )}
      <div style={{ marginLeft: 'auto', display: 'flex', gap: 10, alignItems: 'center' }}>{actions}</div>
    </div>
  );
}

/* ── EmptyCard：空态 ────────────────────────────────────────── */
export function EmptyCard({ text, span }: { text: string; span?: boolean }) {
  return (
    <div className="af-card" style={{
      padding: '60px 20px', textAlign: 'center', gridColumn: span ? '1 / -1' : undefined,
      display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 12, color: 'var(--color-ink-dim)', fontSize: 13,
    }}>
      <FlowMark size={32} />
      {text}
    </div>
  );
}

/* ── 主/次按钮（mockup 的 K-bp / K-bg 语义化）───────────────── */
export function Btn({ primary, children, onClick, style }: {
  primary?: boolean; children: ReactNode; onClick?: (e: React.MouseEvent) => void; style?: React.CSSProperties;
}) {
  return (
    <span
      onClick={onClick}
      style={{
        borderRadius: 8, padding: '5px 15px', fontSize: 12, fontWeight: 700, cursor: 'pointer', display: 'inline-block',
        ...(primary
          ? { background: 'linear-gradient(135deg, var(--color-brand-grad-from), var(--color-brand-grad-to))', color: 'var(--color-on-brand)' }
          : { border: '1px solid var(--color-line-strong)', color: 'var(--color-brand)', background: 'var(--color-panel)' }),
        ...style,
      }}
    >
      {children}
    </span>
  );
}

/* ── 内部：css() 帮助函数 ───────────────────────────────────── */
function css(decl: string): React.CSSProperties {
  const out: Record<string, string> = {};
  for (const line of decl.split(';')) {
    const [k, v] = line.split(':');
    if (!k || !v) continue;
    const key = k.trim().replace(/-([a-z])/g, (_, c) => c.toUpperCase());
    out[key] = v.trim();
  }
  return out as React.CSSProperties;
}
