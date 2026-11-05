/**
 * ChatPage — 对话主业（spec §2.3 定稿四栏）：
 * 会话列表 200 / 消息流（欢迎页 + 气泡 + 活动组 + 正文）/ 右面板 190（可收起）/ Composer。
 * 数据链路：agentApi(已发布列表) + sessionApi(会话 CRUD/历史) + useChatStream(SSE)。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { agentApi } from '../../services/agent-api';
import { modelApi, modelKeys } from '../../services/model-api';
import {
  sessionApi, sessionKeys,
  type MessageRecord, type Session, type TimelineEntryData,
} from '../../services/session-api';
import { useChatStream, isInterruptTool, type ChatMessage } from './useChatStream';
import { SessionSidebar } from './SessionSidebar';
import { ActivityGroup } from './ActivityGroup';
import { Composer, type ComposerState } from './Composer';
import { ContextPanel } from './ContextPanel';
import { Markdown } from './Markdown';
import { FlowMark } from '../../components/shell/FlowMark';
import { FileText } from 'lucide-react';
import type { TimelineEntry } from '../../types';

/* ── 历史 MessageRecord → ChatMessage（done 落库结构 → 展示结构）── */
function historyToMessages(records: MessageRecord[], agentName: string, avatar: string): ChatMessage[] {
  const out: ChatMessage[] = [];
  for (const rec of records) {
    const base: ChatMessage = {
      id: rec._id,
      senderName: rec.role === 'user' ? '我' : agentName,
      avatar: rec.role === 'user' ? '🙂' : avatar,
      role: rec.role,
      content: rec.content ?? '',
      timestamp: rec.created_at,
      usage: rec.token_usage,
      requestId: rec.request_id,
    };
    if (rec.role === 'user') { out.push(base); continue; }

    // agent：timeline_entries 顺序转换；tool_result 就近配对前面的 running tool_call
    const tl: TimelineEntry[] = [];
    for (let i = 0; i < (rec.timeline_entries ?? []).length; i++) {
      const e: TimelineEntryData = rec.timeline_entries[i];
      if (e.type === 'thinking' && e.content) {
        tl.push({ id: `h-tk-${i}`, type: 'thinking', content: e.content, expanded: false });
      } else if ((e.type === 'text' || e.type === 'final_answer') && e.content) {
        tl.push({ id: `h-tx-${i}`, type: 'text', content: e.content });
      } else if (e.type === 'tool' || e.type === 'tool_call') {
        tl.push({
          id: `h-tl-${i}`, type: 'tool', content: '',
          toolName: e.tool_name ?? '', args: e.args,
          toolCallId: e.id ?? '', toolStatus: 'running',
        });
      } else if (e.type === 'tool_result') {
        for (let j = tl.length - 1; j >= 0; j--) {
          const t = tl[j];
          if (t.type === 'tool' && t.toolStatus === 'running' &&
              (e.tool_call_id ? t.toolCallId === e.tool_call_id : t.toolName === e.tool_name)) {
            t.result = e.content ?? '';
            t.toolStatus = e.status === 'error' ? 'error' : 'success';
            break;
          }
        }
      }
      // interrupt/tool_call_start：中断卡由 tool entry 承载，不单独出条目
    }
    // 收敛未配对的 running（异常中断的历史）
    for (const t of tl) if (t.type === 'tool' && t.toolStatus === 'running') t.toolStatus = 'success';
    const interrupted = tl.some(
      (t) => t.type === 'tool' && !t.result && isInterruptTool(t.toolName),
    );
    out.push({ ...base, timeline: tl, isInterrupted: interrupted });
  }
  return out;
}

