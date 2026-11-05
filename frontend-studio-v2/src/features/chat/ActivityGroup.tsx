/**
 * ActivityGroup — 执行活动卡（v5：回归整体设计语言）
 *
 * 主人反馈修正：① 工具/思考图标加类别色框（与下拉箭头明确区分）
 * ② 整体回归 agent-flow 风格 — 白卡 + 淡紫卡头 + 类别色图标框，
 * 不再是无边框极简风（与全局卡片语言统一）。
 *
 * 收起态 = 一张一行卡：  [⚡ 执行活动 · 工作了 2m 36s · 3 工具 ✓  ⌄]
 * 展开态 = 卡头 + 时序叙事流：
 *   [🧠] 思考了 24s ⌄ → 淡紫块全文（超高滚动）
 *   中间文本（正文层级）
 *   [⌨] git add -A && … · 失败（内联红显）
 *   [⌨][🔍] 运行 3 命令 和 搜索 1 次 ✓ ⌄ → 左线明细
 */
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import {
  Brain, ChevronRight, Search, Terminal, FileText, Sparkles, Plug,
  ClipboardList, Loader2, Zap,
} from 'lucide-react';
import type { ChatMessage } from './useChatStream';
import type { TimelineEntry } from '../../types';
import { Markdown } from './Markdown';
import { ClarificationFormCard, type ClarificationField } from './clarification-form-card';

/* ── 工具类别 + 带框图标 ───────────────────────────────────── */
type Cat = 'search' | 'code' | 'file' | 'gen' | 'mcp' | 'plan';
function toolCategory(toolName?: string): Cat {
  const n = (toolName ?? '').toLowerCase();
  if (n.includes('plan') || n.includes('confirm') || n.includes('clarif')) return 'plan';
  if (n.includes('mcp') || n.includes('feishu') || n.includes('dingtalk') || n.includes('notify')) return 'mcp';
  if (n.includes('chart') || n.includes('image') || n.includes('render')) return 'gen';
  if (n.includes('file') || n.includes('read') || n.includes('write') || n.includes('upload')) return 'file';
  if (n.includes('search') || n.includes('kb') || n.includes('recall') || n.includes('web')) return 'search';
  return 'code';
}
const CAT_ICON: Record<Cat, typeof Search> = {
  search: Search, code: Terminal, file: FileText, gen: Sparkles, mcp: Plug, plan: ClipboardList,
};

/** 类别色框图标（20px 圆角块 — 与下拉箭头 12px 裸灰明确区分） */
function CatBadge({ cat, size = 20 }: { cat: Cat; size?: number }) {
  const Icon = CAT_ICON[cat];
  return (
    <span className={`af-cat af-cat-${cat}`} style={{ width: size, height: size, borderRadius: 6 }}>
      <Icon size={size * 0.58} strokeWidth={2.1} />
    </span>
  );
}
/** 思考图标框（淡紫底） */
function ThinkBadge({ streaming = false, size = 20 }: { streaming?: boolean; size?: number }) {
  return (
    <span className="af-cat af-cat-code" style={{ width: size, height: size, borderRadius: 6 }}>
      <Brain size={size * 0.58} strokeWidth={2.1} className={streaming ? 'animate-pulse' : ''} />
    </span>
  );
}

/** 工具行文本：bash(git add -A && …) 形式 — 工具名(关键参数) */
function entryLine(e: TimelineEntry): string {
  const name = e.toolName || '工具';
  const args = e.args as Record<string, unknown> | undefined;
  const cand = args && (args.command ?? args.query ?? args.code ?? args.path ?? args.topic ?? args.question);
  if (typeof cand === 'string' && cand) {
    const short = cand.replace(/\s+/g, ' ');
    return `${name}(${short.length > 60 ? `${short.slice(0, 60)}…` : short})`;
  }
  return name;
}

function errorSummary(e: TimelineEntry): string {
  if (!e.result) return '执行失败';
  const t = e.result.replace(/\s+/g, ' ').trim();
  return t.length > 90 ? `${t.slice(0, 90)}…` : t;
}

