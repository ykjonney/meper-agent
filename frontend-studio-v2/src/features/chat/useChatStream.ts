/**
 * useChatStream — 对话核心状态机（v2）。
 *
 * 逻辑提取自 v1 ChatHomepage.tsx 的 SSE 消费段（thinking/tool/text/interrupt/
 * done 全事件语义保持一致，含 RAF delta 批处理与 toolCallId 精确配对），
 * UI 无关；活动组「单步即时收纳」的展示规则在 ActivityGroup.tsx 派生。
 */
import { useCallback, useRef, useState } from 'react';
import { parseSSEStream } from '../../lib/sse-parser';
import { agentApi, type DoneTimelineEntry } from '../../services/agent-api';
import type { ChatAttachment, Message, TimelineEntry } from '../../types';

/** v2 聊天消息：Message + 流式计时（活动组「已工作 Xs」用） */
export interface ChatMessage extends Message {
  /** 本轮流式开始时刻（Date.now()）；历史回放无此字段 */
  streamStartedAt?: number;
  /** done 时的总耗时 ms；历史回放无 */
  elapsedMs?: number;
}

/** 挂起 interrupt 的工具名单（与 v1 一致：历史重建/中断检测的唯一事实源） */
export const INTERRUPT_TOOLS = ['ask_clarification', 'confirm_workflow', 'propose_plan'];
export const isInterruptTool = (name?: string): boolean => !!name && INTERRUPT_TOOLS.includes(name);