/* ── 页面 ─────────────────────────────────────────────────────── */
export function ChatPage() {
  const qc = useQueryClient();

  // 当前 Agent（默认取第一个已发布；Agent 切换器在欢迎页/头部 — P3.5）
  const { data: agentList } = useQuery({
    queryKey: ['agents', 'published'],
    queryFn: () => agentApi.list({ status: 'published', page_size: 20 }),
  });
  const agents = agentList?.items ?? [];
  // URL ?agent=<id> 指定初始 Agent（智能体列表「对话」入口跳转）
  const [searchParams] = useSearchParams();
  const urlAgentId = searchParams.get('agent');
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(urlAgentId);
  const agent = agents.find((a) => a.id === selectedAgentId) ?? agents[0] ?? null;

  const [sessionId, setSessionId] = useState<string | null>(null);
  // 输入草稿按会话保留（切会话不丢）
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const draftKey = sessionId ?? '__new__';
  const draft = drafts[draftKey] ?? '';
  const setDraft = useCallback((v: string) => setDrafts((d) => ({ ...d, [draftKey]: v })), [draftKey]);
  const [composer, setComposer] = useState<ComposerState>({ planMode: false, thinking: true, webSearch: false });

  const stream = useChatStream({
    agentId: agent?.id ?? '',
    agentName: agent?.name ?? 'Agent',
    agentAvatar: agent?.avatar ?? '🤖',
    onSessionBound: (sid) => {
      setSessionId(sid);
      qc.invalidateQueries({ queryKey: sessionKeys.lists() });
    },
    onFinished: () => {
      qc.invalidateQueries({ queryKey: sessionKeys.lists() });
      if (sessionId) qc.invalidateQueries({ queryKey: sessionKeys.files(sessionId) });
    },
  });

  // 切换会话 / 切换 Agent → 拉历史
  useEffect(() => {
    if (!sessionId || !agent) { stream.reset(); return; }
    let cancelled = false;
    sessionApi.getDetail(sessionId).then((d) => {
      if (!cancelled) stream.loadHistory(historyToMessages(d.messages ?? [], agent.name, agent.avatar));
    }).catch(() => stream.reset());
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, agent?.id]);

  // 模型人话名（default_model 存 id → 从模型配置解析 name）
  const { data: modelList } = useQuery({
    queryKey: modelKeys.lists(),
    queryFn: () => modelApi.list({ page_size: 50 }),
  });
  const modelName = useMemo(() => {
    const dm = agent?.default_model;
    if (!dm) return '';
    const m = modelList?.items?.find((x) => x.id === dm || x.model_id === dm);
    return m?.name ?? '';
  }, [agent?.default_model, modelList]);

  const send = useCallback((text: string) => {
    stream.send(text, { sessionId, planMode: composer.planMode, enableThinking: composer.thinking });
  }, [stream, sessionId, composer.planMode, composer.thinking]);
  // 澄清/审批回答：stream.send 内部按 pendingInterrupt 自动走 /resume
  const answer = useCallback((text: string) => {
    stream.send(text, { sessionId, planMode: composer.planMode, enableThinking: composer.thinking });
  }, [stream, sessionId, composer.planMode, composer.thinking]);

  const selectSession = (s: Session) => setSessionId(s._id);
  const newSession = useCallback(() => { setSessionId(null); stream.reset(); }, [stream]);

  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [ctxOpen, setCtxOpen] = useState(false); // 右面板默认收起（主人定稿）
  const [agentMenuOpen, setAgentMenuOpen] = useState(false);
  // 左右面板可拖拽调宽（原生实现，min/max 兜底）
  const left = useResizable(216, 180, 360);
  const right = useResizable(220, 180, 420);

  return (
    <div className="flex h-full min-w-0 flex-col bg-canvas">
      {/* 顶部横跨会话区+聊天区+右面板（主人要求：同一顶部、开关在顶部） */}
      <header className="flex h-12 flex-none items-center gap-2.5 border-b border-line bg-panel px-3.5">
          <button
            onClick={() => setSidebarOpen((v) => !v)}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-ink-dim transition-colors hover:bg-panel-hover hover:text-ink"
            title={sidebarOpen ? '收起会话列表' : '展开会话列表'}
          >
            <PanelIcon collapsed={!sidebarOpen} />
          </button>

          {/* Agent 切换器 */}
          <div className="relative">
            <button
              onClick={() => setAgentMenuOpen((v) => !v)}
              className="flex h-8 items-center gap-2 rounded-lg border border-line bg-well px-2 pr-2.5 transition-colors hover:border-line-strong"
            >
              <span
                className="flex items-center justify-center rounded-md text-[var(--color-on-brand)]"
                style={{ width: 22, height: 22, background: 'var(--color-brand)' }}
              >
                {agent?.avatar ? <b className="text-[11px]">{agent.avatar}</b> : <FlowMark size={13} />}
              </span>
              <b className="max-w-[160px] truncate text-[12.5px]">{agent?.name ?? '选择智能体'}</b>
              <span className="text-[9px] text-ink-faint">▾</span>
            </button>
            {agentMenuOpen && (
              <>
                <div className="fixed inset-0 z-10" onClick={() => setAgentMenuOpen(false)} />
                <div className="absolute left-0 top-10 z-20 max-h-72 w-64 overflow-y-auto rounded-xl border border-line bg-panel p-1.5 shadow-pop">
                  {agents.length === 0 && (
                    <div className="px-3 py-2.5 text-[12px] text-ink-dim">暂无已发布智能体</div>
                  )}
                  {agents.map((a) => (
                    <button
                      key={a.id}
                      onClick={() => {
                        setAgentMenuOpen(false);
                        if (a.id !== agent?.id) { setSelectedAgentId(a.id); newSession(); }
                      }}
                      className={`flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left transition-colors ${
                        a.id === agent?.id ? 'bg-brand-soft' : 'hover:bg-panel-hover'
                      }`}
                    >
                      <span
                        className="flex flex-none items-center justify-center rounded-md text-[12px] text-white"
                        style={{ width: 26, height: 26, background: 'linear-gradient(135deg, var(--color-brand-grad-from), var(--color-brand-grad-to))' }}
                      >
                        {a.avatar || '🤖'}
                      </span>
                      <span className="min-w-0 flex-1">
                        <b className="block truncate text-[12px] text-ink">{a.name}</b>
                        <span className="block truncate text-[10px] text-ink-dim">{a.description}</span>
                      </span>
                    </button>
                  ))}
                </div>
              </>
            )}
          </div>

          {composer.planMode && <span className="af-pill af-pill-success">📋 计划模式</span>}
          {stream.isStreaming && <span className="af-pill af-pill-brand">● 正在工作</span>}
          {stream.error && <span className="af-pill af-pill-danger" title={stream.error}>✗ 执行出错</span>}

          {/* 右侧：上下文面板开关 + 预留操作区（分享/导出/设置等后续功能） */}
          <div className="ml-auto flex items-center gap-1">
            <button
              onClick={() => setCtxOpen((v) => !v)}
              className={`flex h-8 w-8 items-center justify-center rounded-lg transition-colors ${
                ctxOpen ? 'bg-brand-soft text-brand' : 'text-ink-dim hover:bg-panel-hover hover:text-ink'
              }`}
              title={ctxOpen ? '关闭上下文面板' : '打开上下文面板'}
            >
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
                <rect x="1.5" y="2.5" width="13" height="11" rx="2" />
                <line x1="10.5" y1="2.5" x2="10.5" y2="13.5" />
              </svg>
            </button>
          </div>
        </header>

        {/* 三栏：会话列表(可拖宽) | 消息流 | 上下文面板(可拖宽) */}
        <div className="flex min-h-0 flex-1">
          {sidebarOpen && (
            <>
              <SessionSidebar activeSessionId={sessionId} onSelect={selectSession} onNew={newSession} width={left.w} agentId={agent?.id} />
              <Resizer onDown={left.startResize} />
            </>
          )}

          <section className="flex min-w-0 flex-1 flex-col bg-page">
            {stream.messages.length === 0 ? (
              <WelcomeScreen
            agentName={agent?.name}
            agents={agents} currentAgentId={agent?.id}
            onPickAgent={(id) => { setSelectedAgentId(id); newSession(); }}
            onPick={send}
          />
            ) : (
              <MessageList messages={stream.messages} streamingMsgId={stream.streamingMsgId} onAnswer={answer} sessionId={sessionId} />
            )}

            <div className="px-5">
              <div className="mx-auto w-full max-w-[820px]">
              <Composer
                agentName={agent?.name}
                agentModel={modelName}
                draft={draft}
                onDraftChange={setDraft}
                streaming={stream.isStreaming}
                disabled={!agent}
                onSend={send}
                onStop={stream.stop}
                state={composer}
                onStateChange={setComposer}
              />
              </div>
            </div>
          </section>

          {ctxOpen && (
            <>
              <Resizer onDown={right.startResize} side="right" />
              <ContextPanel sessionId={sessionId} messages={stream.messages} streaming={stream.isStreaming} width={right.w} />
            </>
          )}
        </div>
    </div>
  );
}