function catVerb(cat: Cat, n: number): string {
  switch (cat) {
    case 'code': return n === 1 ? '运行 1 个命令' : `运行 ${n} 命令`;
    case 'search': return n === 1 ? '网上搜索了 1 次' : `网上搜索了 ${n} 次`;
    case 'file': return n === 1 ? '读写 1 个文件' : `文件操作 ${n} 次`;
    case 'gen': return n === 1 ? '生成 1 个产物' : `生成 ${n} 个产物`;
    case 'mcp': return n === 1 ? '调用 1 次外部集成' : `调用外部集成 ${n} 次`;
    case 'plan': return `计划审批 ×${n}`;
  }
}

function fmtSec(ms?: number): string {
  if (!ms || ms <= 0) return '';
  const s = Math.round(ms / 1000);
  return s >= 60 ? `${Math.floor(s / 60)}m ${s % 60}s` : `${s}s`;
}

/* ── 渲染段：严格 timeline 时序 ── */
type Segment =
  | { kind: 'think'; e: TimelineEntry }
  | { kind: 'text'; e: TimelineEntry }
  | { kind: 'special'; e: TimelineEntry }
  | { kind: 'tools'; items: TimelineEntry[] };

/* ── 特殊工具（独有叙事节点，永远单条渲染、不参与聚合）──────── */
type SpecialKind = 'clarify' | 'plan' | 'confirm_wf' | 'subagent' | 'parse_file' | 'chart' | 'recall' | 'auth' | 'skill';
function specialTool(t: TimelineEntry): SpecialKind | null {
  const n = (t.toolName ?? '').toLowerCase();
  if (n === 'ask_clarification') return 'clarify';
  if (n === 'propose_plan') return 'plan';
  if (n === 'confirm_workflow') return 'confirm_wf';
  if (n === 'delegate_to_subagent') return 'subagent';
  if (n === 'parse_file') return 'parse_file';
  if (n === 'render_chart') return 'chart';
  if (n === 'recall_tool_result') return 'recall';
  if (n === 'request_app_authorization') return 'auth';
  if (n.includes('skill')) return 'skill';
  return null;
}

export function ActivityGroup({ msg, live, onAnswer }: {
  msg: ChatMessage;
  live: boolean;
  /** 回答挂起的 interrupt（澄清选项/计划审批）— 上层接 send（自动走 resume） */
  onAnswer?: (text: string) => void;
}) {
  const all = msg.timeline ?? [];

  const segments = useMemo<Segment[]>(() => {
    const segs: Segment[] = [];
    for (let i = 0; i < all.length; i++) {
      const e = all[i];
      if (e.type === 'thinking') {
        segs.push({ kind: 'think', e });
      } else if (e.type === 'text' && e.content) {
        // live：所有文本都在组内时序流动（最终答案 done 后才定稿到正文位）；
        // done：只有后面还跟着过程的才是中间说明
        if (live || all.slice(i + 1).some((x) => x.type === 'thinking' || x.type === 'tool')) {
          segs.push({ kind: 'text', e });
        }
      } else if (e.type === 'tool') {
        if (specialTool(e)) {
          segs.push({ kind: 'special', e });
          continue;
        }
        const last = segs[segs.length - 1];
        if (last?.kind === 'tools') last.items.push(e);
        else segs.push({ kind: 'tools', items: [e] });
      }
    }
    return segs;
  }, [all, live]);

  if (segments.length === 0) return null;

  const totalTools = all.filter((e) => e.type === 'tool');
  const failCount = totalTools.filter((e) => e.toolStatus === 'error').length;
  const okCount = totalTools.filter((e) => e.toolStatus === 'success').length;
  const runningNow = live && totalTools.some((e) => e.toolStatus === 'running' || e.toolStatus === 'pending');
  const thinkingNow = live && all.some((e) => e.type === 'thinking' && e.expanded === true);
  const elapsed = msg.elapsedMs ?? (msg.streamStartedAt ? Date.now() - msg.streamStartedAt : undefined);

  return (
    <GroupInner
      msg={msg} live={live} onAnswer={onAnswer}
      runningNow={runningNow} thinkingNow={thinkingNow} elapsed={elapsed}
      segments={segments}
      toolCount={totalTools.length} okCount={okCount} failCount={failCount}
    />
  );
}