const OUTPUT_PATH_RE = /\boutput\/([^\s"'<>)\\]+\.[A-Za-z0-9]+)/g;

/** 从工具结果里解析 output/ 产出文件（v1 同款） */
export function parseOutputAttachments(text: string): ChatAttachment[] {
  if (!text) return [];
  const seen = new Set<string>();
  const out: ChatAttachment[] = [];
  for (const match of text.matchAll(OUTPUT_PATH_RE)) {
    const rel = match[1];
    if (seen.has(rel)) continue;
    seen.add(rel);
    out.push({ source: 'output', ref: rel, name: rel.split('/').pop() || rel });
  }
  return out;
}

/** done 事件的权威 timeline → 展示 entries（v1 同款） */
function doneTimelineToEntries(entries: DoneTimelineEntry[], msgId: string): TimelineEntry[] {
  const tl: TimelineEntry[] = [];
  let seq = 0;
  for (const e of entries) {
    if (e.type === 'thinking' && e.content) {
      tl.push({ id: `${msgId}-f-think-${seq++}`, type: 'thinking', content: e.content, expanded: false });
    } else if ((e.type === 'text' || e.type === 'final_answer') && e.content) {
      tl.push({ id: `${msgId}-f-text-${seq++}`, type: 'text', content: e.content });
    } else if (e.type === 'error' && e.content) {
      tl.push({ id: `${msgId}-f-err-${seq++}`, type: 'error', content: `❌ ${e.content}` });
    } else if (e.type === 'tool_call' || e.type === 'tool') {
      tl.push({
        id: `${msgId}-f-tool-${seq++}`,
        type: 'tool', content: '',
        toolName: e.tool_name ?? '', args: e.args, toolCallId: e.id ?? '',
        toolStatus: e.type === 'tool' ? 'success' : 'running',
      });
    } else if (e.type === 'tool_result') {
      const rid = e.tool_call_id ?? '';
      for (let i = tl.length - 1; i >= 0; i--) {
        const t = tl[i];
        if (
          t.type === 'tool' && t.toolStatus === 'running' &&
          (rid ? t.toolCallId === rid : t.toolName === e.tool_name)
        ) {
          t.result = e.content;
          t.toolStatus = e.is_error === true || e.status === 'error' ? 'error' : 'success';
          break;
        }
      }
    }
  }
  for (const t of tl) {
    if (t.type === 'tool' && (t.toolStatus === 'running' || t.toolStatus === 'pending')) {
      t.toolStatus = 'success';
    }
  }
  return tl;
}

export interface SendOptions {
  sessionId: string | null;
  planMode?: boolean;
  enableThinking?: boolean;
  /** 回答挂起的 interrupt（澄清/计划反馈）时必传目标消息 id */
  resumeMessageId?: string;
  fileIds?: string[];
  filePaths?: string[];
}

export function useChatStream(opts: {
  agentId: string;
  agentName: string;
  agentAvatar: string;
  /** 流中新建会话后回调（后端在首个请求时创建会话，done 携带 session_id） */
  onSessionBound?: (sessionId: string) => void;
  onFinished?: () => void;
}) {
  const { agentId, agentName, agentAvatar, onSessionBound, onFinished } = opts;
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamingMsgId, setStreamingMsgId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const abortRef = useRef<AbortController | null>(null);
  // text_delta RAF 批处理（v1 同款：buffer + rAF 合并尾巴进当前 text entry）
  const deltaBufRef = useRef<{ text: string } | null>(null);
  const rafIdRef = useRef<number | null>(null);
  // 挂起的 interrupt（下次 send 走 /resume）
  const pendingInterruptRef = useRef<{ toolMsgId: string } | null>(null);

  const patchMessage = useCallback((id: string, fn: (m: ChatMessage) => ChatMessage) => {
    setMessages((prev) => prev.map((m) => (m.id === id ? fn(m) : m)));
  }, []);

  const flushDelta = useCallback((msgId: string) => {
    const buf = deltaBufRef.current;
    if (!buf || !buf.text) return;
    const text = buf.text;
    deltaBufRef.current = null;
    if (rafIdRef.current) { cancelAnimationFrame(rafIdRef.current); rafIdRef.current = null; }
    patchMessage(msgId, (m) => {
      const tl = [...(m.timeline ?? [])];
      // 并入规则：仅当「最后一条」是 text 才追加（当前轮延续）；
      // 否则（中间隔着 thinking/tool）开新 entry —— 多轮文本严格保持时序位置，
      // 修复从后往前误并入第一轮文本导致的段落错位。
      const last = tl[tl.length - 1];
      if (last && last.type === 'text') {
        tl[tl.length - 1] = { ...last, content: last.content + text };
      } else {
        tl.push({ id: `${msgId}-text-${Date.now()}`, type: 'text', content: text });
      }
      return { ...m, timeline: tl };
    });
  }, [patchMessage]);

  const stop = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  const send = useCallback(async (prompt: string, o: SendOptions) => {
    if (!prompt.trim() || isStreaming) return;
    setError(null);

    const userMsg: ChatMessage = {
      id: `u-${Date.now()}`, senderName: '我', avatar: '🙂', role: 'user',
      content: prompt, timestamp: new Date().toISOString(),
    };
    const agentMsgId = `a-${Date.now()}`;
    const agentMsg: ChatMessage = {
      id: agentMsgId, senderName: agentName, avatar: agentAvatar, role: 'agent',
      agentId, content: '', timestamp: new Date().toISOString(),
      status: 'thinking', timeline: [], streamStartedAt: Date.now(),
    };

    // resume 判定（v1 同款）：显式指定 或 最近一条中断消息
    const resumeMsgId = o.resumeMessageId
      ?? pendingInterruptRef.current?.toolMsgId
      ?? [...messages].reverse().find((m) => m.isInterrupted)?.id;
    const isResume = !!resumeMsgId;

    if (isResume && resumeMsgId) {
      // 回答注入旧中断卡片的 tool entry 作为 result，不渲染独立用户气泡
      setMessages((prev) => prev.map((m) => {
        if (m.id !== resumeMsgId) return m;
        let answered = false;
        const tl = (m.timeline ?? []).map((e) => {
          if (!answered && e.type === 'tool' && isInterruptTool(e.toolName) && !e.result) {
            answered = true;
            return { ...e, result: prompt, toolStatus: 'success' as const };
          }
          return e;
        });
        return { ...m, isInterrupted: false, timeline: tl };
      }).concat(agentMsg));
    } else {
      setMessages((prev) => [...prev, userMsg, agentMsg]);
    }
    pendingInterruptRef.current = null;
    setIsStreaming(true);
    setStreamingMsgId(agentMsgId);

    const controller = new AbortController();
    abortRef.current = controller;
    deltaBufRef.current = null;

    try {
      const res = isResume
        ? await agentApi.resume(agentId, {
            session_id: o.sessionId ?? '',
            // resume 的 answer 不允许为空：只贴图不打字时占位让请求可过
            answer: prompt || '(用户上传了附件)',
            enable_thinking: o.enableThinking ?? true,
            plan_mode: o.planMode || undefined,
          }, controller.signal)
        : await agentApi.stream(agentId, {
            input: prompt,
            session_id: o.sessionId ?? undefined,
            enable_thinking: o.enableThinking ?? true,
            plan_mode: o.planMode || undefined,
            file_ids: o.fileIds?.length ? o.fileIds : undefined,
            file_paths: o.filePaths?.length ? o.filePaths : undefined,
          }, controller.signal);

      if (!res.ok) {
        let detail = `HTTP ${res.status}`;
        try {
          const body = await res.json();
          detail = body?.error?.message ?? body?.message ?? detail;
        } catch { /* ignore */ }
        throw new Error(detail);
      }

      // ── SSE 消费（事件语义与 v1 一致）──────────────────────────
      let streamedAtts: ChatAttachment[] = [];
      let thinkingText = '';
      let thinkingEntryId: string | null = null;

      for await (const evt of parseSSEStream(res)) {
        if (controller.signal.aborted) break;

        if (!('type' in evt)) {
          // done：绑定新会话 + 权威 timeline 替换 + 计时收尾
          if (!o.sessionId && evt.session_id) onSessionBound?.(evt.session_id);
          onFinished?.();
          const finalTimeline = evt.timeline ? doneTimelineToEntries(evt.timeline, agentMsgId) : null;
          patchMessage(agentMsgId, (m) => {
            const tl = finalTimeline ?? (m.timeline ?? []).map((e) =>
              e.type === 'tool' &&
              (e.toolStatus === 'pending' || e.toolStatus === 'running') &&
              !isInterruptTool(e.toolName) && e.toolName !== ''
                ? { ...e, toolStatus: 'success' as const }
                : e,
            );
            return {
              ...m, status: undefined, timeline: tl,
              usage: evt.usage ?? m.usage,
              requestId: evt.request_id || m.requestId,
              elapsedMs: m.streamStartedAt ? Date.now() - m.streamStartedAt : undefined,
            };
          });
          continue;
        }

        switch (evt.type) {
          case 'thinking':
          case 'thinking_delta': {
            // thinking = 权威全文（覆盖）；thinking_delta = 增量（追加）。
            // final 即本轮思考结束：写入全文并收起（活动组按 expanded=false 渲染为单行）。
            const isFinal = evt.type === 'thinking';
            thinkingText = isFinal ? evt.content : thinkingText + evt.content;
            const text = thinkingText;
            const pushId: string = thinkingEntryId
              ?? `${agentMsgId}-think-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
            thinkingEntryId = pushId;
            if (isFinal) { thinkingText = ''; thinkingEntryId = null; }
            const now = Date.now();
            patchMessage(agentMsgId, (m) => {
              const tl = [...(m.timeline ?? [])];
              const idx = tl.findIndex((e) => e.id === pushId);
              if (idx >= 0) {
                tl[idx] = {
                  ...tl[idx], content: text,
                  // final = 本轮思考结束：结算本地计时「思考了 Xs」
                  _ms: isFinal && tl[idx]._t0 ? now - tl[idx]._t0 : tl[idx]._ms,
                  expanded: isFinal && !tl[idx].userToggled ? false : tl[idx].expanded,
                };
              } else {
                tl.push({ id: pushId, type: 'thinking', content: text, expanded: !isFinal, _t0: now });
              }
              // final 清 status：工具执行期间不得显示"思考中"（v1 踩坑注释保留）
              return { ...m, status: isFinal ? undefined : 'thinking', timeline: tl };
            });
            break;
          }
          case 'tool_call_start': {
            flushDelta(agentMsgId);
            const toolName = evt.tool_name || '';
            const toolEntryId = `${agentMsgId}-tool-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
            patchMessage(agentMsgId, (m) => {
              const tl = [...(m.timeline ?? [])];
              tl.push({ id: toolEntryId, type: 'tool', content: '', toolName, toolStatus: 'pending' });
              return { ...m, status: undefined, timeline: tl };
            });
            break;
          }
          case 'tool_call': {
            // tool_call 在 final thinking 之后到达：兜底重置思考累积
            thinkingText = ''; thinkingEntryId = null;
            flushDelta(agentMsgId);
            patchMessage(agentMsgId, (m) => {
              const tl = [...(m.timeline ?? [])];
              const idx = tl.findIndex((e) => e.type === 'tool' && e.toolStatus === 'pending');
              const now = Date.now();
              if (idx >= 0) {
                tl[idx] = {
                  ...tl[idx], toolName: evt.tool_name, toolCallId: evt.id,
                  args: evt.args, toolStatus: 'running', _t0: tl[idx]._t0 ?? now,
                };
              } else {
                tl.push({
                  id: `${agentMsgId}-tool-${now}`, type: 'tool', content: '',
                  toolName: evt.tool_name, toolCallId: evt.id, args: evt.args,
                  toolStatus: 'running', _t0: now,
                });
              }
              return { ...m, timeline: tl };
            });
            break;
          }
          case 'tool_result': {
            const isError = evt.status === 'error';
            const tcid = evt.tool_call_id;
            const newAtts = parseOutputAttachments(evt.content);
            for (const a of newAtts) {
              if (!streamedAtts.some((b) => b.ref === a.ref)) streamedAtts.push(a);
            }
            patchMessage(agentMsgId, (m) => {
              const tl = [...(m.timeline ?? [])];
              for (let i = tl.length - 1; i >= 0; i--) {
                const e = tl[i];
                if (
                  e.type === 'tool' && e.toolStatus === 'running' &&
                  (tcid ? e.toolCallId === tcid : e.toolName === evt.tool_name)
                ) {
                  tl[i] = {
                    ...e, result: evt.content,
                    toolStatus: isError ? 'error' : 'success',
                    _ms: e._t0 ? Date.now() - e._t0 : e._ms,
                  };
                  break;
                }
              }
              return {
                ...m, timeline: tl,
                attachments: streamedAtts.length > 0 ? [...streamedAtts] : m.attachments,
              };
            });
            break;
          }
          case 'text_delta': {
            // RAF 批处理：buffer 累积，rAF 里 flush（正文一出 → 活动组自动收纳）
            if (!deltaBufRef.current) deltaBufRef.current = { text: '' };
            deltaBufRef.current.text += evt.content;
            if (!rafIdRef.current) {
              rafIdRef.current = requestAnimationFrame(() => {
                rafIdRef.current = null;
                flushDelta(agentMsgId);
              });
            }
            break;
          }
          case 'text': {
            // 权威全文：覆盖最后一个 text entry
            if (evt.content) {
              if (rafIdRef.current) { cancelAnimationFrame(rafIdRef.current); rafIdRef.current = null; }
              deltaBufRef.current = null;
              patchMessage(agentMsgId, (m) => {
                const tl = [...(m.timeline ?? [])];
                let found = false;
                for (let i = tl.length - 1; i >= 0; i--) {
                  if (tl[i].type === 'text') { tl[i] = { ...tl[i], content: evt.content }; found = true; break; }
                }
                if (!found) tl.push({ id: `${agentMsgId}-text-${Date.now()}`, type: 'text', content: evt.content });
                return { ...m, status: undefined, timeline: tl };
              });
            }
            break;
          }
          case 'error': {
            const errContent = evt.content || '执行出错';
            setError(errContent);
            patchMessage(agentMsgId, (m) => {
              const tl = [...(m.timeline ?? [])];
              tl.push({ id: `${agentMsgId}-err-${Date.now()}`, type: 'error', content: `❌ ${errContent}` });
              return { ...m, status: 'error', timeline: tl };
            });
            break;
          }
          case 'interrupt': {
            // ask_clarification / propose_plan 挂起：后端权威字段回填 args（v1 同款）
            patchMessage(agentMsgId, (m) => {
              const tl = [...(m.timeline ?? [])];
              for (let i = tl.length - 1; i >= 0; i--) {
                const e = tl[i];
                if (e.type === 'tool' && !e.result && isInterruptTool(e.toolName)) {
                  if (e.toolName === 'ask_clarification') {
                    const args = { ...e.args };
                    if (!args.question && evt.question) args.question = evt.question;
                    if (!args.clarification_type && evt.clarification_type) args.clarification_type = evt.clarification_type;
                    if (args.context == null && evt.context != null) args.context = evt.context;
                    if (args.options == null && evt.options != null) args.options = evt.options;
                    if (args.fields == null && evt.fields != null) args.fields = evt.fields;
                    tl[i] = { ...e, args, toolStatus: 'success' };
                  } else if (e.toolName === 'propose_plan') {
                    const args = { ...e.args };
                    if (!args.plan && evt.plan) args.plan = evt.plan;
                    tl[i] = { ...e, args, toolStatus: 'success' };
                  } else if (e.toolName === 'confirm_workflow') {
                    // 回填工作流确认的权威字段（名称/描述/入参预览/问题）
                    const args = { ...e.args };
                    if (!args.question && evt.question) args.question = evt.question;
                    if (!args.workflow_name && evt.workflow_name) args.workflow_name = evt.workflow_name;
                    if (!args.description && evt.workflow_description) args.description = evt.workflow_description;
                    if (args.input_preview == null && evt.input_preview != null) args.input_preview = evt.input_preview;
                    tl[i] = { ...e, args, toolStatus: 'success' };
                  } else {
                    tl[i] = { ...e, toolStatus: 'success' };
                  }
                  break;
                }
              }
              return { ...m, isInterrupted: true, timeline: tl };
            });
            pendingInterruptRef.current = { toolMsgId: agentMsgId };
            break;
          }
          default:
            break;
        }
      }
    } catch (err) {
      if ((err as Error).name !== 'AbortError') {
        const msg = (err as Error).message || '连接中断';
        setError(msg);
        patchMessage(agentMsgId, (m) => {
          const tl = [...(m.timeline ?? [])];
          tl.push({ id: `${agentMsgId}-err-${Date.now()}`, type: 'error', content: `❌ ${msg}` });
          return { ...m, status: 'error', timeline: tl };
        });
      }
    } finally {
      if (rafIdRef.current) { cancelAnimationFrame(rafIdRef.current); rafIdRef.current = null; }
      flushDelta(agentMsgId);
      setIsStreaming(false);
      setStreamingMsgId(null);
      abortRef.current = null;
      // 收尾：计时 + running/pending 工具收敛（用户停止/连接断开不留永久转轮）
      patchMessage(agentMsgId, (m) => ({
        ...m,
        elapsedMs: m.elapsedMs ?? (m.streamStartedAt ? Date.now() - m.streamStartedAt : undefined),
        status: undefined,
        timeline: (m.timeline ?? []).map((e) =>
          e.type === 'tool' && (e.toolStatus === 'running' || e.toolStatus === 'pending')
            ? { ...e, toolStatus: 'error' as const, result: e.result ?? '⏹ 已由用户停止' }
            : e,
        ),
      }));
    }
  }, [agentId, agentName, agentAvatar, isStreaming, messages, patchMessage, flushDelta, onSessionBound, onFinished]);

  /** 历史回放（session detail）注入 */
  const loadHistory = useCallback((history: ChatMessage[]) => {
    setMessages(history);
  }, []);

  /** 清空（新建会话） */
  const reset = useCallback(() => {
    abortRef.current?.abort();
    setMessages([]);
    setError(null);
    pendingInterruptRef.current = null;
  }, []);

  return { messages, isStreaming, streamingMsgId, error, send, stop, loadHistory, reset };
}