/* ── 原生拖拽调宽 ─────────────────────────────────────────────── */
function useResizable(initial: number, min: number, max: number) {
  const [w, setW] = useState(initial);
  const startResize = (e: React.MouseEvent, side: 'left' | 'right') => {
    e.preventDefault();
    const startX = e.clientX;
    const startW = w;
    const onMove = (ev: MouseEvent) => {
      const d = side === 'left' ? ev.clientX - startX : startX - ev.clientX;
      setW(Math.min(max, Math.max(min, startW + d)));
    };
    const onUp = () => {
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    };
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
  };
  return { w, startResize };
}

function Resizer({ onDown, side = 'left' }: { onDown: (e: React.MouseEvent, side: 'left' | 'right') => void; side?: 'left' | 'right' }) {
  return (
    <div
      onMouseDown={(e) => onDown(e, side)}
      className="group relative z-10 -mx-[3px] w-[6px] flex-none cursor-col-resize"
      title="拖拽调宽"
    >
      <div className="mx-auto h-full w-[2px] bg-transparent transition-colors group-hover:bg-brand/50" />
    </div>
  );
}

function PanelIcon({ collapsed }: { collapsed: boolean }) {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
      <rect x="1.5" y="2.5" width="13" height="11" rx="2" />
      {collapsed
        ? <path d="M10 5.5 L12.5 8 L10 10.5" strokeLinecap="round" strokeLinejoin="round" />
        : <line x1="10" y1="2.5" x2="10" y2="13.5" />}
    </svg>
  );
}