function GroupInner({
  msg, live, onAnswer, runningNow, thinkingNow, elapsed,
  segments, toolCount, okCount, failCount,
}: {
  msg: ChatMessage;
  live: boolean;
  onAnswer?: (text: string) => void;
  runningNow: boolean;
  thinkingNow: boolean;
  elapsed?: number;
  segments: Segment[];
  toolCount: number;
  okCount: number;
  failCount: number;
}) {
  // 状态机（主人定稿）：执行中展开直播（用户中途收起=暂不想看，尊重）；
  // 结束无条件收起（不管用户点没点）；完成后系统不再干预，归用户自由操作；
  // interrupt 挂起（等用户输入）时保持展开。
  const waitingUser = msg.isInterrupted === true;
  const [open, setOpen] = useState(live || waitingUser);
  useEffect(() => {
    if (waitingUser) { setOpen(true); return; }
    if (!live) { setOpen(false); return; }
  }, [live, waitingUser]);
  const [, tick] = useState(0);
  useEffect(() => {
    if (!live || !msg.streamStartedAt || msg.elapsedMs !== undefined) return;
    const t = setInterval(() => tick((n) => n + 1), 1000);
    return () => clearInterval(t);
  }, [live, msg.streamStartedAt, msg.elapsedMs]);

  // 「下一个开始就关闭」：扁平过程序列中，非最后一条 = 已被接替
  const flatProcess = useMemo(
    () => segments.flatMap((seg) => seg.kind === 'think' || seg.kind === 'special' ? [seg.e] : seg.kind === 'tools' ? seg.items : []),
    [segments],
  );
  const isSuperseded = useCallback((e: TimelineEntry) => {
    const idx = flatProcess.findIndex((x) => x.id === e.id);
    return idx >= 0 && idx < flatProcess.length - 1;
  }, [flatProcess]);

  const statusText = runningNow ? '工作中' : thinkingNow ? '思考中' : '工作了';
  const allOk = toolCount > 0 && failCount === 0 && okCount === toolCount;

  return (
    <div className="w-full overflow-hidden rounded-xl border border-line bg-panel shadow-card">
      {/* 卡头 = 收起态整卡 / 展开态头部（点击切换） */}
      <button
        onClick={() => setOpen((v) => !v)}
        className={`flex w-full items-center gap-2 px-3.5 py-2.5 text-left transition-colors hover:bg-brand-soft/40 ${
          open ? 'bg-brand-soft/40' : ''
        }`}
      >
        {live
          ? <Loader2 size={14} className="flex-none animate-spin-soft text-brand" />
          : <Zap size={14} className="flex-none text-brand" />}
        <b className="flex-none text-[12.5px] text-ink">执行活动</b>
        <span className="af-label flex-none">EXEC</span>
        <span className="min-w-0 truncate text-[12px] text-ink-dim">
          {live
            ? <>工作中{elapsed ? ` ${fmtSec(elapsed)}` : ''}</>
            : <>
                {statusText}
                {elapsed ? ` ${fmtSec(elapsed)}` : ''}
                {toolCount > 0 && ` · ${toolCount} 工具`}
                {failCount > 0
                  ? <span className="font-bold text-danger"> · {failCount} 失败</span>
                  : allOk ? ' · 全部成功' : ''}
              </>}
        </span>
        <ChevronRight size={13} className={`ml-auto flex-none text-ink-faint transition-transform ${open ? 'rotate-90' : ''}`} />
      </button>

      {/* 展开体：时序叙事流 */}
      {open && (
        <div className="flex flex-col gap-2.5 border-t border-line px-3.5 py-3">
          {segments.map((seg, i) => {
            if (seg.kind === 'think') return <ThinkRow key={seg.e.id ?? i} e={seg.e} live={live} superseded={isSuperseded(seg.e)} />;
            if (seg.kind === 'text') {
              return (
                <div key={seg.e.id ?? i} className="prose-chat text-[13.5px] text-ink">
                  <Markdown content={seg.e.content} />
                </div>
              );
            }
            if (seg.kind === 'special') {
              return <SpecialToolRow key={seg.e.id ?? i} t={seg.e} live={live} kind={specialTool(seg.e)!} onAnswer={onAnswer} />;
            }
            return seg.items.length === 1
              ? <ToolLine key={seg.items[0].id ?? i} t={seg.items[0]} live={live} superseded={isSuperseded(seg.items[0])} rich />
              : <ToolGroup key={i} tools={seg.items} live={live} superseded={isSuperseded(seg.items[seg.items.length - 1])} />;
          })}
        </div>
      )}
    </div>
  );
}

/* ── 思考：[🧠] 思考了 24s ⌄ → 淡紫块全文 ── */
function ThinkRow({ e, live, superseded }: { e: TimelineEntry; live: boolean; superseded: boolean }) {
  const streaming = live && e.expanded === true;
  // 「下一个开始就关闭」：被后续过程接替 → 立即收起；流式中保持展开
  const [open, setOpen] = useState(streaming && !superseded);
  useEffect(() => {
    if (superseded) setOpen(false);
    else setOpen(streaming);
  }, [superseded, streaming]);
  // 流式内容增长 → 自动滚底；用户上翻（距底 >24px）则暂停跟随
  const bodyRef = useRef<HTMLDivElement>(null);
  const stickRef = useRef(true);
  useEffect(() => {
    if (streaming && stickRef.current && bodyRef.current) {
      bodyRef.current.scrollTop = bodyRef.current.scrollHeight;
    }
  }, [e.content, streaming]);
  if (!e.content) return null;
  return (
    <div>
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-fit items-center gap-2 rounded-md py-0.5 pr-2 text-left transition-colors hover:opacity-80"
      >
        <ThinkBadge streaming={streaming} />
        <b className="text-[12.5px] text-ink">思考过程{streaming ? '中' : ''}</b>
        <span className="text-[11.5px] text-ink-dim">· {e.content.length >= 1000 ? `${(e.content.length / 1000).toFixed(1)}k 字` : `${e.content.length} 字`}</span>
        <ChevronRight size={12} className={`text-ink-faint transition-transform ${open ? 'rotate-90' : ''}`} />
      </button>
      {open && (
        <div
          ref={bodyRef}
          onScroll={(ev) => {
            const el = ev.currentTarget;
            stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
          }}
          className="ml-[10px] mt-1.5 max-h-60 overflow-y-auto scrollbar-custom whitespace-pre-wrap rounded-lg bg-brand-soft/40 px-3 py-2.5 text-[12.5px] leading-relaxed text-ink-soft"
        >
          {e.content}
          {streaming && <span className="ml-0.5 inline-block h-[11px] w-[5px] animate-caret-blink rounded-[1px] bg-brand align-middle" />}
        </div>
      )}
    </div>
  );
}

/* ── 工具单行：[⌨] 命令 · 状态 · 耗时 ›（失败内联红显） ── */
function ToolLine({ t, live, superseded = false, rich = false }: { t: TimelineEntry; live: boolean; superseded?: boolean; rich?: boolean }) {
  const cat = toolCategory(t.toolName);
  const isRunning = t.toolStatus === 'running' || t.toolStatus === 'pending';
  const isError = t.toolStatus === 'error';
  const line = entryLine(t);
  // 「下一个开始就关闭」：被下一个工具接替 → 立即收起；运行中/失败保持展开
  const [open, setOpen] = useState(live && isRunning);
  useEffect(() => {
    if (superseded) { setOpen(false); return; }
    if (isError) { setOpen(true); return; }
    setOpen(live && isRunning);
  }, [superseded, isError, live, isRunning]);
  useEffect(() => {
    if (isError) setOpen(true);
    else if (isRunning && live) setOpen(true);
    else if (!isRunning && !t.result) setOpen(false);
  }, [isError, isRunning, live, t.result]);

  return (
    <div>
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 rounded-md py-0.5 pr-1 text-left transition-colors hover:bg-panel-hover"
      >
        {isRunning
          ? <span className="af-cat af-cat-code" style={{ width: 20, height: 20, borderRadius: 6 }}><Loader2 size={11} className="animate-spin-soft text-brand" /></span>
          : isError
            ? <span className="af-cat" style={{ width: 20, height: 20, borderRadius: 6, background: 'var(--color-danger-soft)', color: 'var(--color-danger)' }}><Terminal size={11} strokeWidth={2.1} /></span>
            : <CatBadge cat={cat} />}
        <span className={`min-w-0 flex-1 truncate font-mono text-[12px] ${isError ? 'text-danger' : isRunning ? 'text-brand' : 'text-ink-soft'}`}>
          {line || t.toolName}
          {isRunning && <span className="ml-1 text-[11px] text-ink-faint">运行中…</span>}
        </span>
        {rich && (
          <span className="flex flex-none items-center gap-1.5 text-[10.5px] text-ink-faint">
            {isError && <b className="text-danger">失败</b>}
            {t._ms ? fmtSec(t._ms) : null}
          </span>
        )}
        <ChevronRight size={12} className={`flex-none text-ink-faint transition-transform ${open ? 'rotate-90' : ''}`} />
      </button>
      {open && isError && (
        <div className="ml-[12px] mt-1 rounded-lg bg-danger-soft px-3 py-2 text-[12px] leading-relaxed text-danger">
          {errorSummary(t)}
        </div>
      )}
      {open && !isError && (
        <div className="ml-[12px] mt-1 rounded-lg bg-well px-3 py-2 font-mono text-[11px] leading-relaxed text-ink-dim">
          {t.args != null && (
            <div className="whitespace-pre-wrap break-all">
              <span className="text-ink-faint">$ </span>
              {JSON.stringify(t.args, null, 1).length > 300
                ? `${JSON.stringify(t.args, null, 1).slice(0, 300)}…`
                : JSON.stringify(t.args, null, 1)}
            </div>
          )}
          {t.result && (
            <div className="mt-1 whitespace-pre-wrap break-all">
              <span className="text-ink-faint">→ </span>
              {t.result.length > 400 ? `${t.result.slice(0, 400)}…` : t.result}
            </div>
          )}
          {!t.args && !t.result && <span className="text-ink-faint">等待结果…</span>}
        </div>
      )}
    </div>
  );
}