/* ── 消息列表 + 贴底跟随 ──────────────────────────────────────── */
function MessageList({ messages, streamingMsgId, onAnswer, sessionId }: {
  messages: ChatMessage[];
  streamingMsgId: string | null;
  onAnswer?: (text: string) => void;
  sessionId: string | null;
}) {
  const boxRef = useRef<HTMLDivElement>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const pinnedRef = useRef(true);
  const [pinned, setPinned] = useState(true);

  useEffect(() => {
    const box = boxRef.current;
    if (!box) return;
    const onScroll = () => {
      pinnedRef.current = box.scrollHeight - box.scrollTop - box.clientHeight < 80;
      setPinned(pinnedRef.current);
    };
    box.addEventListener('scroll', onScroll);
    return () => box.removeEventListener('scroll', onScroll);
  }, []);

  // 内容增长（新消息 / 流式正文）→ 贴底时自动跟随
  const last = messages[messages.length - 1];
  const lastLen = last?.timeline?.reduce((n, e) => n + (e.content?.length ?? 0), 0) ?? 0;
  useEffect(() => {
    if (pinnedRef.current) endRef.current?.scrollIntoView({ block: 'end' });
  }, [messages.length, lastLen]);
  // 用户发出新消息 → 无条件滚底（即使之前上翻了历史）
  useEffect(() => {
    if (last?.role === 'user') {
      pinnedRef.current = true;
      setPinned(true);
      endRef.current?.scrollIntoView({ block: 'end' });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [messages.length]);

  return (
    <div ref={boxRef} className="scrollbar-custom min-h-0 flex-1 overflow-y-auto px-5 py-4">
      {/* 消息列限宽居中：长文可读 + 左右交错的对话层次 */}
      <div className="mx-auto flex w-full max-w-[820px] flex-col gap-4">
        {messages.map((m) =>
          m.role === 'user'
            ? <UserBubble key={m.id} text={m.content} />
            : <AgentBubble key={m.id} msg={m} live={streamingMsgId === m.id} onAnswer={onAnswer} sessionId={sessionId} />,
        )}
      </div>
      <div ref={endRef} />

      {/* 跳到最新消息（未贴底时浮动） */}
      {!pinned && (
        <button
          onClick={() => { pinnedRef.current = true; setPinned(true); endRef.current?.scrollIntoView({ behavior: 'smooth' }); }}
          className="sticky bottom-2 left-1/2 z-10 flex -translate-x-1/2 items-center gap-1.5 rounded-full border border-line bg-panel px-3.5 py-1.5 text-[11.5px] font-semibold text-ink-soft shadow-pop transition-colors hover:text-brand"
        >
          ↓ 跳到最新消息
        </button>
      )}
    </div>
  );
}

function UserBubble({ text }: { text: string }) {
  return (
    <div
      title={new Date().toLocaleString('zh-CN')}
      className="ml-auto w-fit max-w-[78%] whitespace-pre-wrap rounded-xl rounded-br-sm px-4 py-2.5 text-[13.5px] leading-relaxed text-[var(--color-on-brand)]"
      style={{ background: 'var(--color-brand)' }}
    >
      {text}
    </div>
  );
}

function AgentBubble({ msg, live, onAnswer, sessionId }: {
  msg: ChatMessage;
  live: boolean;
  onAnswer?: (text: string) => void;
  sessionId: string | null;
}) {
  const all = msg.timeline ?? [];
  // 最终答案 = done 定稿后，最后一个 text entry 且其后无过程。
  // live 时正文位保持空 — 所有文本在活动组内时序流动，避免流式中位置跳变（主人报的混乱根因）
  const finalText = useMemo(() => {
    if (live) return null;
    for (let i = all.length - 1; i >= 0; i--) {
      const e = all[i];
      if (e.type === 'thinking' || e.type === 'tool') return null;
      if (e.type === 'text' && e.content) return e;
    }
    return null;
  }, [all, live]);
  const errorEntries = useMemo(() => all.filter((e) => e.type === 'error'), [all]);

  // 不再渲染头像：身份由顶部 Agent 切换器承载；消息与输入框同宽对齐（主人定稿）
  return (
    <div className="flex w-full min-w-0 flex-col gap-2">
        {/* 活动组（过程：思考/工具/中间文本；done 收成一行） */}
        <ActivityGroup msg={msg} live={live} onAnswer={onAnswer} />
        {/* 最终答案（Markdown + hover 操作） */}
        {finalText && (
          <div className="group/wrap w-full">
            <div className="w-full rounded-2xl rounded-tl-md border border-line bg-panel px-4 py-3 shadow-card">
              <Markdown content={finalText.content} />
            </div>
            <div className="mt-1 flex gap-3 px-1 text-[11px] text-ink-faint opacity-0 transition-opacity group-hover/wrap:opacity-100">
              <button
                onClick={() => navigator.clipboard?.writeText(finalText.content)}
                className="transition-colors hover:text-brand"
              >⧉ 复制</button>
            </div>
          </div>
        )}
        {/* Agent 产出文件（可下载） */}
        {(msg.attachments ?? []).filter((a) => a.source === 'output').map((a) => (
          <a
            key={a.ref}
            href={sessionId ? sessionApi.getDownloadUrl(sessionId, a.ref) : undefined}
            target="_blank"
            rel="noreferrer"
            className="af-card flex w-fit max-w-full items-center gap-2.5 px-3.5 py-2.5 text-[12px] text-ink-soft transition-colors hover:text-brand"
            title="点击下载/预览"
          >
            <span className="af-cat af-cat-file" style={{ width: 24, height: 24, borderRadius: 7 }}>
              <FileText size={13} strokeWidth={2} />
            </span>
            <span className="truncate font-medium">{a.name}</span>
            <span className="af-pill af-pill-success flex-none">产出文件 ↧</span>
          </a>
        ))}
        {/* 错误（永不折叠） */}
        {errorEntries.map((e) => (
          <div key={e.id} className="w-full rounded-xl border border-danger/30 bg-danger-soft px-3.5 py-2 text-[12.5px] text-danger">
            {e.content}
          </div>
        ))}
        {/* 流式起手占位 */}
        {live && all.length === 0 && (
          <div className="flex items-center gap-1.5 px-1 text-[12.5px] text-ink-dim">
            {[0, 1, 2].map((i) => (
              <i key={i} className="h-1.5 w-1.5 animate-thinking-dot rounded-full bg-brand" style={{ animationDelay: `${i * 0.18}s` }} />
            ))}
            正在思考…
          </div>
        )}
    </div>
  );
}

/* ── 欢迎页（空会话首屏，spec §2.3）───────────────────────────── */
function WelcomeScreen({ agentName, agents, currentAgentId, onPickAgent, onPick }: {
  agentName?: string;
  agents: { id: string; name: string; avatar: string; description: string }[];
  currentAgentId?: string;
  onPickAgent: (id: string) => void;
  onPick: (q: string) => void;
}) {
  const suggestions = [
    '帮我分析最近一周的数据并给出改进建议',
    '用计划模式制定一个执行方案，先给我审批',
    '调研一下行业最新动态，输出结构化报告',
  ];
  return (
    <div className="scrollbar-custom flex min-h-0 flex-1 flex-col items-center justify-center gap-5 overflow-y-auto px-6 py-6">
      <div
        className="flex h-14 w-14 flex-none items-center justify-center rounded-xl text-[var(--color-on-brand)] shadow-pop"
        style={{ background: 'var(--color-brand)' }}
      >
        <FlowMark size={24} />
      </div>
      <div className="text-center">
        <div className="af-label mb-1.5">AGENT CONSOLE</div>
        <div className="text-xl font-extrabold tracking-tight">{agentName ?? 'Agent Flow'}</div>
        <div className="mt-1 text-xs text-ink-dim">
          {agentName ? '已就绪 — 下达任务，或先开启计划模式再执行' : '选择一个智能体开始'}
        </div>
      </div>
      {/* Agent 快捷切换卡（spec §2.3 欢迎页定稿项） */}
      {agents.length > 0 && (
        <div className="grid w-full max-w-lg grid-cols-2 gap-2">
          {agents.slice(0, 4).map((a) => (
            <button
              key={a.id}
              onClick={() => onPickAgent(a.id)}
              className={`af-card flex items-center gap-2.5 px-3 py-2.5 text-left transition-all hover:-translate-y-px ${
                a.id === currentAgentId ? 'border-brand ring-1 ring-brand' : ''
              }`}
            >
              <span
                className="flex h-8 w-8 flex-none items-center justify-center rounded-lg text-[14px] text-[var(--color-on-brand)]"
                style={{ background: 'var(--color-brand)' }}
              >
                {a.avatar || <FlowMark size={15} />}
              </span>
              <span className="min-w-0">
                <b className="block truncate text-[12px] text-ink">{a.name}</b>
                <span className="block truncate text-[10px] text-ink-dim">{a.description || '—'}</span>
              </span>
            </button>
          ))}
        </div>
      )}
      <div className="flex w-full max-w-md flex-col gap-2">
        {suggestions.map((s) => (
          <button
            key={s}
            onClick={() => onPick(s)}
            className="af-card px-3.5 py-2.5 text-left text-[12px] text-ink-soft transition-all hover:-translate-y-px hover:text-brand"
          >
            {s}
          </button>
        ))}
      </div>
    </div>
  );
}