/* ── 工具聚合段 ── */
function ToolGroup({ tools, live, superseded = false }: { tools: TimelineEntry[]; live: boolean; superseded?: boolean }) {
  // 状态机：执行中且被接替 → 收；运行中/执行中出错 → 展开直播；
  // done → 一律收起（失败数在卡头红显，点开看详情）— 修复含错误时永远无法收起
  const hasRunning = tools.some((t) => t.toolStatus === 'running' || t.toolStatus === 'pending');
  const hasError = tools.some((t) => t.toolStatus === 'error');
  const [open, setOpen] = useState(live && hasRunning);
  useEffect(() => {
    if (!live) { setOpen(false); return; }
    if (superseded) { setOpen(false); return; }
    setOpen(hasRunning || hasError);
  }, [superseded, hasError, hasRunning, live]);
  const runningNow = live && tools.some((t) => t.toolStatus === 'running' || t.toolStatus === 'pending');
  useEffect(() => {
    if (tools.some((t) => t.toolStatus === 'running' || t.toolStatus === 'pending')) setOpen(true);
    if (tools.some((t) => t.toolStatus === 'error')) setOpen(true);
  }, [tools]);
  const failCount = tools.filter((t) => t.toolStatus === 'error').length;
  const allOk = tools.every((t) => t.toolStatus === 'success');

  const cats: Cat[] = [];
  for (const t of tools) {
    const c = toolCategory(t.toolName);
    if (!cats.includes(c)) cats.push(c);
  }
  const parts = cats.map((c) => catVerb(c, tools.filter((t) => toolCategory(t.toolName) === c).length));

  return (
    <div>
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-fit items-center gap-2 rounded-md py-0.5 pr-2 text-left transition-colors hover:opacity-80"
      >
        {/* 最多展示 2 个类别框 */}
        <span className="flex -space-x-1">
          {cats.slice(0, 2).map((c) => <CatBadge key={c} cat={c} />)}
          {cats.length > 2 && (
            <span className="af-cat bg-panel-hover text-[9px] font-bold text-ink-dim" style={{ width: 20, height: 20, borderRadius: 6 }}>
              +{cats.length - 2}
            </span>
          )}
        </span>
        <b className="text-[12.5px] text-ink">{parts.join(' 和 ')}</b>
        {runningNow && <Loader2 size={12} className="animate-spin-soft text-brand" />}
        {failCount > 0
          ? <span className="text-[11.5px] font-bold text-danger">{failCount} 失败</span>
          : allOk ? <CheckBadge /> : null}
        <ChevronRight size={12} className={`text-ink-faint transition-transform ${open ? 'rotate-90' : ''}`} />
      </button>

      {open && (
        <div className="ml-[9px] mt-1 flex flex-col gap-0.5 border-l border-line pl-3">
          {tools.map((t) => <ToolLine key={t.id} t={t} live={live} />)}
        </div>
      )}
    </div>
  );
}

function CheckBadge() {
  return (
    <span className="flex h-[14px] w-[14px] flex-none items-center justify-center rounded-full bg-success-soft">
      <svg width="9" height="9" viewBox="0 0 10 10" fill="none" stroke="var(--color-success)" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
        <path d="M1.5 5.5 L4 8 L8.5 2.5" />
      </svg>
    </span>
  );
}


/* ══════════════ 特殊工具专属渲染（独有能力的叙事节点） ══════════════ */
function SpecialToolRow({ t, live, kind, onAnswer }: {
  t: TimelineEntry; live: boolean; kind: SpecialKind; onAnswer?: (text: string) => void;
}) {
  const args = (t.args ?? {}) as Record<string, unknown>;
  const isRunning = t.toolStatus === 'running' || t.toolStatus === 'pending';
  const answered = Boolean(t.result);
  const awaitingInput = kind === 'clarify' && !answered;

  // —— 澄清提问：默认展开、琥珀底、待回答 pill ——
  if (kind === 'clarify') {
    const opts = Array.isArray(args.options) ? (args.options as string[]) : [];
    const fields = Array.isArray(args.fields) ? (args.fields as ClarificationField[]) : [];
    // 向导表单（多题 fields）：接 v1 ClarificationFormCard，提交序列化 JSON 走 resume
    if (fields.length > 0 && awaitingInput) {
      return (
        <div className="overflow-hidden rounded-xl border border-warning/40 bg-warning-soft/50">
          <div className="flex items-center gap-2 px-3.5 py-2.5">
            <span className="af-cat" style={{ width: 20, height: 20, borderRadius: 6, background: 'var(--color-warning-soft)', color: 'var(--color-warning)' }}>
              <ClipboardList size={11} strokeWidth={2.1} />
            </span>
            <b className="text-[12.5px] text-ink">向你提问 · {fields.length} 个问题</b>
            <span className="af-pill af-pill-warning">等待回答</span>
          </div>
          <div className="px-3.5 pb-3">
            <ClarificationFormCard
              question={typeof args.question === 'string' ? args.question : ''}
              context={(args.context as string | null) ?? null}
              fields={fields}
              answered={false}
              onSubmit={(json) => onAnswer?.(json)}
            />
          </div>
        </div>
      );
    }
    return (
      <div className="overflow-hidden rounded-xl border border-warning/40 bg-warning-soft/50">
        <div className="flex items-center gap-2 px-3.5 py-2.5">
          <span className="af-cat" style={{ width: 20, height: 20, borderRadius: 6, background: 'var(--color-warning-soft)', color: 'var(--color-warning)' }}>
            <ClipboardList size={11} strokeWidth={2.1} />
          </span>
          <b className="text-[12.5px] text-ink">向你提问</b>
          {awaitingInput
            ? <span className="af-pill af-pill-warning">等待回答</span>
            : <span className="af-pill af-pill-success">已回答</span>}
        </div>
        {typeof args.question === 'string' && (
          <div className="px-3.5 pb-2 text-[13px] font-medium leading-relaxed text-ink">{args.question}</div>
        )}
        {opts.length > 0 && awaitingInput && (
          <div className="flex flex-wrap gap-1.5 px-3.5 pb-2.5">
            {opts.slice(0, 8).map((o, i) => (
              <button
                key={i}
                onClick={() => onAnswer?.(String(o))}
                disabled={!onAnswer}
                className="af-pill af-pill-neutral transition-colors hover:bg-brand-soft hover:text-brand"
              >
                {String(o)}
              </button>
            ))}
          </div>
        )}
        {!awaitingInput && opts.length > 0 && (
          <div className="flex flex-wrap gap-1.5 px-3.5 pb-2.5 opacity-60">
            {opts.slice(0, 8).map((o, i) => (
              <span key={i} className="af-pill af-pill-neutral">{String(o)}</span>
            ))}
          </div>
        )}
        {answered && t.result && (
          <div className="mx-3.5 mb-2.5 rounded-lg bg-success-soft px-3 py-2 text-[12px] text-success">
            你的回答：{t.result.length > 200 ? `${t.result.slice(0, 200)}…` : t.result}
          </div>
        )}
      </div>
    );
  }

  // —— 工作流确认：醒目卡 + 确认/取消（confirm → resume「确认执行 {name}」）——
  if (kind === 'confirm_wf') {
    const name = String(args.workflow_name ?? '工作流');
    const desc = typeof args.description === 'string' ? args.description : '';
    const preview = args.input_preview as Record<string, unknown> | undefined;
    const pending = !answered && !isRunning;
    return (
      <div className={`overflow-hidden rounded-xl border bg-panel ${pending ? 'border-brand border-l-[3px] border-l-brand' : 'border-line'}`}>
        <div className="flex items-center gap-2 px-3.5 py-2.5">
          <span className="af-cat af-cat-plan"><ClipboardList size={11} strokeWidth={2.1} /></span>
          <b className="text-[12.5px] text-ink">工作流确认 · {name}</b>
          {answered
            ? <span className="af-pill af-pill-success">已处理</span>
            : isRunning ? <span className="af-pill af-pill-brand">生成中…</span>
            : <span className="af-pill af-pill-warning">待确认</span>}
        </div>
        {desc && <div className="px-3.5 pb-2 text-[12.5px] leading-relaxed text-ink-soft">{desc}</div>}
        {preview && Object.keys(preview).length > 0 && (
          <div className="mx-3.5 mb-2.5 max-h-40 overflow-y-auto scrollbar-custom rounded-lg bg-well px-3 py-2 font-mono text-[11px] leading-relaxed text-ink-dim">
            {JSON.stringify(preview, null, 1).length > 400
              ? `${JSON.stringify(preview, null, 1).slice(0, 400)}…`
              : JSON.stringify(preview, null, 1)}
          </div>
        )}
        {t.toolStatus === 'error' && (
          <div className="mx-3.5 mb-2.5 rounded-lg bg-danger-soft px-3 py-2 text-[12px] text-danger">{errorSummary(t)}</div>
        )}
        {pending && onAnswer && (
          <div className="flex items-center gap-2 px-3.5 pb-3">
            <button onClick={() => onAnswer(`确认执行 ${name}`)} className="af-btn h-7">✓ 确认执行</button>
            <button onClick={() => onAnswer('取消')} className="af-btn-ghost h-7">✕ 取消</button>
          </div>
        )}
      </div>
    );
  }

  // —— 计划审批：紫左边框卡 + 计划正文预览 ——
  if (kind === 'plan') {
    const title = typeof args.title === 'string' ? args.title : '执行计划';
    const plan = typeof args.plan === 'string' ? args.plan : '';
    return (
      <div className="overflow-hidden rounded-xl border border-line border-l-[3px] border-l-brand bg-panel">
        <div className="flex items-center gap-2 px-3.5 py-2.5">
          <span className="af-cat af-cat-plan"><ClipboardList size={11} strokeWidth={2.1} /></span>
          <b className="text-[12.5px] text-ink">📋 {title}</b>
          {answered
            ? <span className="af-pill af-pill-success">已批准</span>
            : isRunning
              ? <span className="af-pill af-pill-brand">生成中…</span>
              : <span className="af-pill af-pill-warning">待审批</span>}
        </div>
        {plan && (
          <div className="mx-3.5 mb-2.5 max-h-56 overflow-y-auto scrollbar-custom rounded-lg bg-well px-3 py-2.5">
            <div className="prose-chat text-[12.5px] text-ink-soft"><Markdown content={plan} /></div>
          </div>
        )}
        {/* 审批操作（HITL 闭环）：批准即 resume；反馈/拒绝走文字回答 */}
        {!answered && onAnswer && !isRunning && (
          <div className="flex items-center gap-2 px-3.5 pb-3">
            <button onClick={() => onAnswer('同意执行')} className="af-btn h-7">✓ 同意执行</button>
            <button onClick={() => onAnswer('计划需要修订：')} className="af-btn-ghost h-7">✎ 反馈修订</button>
          </div>
        )}
      </div>
    );
  }

  // —— 子 Agent 委派：执行主体名做标题 ——
  if (kind === 'subagent') {
    const name = String(args.subagent_name ?? '子 Agent');
    const task = typeof args.task === 'string' ? args.task : '';
    const [open, setOpen] = useState(isRunning && live);
    useEffect(() => { if (isRunning && live) setOpen(true); }, [isRunning, live]);
    return (
      <div>
        <button onClick={() => task && setOpen((v) => !v)}
                className="flex w-fit items-center gap-2 rounded-md py-0.5 pr-2 text-left hover:opacity-80">
          <span className="af-cat af-cat-plan"><BotIcon size={11} strokeWidth={2.1} /></span>
          <b className="text-[12.5px] text-ink">{isRunning ? `${name} 执行子任务中…` : `子 Agent · ${name}`}</b>
          {task && <span className="max-w-[300px] truncate text-[11.5px] text-ink-dim">{task}</span>}
          {answered && t.result && <CheckBadge />}
          {task && <ChevronRight size={12} className={`text-ink-faint transition-transform ${open ? 'rotate-90' : ''}`} />}
        </button>
        {open && task && (
          <div className="ml-[12px] mt-1 max-h-48 overflow-y-auto scrollbar-custom whitespace-pre-wrap rounded-lg bg-well px-3 py-2 text-[11.5px] leading-relaxed text-ink-dim">{task}</div>
        )}
      </div>
    );
  }

  // —— 文件解析 / 图表 / 回溯 / 授权 / 技能：轻量专属行 ——
  const fileLabel = `文件解析 · ${String(args.path ?? '文件').split('/').pop()}`;
  const meta = LIGHT_META[kind]?.(args) ?? { label: fileLabel, badge: null as ReactNode };

  const [open, setOpen] = useState(isErrorSafe(t));
  return (
    <div>
      <button onClick={() => setOpen((v) => !v)}
              className="flex w-fit items-center gap-2 rounded-md py-0.5 pr-2 text-left hover:opacity-80">
        {isRunning
          ? <span className="af-cat af-cat-code" style={{ width: 20, height: 20, borderRadius: 6 }}><Loader2 size={11} className="animate-spin-soft text-brand" /></span>
          : meta.badge}
        <b className={`text-[12.5px] ${t.toolStatus === 'error' ? 'text-danger' : 'text-ink'}`}>{meta.label}</b>
        {isRunning && <span className="text-[11px] text-ink-faint">进行中…</span>}
        {t.toolStatus === 'error' && <span className="text-[11px] font-bold text-danger">失败</span>}
        {t._ms ? <span className="text-[10.5px] text-ink-faint">{fmtSec(t._ms)}</span> : null}
        {(t.args != null || t.result) && (
          <ChevronRight size={12} className={`text-ink-faint transition-transform ${open ? 'rotate-90' : ''}`} />
        )}
      </button>
      {open && (t.result || args.detail != null) && (
        <div className="ml-[12px] mt-1 max-h-60 overflow-y-auto scrollbar-custom rounded-lg bg-well px-3 py-2 font-mono text-[11px] leading-relaxed text-ink-dim">
          <span className="text-ink-faint">→ </span>
          {t.result ? (t.result.length > 400 ? `${t.result.slice(0, 400)}…` : t.result) : String(args.detail ?? '')}
        </div>
      )}
      {open && t.toolStatus === 'error' && (
        <div className="ml-[12px] mt-1 rounded-lg bg-danger-soft px-3 py-2 text-[12px] text-danger">{errorSummary(t)}</div>
      )}
    </div>
  );
}

/* 轻量专属行的 文案+图标（args 相关的动态文案用函数生成） */
const LIGHT_META: Record<SpecialKind, ((args: Record<string, unknown>) => { label: string; badge: ReactNode } | null) | null> = {
  clarify: null, plan: null, subagent: null,
  parse_file: (args) => ({
    label: `文件解析 · ${String(args.path ?? '文件').split('/').pop()}`,
    badge: <CatBadge cat="file" />,
  }),
  chart: () => ({ label: '生成图表', badge: <CatBadge cat="gen" /> }),
  recall: () => ({ label: '↺ 回溯历史工具输出', badge: <CatBadge cat="code" /> }),
  auth: () => ({ label: '🔑 请求应用授权', badge: <CatBadge cat="mcp" /> }),
  skill: (args) => ({
    label: `加载技能${args.skill_name ? ` · ${String(args.skill_name)}` : ''}`,
    badge: <span className="af-cat af-cat-plan"><Sparkles size={11} strokeWidth={2.1} /></span>,
  }),
  confirm_wf: () => ({ label: '工作流确认', badge: <CatBadge cat="plan" /> }),
};

function isErrorSafe(t: TimelineEntry): boolean { return t.toolStatus === 'error'; }
function BotIcon({ size, strokeWidth }: { size: number; strokeWidth: number }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round"><rect x="4" y="8" width="16" height="12" rx="2"/><path d="M12 8V4M8 4h8"/><circle cx="9" cy="14" r="1" fill="currentColor"/><circle cx="15" cy="14" r="1" fill="currentColor"/></svg>;
}
