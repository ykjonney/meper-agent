import { useState, useRef, useEffect, useLayoutEffect, useMemo, Fragment, FormEvent, useCallback, type MouseEvent, type ChangeEvent, type ReactNode } from 'react';
import { Agent, Message, type ChatAttachment, type TimelineEntry } from '../../types'
import {
  Send, Plus, Trash2, FileCode, CheckCircle, Check,
  Bot, Terminal, Loader2, Paperclip, Brain, X, ClipboardList, ShieldAlert,
  Wrench, AlertTriangle, ChevronRight, ChevronDown, User, Download, FileText, Image as ImageIcon, Copy, RotateCcw,
  PenLine, SquarePen, FolderSearch, Search, Globe, Link2, BarChart3, FileSearch, BookOpen,
  ThumbsUp, ThumbsDown, PanelRight, Workflow,
  FolderOpen, LayoutDashboard, Shield, ArrowLeftRight,
} from 'lucide-react';
import { toast } from '../ui/toast'
import { IconAgent, IconTask, IconFlow, IconResource } from '../IndigoIcons'
import { NotificationCenter } from '../notification-center'
import { useQuery, useQueryClient, useMutation } from '@tanstack/react-query';
import { Popover } from '../ui'
import { userSkillsApi, type SessionFeedbackItem } from '../../services/user-skills-api'
import {
  sessionApi, sessionKeys, type Session, type MessageRecord, type FileRef, getFileId,
} from '../../services/session-api';
import { agentApi, agentKeys, type DoneTimelineEntry, type ThinkingLevel } from '../../services/agent-api'
import { modelApi, modelKeys } from '../../services/model-api'
import { toStudioAgent } from '../../services/adapters'
import { getFileBlob, downloadFile as downloadFileById } from '../../services/file-api'
import { parseSSEStream } from '../../lib/sse-parser'
import { formatFileSize } from '../../lib/file-preview'
import { formatTimeFull } from '../../lib/formatTime'
import { isImeComposing } from '../../lib/keyboard'
import { countZi, truncateByZi } from '../../lib/text-stats'
import { SessionFilesPanel, type SessionFilesPanelHandle } from '../SessionFilesPanel'
import AvatarRender from '../AvatarRender'
import { Markdown } from '../Markdown'
import { detectPreviewKind } from '../FilePreview'
import { FilePreviewModal } from '../FilePreviewModal'
import { WorkflowTaskCard, parseTaskCreated } from '../WorkflowTaskCard'
import WorkflowProposalCard from '../workflow-proposal-card'
import {
  ClarificationFormCard,
  DISMISSED_CLARIFICATION_TEXT,
  type ClarificationField,
} from '../clarification-form-card';
import { ChatVoiceComposer } from '../voice/ChatVoiceComposer'
import { voiceConfigApi, voiceConfigKeys } from '../../services/voice-config-api'

// 思考档位元数据：label=档位文字，color=强度色（信号色 token，明暗主题自适应；
// off=灰 / low=绿 / medium=黄 / high=橙红）。

export const THINK_LEVELS = ['off', 'low', 'medium', 'high'] as const;
export const THINK_LEVEL_META: Record<ThinkingLevel, { label: string; color: string }> = {
  off: { label: '关', color: 'var(--color-ink-faint)' },
  low: { label: '低', color: 'var(--color-sig-ok)' },
  medium: { label: '中', color: 'var(--color-sig-wait)' },
  high: { label: '高', color: 'var(--color-sig-fail)' },
};
/** 上下文窗口 tokens → 紧凑显示（128000→"128k"，1000000→"1M"）。 */
export const fmtContextWindow = (n?: number): string => {
  if (!n) return '';
  if (n >= 1_000_000) return `${Math.round(n / 100_000) / 10}M`;
  return `${Math.round(n / 1000)}k`;
};

export const MORE_ICONS: Record<string, typeof LayoutDashboard> = {
  dashboard: LayoutDashboard,
  users: Shield,
  'external-auth': Link2,
  transfer: ArrowLeftRight,
  // 系统设置：改版后由侧栏底部独立齿轮承担（lucide Settings），不再进「更多」菜单
}

/** 侧栏主要功能 4 项（其余导航项收纳进「··· 更多」）；语义图标按 id 映射。 */
export const PRIMARY_NAV: { id: string; label: string; Icon: (p: { size?: number; className?: string }) => ReactNode }[] = [
  { id: 'agents', label: '智能体', Icon: IconAgent },
  { id: 'board', label: '任务', Icon: IconTask },
  { id: 'workflows', label: '工作流', Icon: IconFlow },
  { id: 'resource', label: '资源库', Icon: IconResource },
];

/** Convert a stored agent message + its timeline into display Messages. */
/**
 * 从工具结果文本里解析 agent 写出的 output 文件路径。
 * write_to_output 返回形如 "Successfully wrote 123 bytes to output/report.png"，
 * 路径相对 output/，即 sessionApi.previewFile 的 filePath 入参，无需二次转换。
 * 也可命中 "output/xxx" 字面量（agent 在 markdown 链接里引用产物时）。
 * 返回去重后的 ChatAttachment[]（source='output'）。
 */
export const OUTPUT_PATH_RE = /\boutput\/([^\s"'<>)\\]+\.[A-Za-z0-9]+)/g;

/**
 * 可挂起 interrupt 的工具名单（前端唯一事实源：历史重建/中断检测/忽略
 * 标记/答填/收敛五处匹配共用；与后端 MessageService._INTERRUPT_TOOL_NAMES
 * 保持一致——加新 HITL 工具时两侧同步）。
 */
export const INTERRUPT_TOOLS: ReadonlySet<string> = new Set([
  'ask_clarification',
  'confirm_workflow',
  'propose_plan',
]);
export const isInterruptTool = (name: unknown): boolean =>
  typeof name === 'string' && INTERRUPT_TOOLS.has(name);

/**
 * ① 计划工具清单提取：从计划文本识别将使用的工具/能力，审批卡警示条展示。
 * 审阅焦点从"步骤是否合理"（需领域知识）降到"会碰什么"（一眼可扫）——
 * 变更类（执行期才解锁）高亮警示。启发式匹配，宁缺勿滥（提示用，非强制）。
 */
export const PLAN_TOOL_HINTS: ReadonlyArray<{ label: string; mutating: boolean; re: RegExp }> = [
  { label: '命令执行 bash', mutating: true, re: /bash|shell|命令行|运行命令|执行命令|pip install|npm (install|run)|pytest|git (commit|push)/i },
  { label: '文件写入 write/edit', mutating: true, re: /write_file|edit_file|写入文件|修改文件|创建文件|覆盖文件/ },
  { label: '代码编排 run_code', mutating: true, re: /run_code/ },
  { label: '派发工作流', mutating: true, re: /dispatch_workflow|派发工作流|启动工作流|运行工作流/ },
  { label: '图表生成', mutating: true, re: /render_chart|绘制图表|生成图表/ },
  { label: '外部调用 HTTP/MCP', mutating: true, re: /webhook|https?:\/\/|api 调用|调用接口|调用 API|\bMCP\b/i },
  { label: '知识库检索', mutating: false, re: /kb_search|kb_read|知识库/ },
];
export const extractPlanToolHints = (plan: string) =>
  PLAN_TOOL_HINTS.filter((h) => h.re.test(plan));

export function parseOutputAttachments(text: string): ChatAttachment[] {
  if (!text) return [];
  const seen = new Set<string>();
  const out: ChatAttachment[] = [];
  for (const match of text.matchAll(OUTPUT_PATH_RE)) {
    const rel = match[1]; // 相对 output/ 的路径
    if (seen.has(rel)) continue;
    seen.add(rel);
    out.push({
      source: 'output',
      ref: rel,
      name: rel.split('/').pop() || rel,
    });
  }
  return out;
}

/** done 事件的权威终态 timeline（与落库同源）→ 展示 entries。流结束时整体
 *  替换流式累加结果——无论流过程发生何种漂移（resume 重放/事件重复），
 *  流结束瞬间与刷新后加载的持久化消息必然一致。旧后端不带 timeline 时
 *  由调用方维持原有行为。 */
export function doneTimelineToEntries(entries: DoneTimelineEntry[], msgId: string): TimelineEntry[] {
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
        type: 'tool',
        content: '',
        toolName: e.tool_name ?? '',
        args: e.args,
        toolCallId: e.id ?? '',
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
  // 收敛未配对的 running/pending（异常中断）为 success，与下方 done 收敛语义一致。
  for (const t of tl) {
    if (t.type === 'tool' && (t.toolStatus === 'running' || t.toolStatus === 'pending')) {
      t.toolStatus = 'success';
    }
  }
  return tl;
}

/** Convert a persisted backend agent MessageRecord into a single studio
 *  Message whose `timeline` carries text/tool/thinking/error entries in
 *  chronological order (mirrors frontend historyEntryToTimeline). Tool_call
 *  + tool_result are merged into one tool entry; an unanswered
 *  ask_clarification/confirm_workflow tool_call stays interactive
 *  (isInterrupted). Output-file attachments parsed from tool results are
 *  attached to the message. */
export function agentMessageToDisplay(rec: MessageRecord, agentName: string, avatar: string): Message {
  const timeline: TimelineEntry[] = [];
  // Map tool_call_id → index of the last pending tool_call entry (for merging
  // the matching tool_result). Prefer id over tool_name so parallel same-name
  // calls (e.g. two kb_search) pair correctly instead of overwriting each other.
  const pendingToolCalls = new Map<string, number>();
  const outputAtts: ChatAttachment[] = [];
  let isInterrupted = false;

  for (let i = 0; i < (rec.timeline_entries ?? []).length; i++) {
    const entry = (rec.timeline_entries ?? [])[i];
    if (entry.type === 'text' || entry.type === 'final_answer') {
      const t = (entry.content ?? '').trim();
      if (t) timeline.push({ id: `${rec._id}-text-${i}`, type: 'text', content: t });
    } else if (entry.type === 'thinking') {
      timeline.push({ id: `${rec._id}-think-${i}`, type: 'thinking', content: entry.content ?? '' });
    } else if ((entry.type as string) === 'error') {
      timeline.push({ id: `${rec._id}-err-${i}`, type: 'error', content: `❌ ${entry.content || '执行出错'}` });
    } else if (entry.type === 'tool_call' || entry.type === 'tool') {
      const name = entry.tool_name ?? '';
      // tool entry (already merged by backend) or tool_call (need merge).
      const isError =
        entry.type === 'tool' &&
        typeof entry.content === 'string' &&
        /\b(error|fail)/i.test(entry.content);
      const matched = isInterruptTool(name);
      const idx = timeline.push({
        id: `${rec._id}-tool-${name}-${i}`,
        type: 'tool',
        content: '',
        toolName: name,
        toolCallId: entry.id,
        args: entry.args,
        toolStatus: isInterruptTool
          ? 'success'
          : entry.type === 'tool'
            ? (isError ? 'error' : 'success')
            : 'running',
        result: entry.type === 'tool' ? entry.content : undefined,
      }) - 1;
      if (entry.type === 'tool_call') {
        // Prefer tool_call_id; fall back to tool_name for older records.
        const mapKey = entry.id || name;
        if (mapKey) pendingToolCalls.set(mapKey, idx);
      }
      // 收集 output 产物。
      if (entry.type === 'tool' && typeof entry.content === 'string') {
        outputAtts.push(...parseOutputAttachments(entry.content));
      }
    } else if (entry.type === 'tool_result') {
      const name = entry.tool_name ?? '';
      // 真正的 fallback：status 存在时以它为准（success 时内容含 error 字样
      // 也不得误判——此前实现是 ||，正常返回的文档片段/日志被标失败）；
      // 仅旧数据（无 status）才文本嗅探。
      const isError =
        entry.status != null
          ? entry.status === 'error'
          : typeof entry.content === 'string' && /\b(error|fail)/i.test(entry.content);
      // Prefer tool_call_id; fall back to tool_name for older records.
      const mapKey = entry.tool_call_id || name;
      const pendingIdx = mapKey ? pendingToolCalls.get(mapKey) : undefined;
      if (pendingIdx !== undefined && timeline[pendingIdx]) {
        timeline[pendingIdx] = {
          ...timeline[pendingIdx],
          result: entry.content ?? '',
          toolStatus: isError ? 'error' : 'success',
        };
        pendingToolCalls.delete(mapKey);
      } else {
        timeline.push({
          id: `${rec._id}-tool-${name}-${i}`,
          type: 'tool',
          content: '',
          toolName: name,
          toolCallId: entry.tool_call_id,
          result: entry.content ?? '',
          toolStatus: isError ? 'error' : 'success',
        });
      }
      if (typeof entry.content === 'string') {
        outputAtts.push(...parseOutputAttachments(entry.content));
      }
    }
    // tool_call_start / interrupt are transient — skip in history.
  }

  // 未答的 ask_clarification/confirm_workflow（tool_call 无 tool_result）→ 中断态。
  for (const e of timeline) {
    if (
      e.type === 'tool' &&
      isInterruptTool(e.toolName) &&
      !e.result
    ) {
      isInterrupted = true;
      break;
    }
  }

  const dedupOutput = outputAtts.filter(
    (a, i, arr) => arr.findIndex((b) => b.ref === a.ref) === i,
  );

  return {
    id: rec._id,
    senderName: agentName,
    avatar,
    role: 'agent',
    content: '',
    timestamp: formatTimeFull(rec.created_at),
    requestId: rec.request_id,
    timeline: timeline.length > 0 ? timeline : undefined,
    isInterrupted,
    attachment: fileRefToAttachment(rec.files?.[0]),
    attachments: dedupOutput.length > 0 ? dedupOutput : undefined,
    usage: rec.token_usage,
  };
}

export function fileRefToAttachment(file?: FileRef): Message['attachment'] | undefined {
  if (!file) return undefined;
  const name = file.name;
  const mime = file.mime_type ?? '';
  const type: Message['attachment']['type'] = mime.startsWith('image/')
    ? 'image'
    : mime.startsWith('video/')
      ? 'video'
      : mime.includes('markdown') || name.endsWith('.md')
        ? 'markdown'
        : 'code';
  return { name, type, content: file.storage_key || name };
}

/* ─── 对话内附件预览（用户上传 + agent 产出统一渲染） ─── */

/** 按 source 取 blob：upload 走 FileRef.id，output 走 session output 路径。 */
export async function fetchAttachmentBlob(att: ChatAttachment, sessionId: string | null): Promise<Blob> {
  if (att.source === 'upload') {
    return getFileBlob(att.ref);
  }
  if (!sessionId) throw new Error('会话未加载，无法预览产出文件');
  const { blob } = await sessionApi.previewFile(sessionId, att.ref);
  return blob;
}

/** 下载附件：upload 用 file-api（<a download>），output 用 sessionApi.downloadFile。 */
export async function downloadAttachment(att: ChatAttachment, sessionId: string | null): Promise<void> {
  if (att.source === 'upload') {
    await downloadFileById(att.ref, att.name);
    return;
  }
  if (!sessionId) throw new Error('会话未加载，无法下载产出文件');
  await sessionApi.downloadFile(sessionId, att.ref);
}

/**
 * 单个附件的内联展示：图片懒加载缩略图直显，其余类型显示文件卡片。
 * 点击图片或「预览」打开 FilePreviewModal（复用，支持缩放/Esc/富渲染/下载）。
 * 需要父级传入 sessionId（output 来源取数依赖）。
 */
export function updateMsg(
  prev: Message[],
  id: string,
  patch: Partial<Message>,
): Message[] {
  return prev.map((m) => (m.id === id ? { ...m, ...patch } : m));
}

export function formatSessionTime(iso: string): string {
  try {
    const d = new Date(iso);
    const now = Date.now();
    const diff = now - d.getTime();
    if (diff < 60_000) return '刚刚';
    if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}分钟前`;
    if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}小时前`;
    return d.toLocaleDateString();
  } catch {
    return '';
  }
}

/* ────────────────────────────────────────────────────────────
   Tool-call rendering helpers + ToolCallCard
   Mirrors the structured tool card from frontend/src/components/chat-panel.tsx:
   a status-colored header (running/success/error) with a collapsible detail
   pane showing formatted request args + return result.
   ──────────────────────────────────────────────────────────── */

/** Per-status visual config. Uses Tailwind opacity color tokens so it renders
 *  correctly in both dark and light themes (no raw hex). `hover` deepens the
 *  same status color slightly (→ /15) for a subtle, theme-safe lift instead of
 *  overlaying an unrelated neutral that looks jarring on a colored card. */

export function userMessageToDisplay(rec: MessageRecord): Message {
  // 全部附件（非仅首个）映射成可预览 ChatAttachment；source='upload' 走 getFileBlob(id)
  const attachments: ChatAttachment[] | undefined =
    rec.files && rec.files.length > 0
      ? rec.files.map((f) => ({
          source: 'upload' as const,
          ref: getFileId(f),
          name: f.name,
          mime_type: f.mime_type,
          size: f.size,
        }))
      : undefined;
  return {
    id: rec._id,
    senderName: '我',
    avatar: '👩‍💼',
    role: 'user',
    content: rec.content,
    timestamp: formatTimeFull(rec.created_at),
    attachment: fileRefToAttachment(rec.files?.[0]),
    attachments,
  };
}


/** 数值夹取到 [lo, hi]（侧栏/产物面板拖拽宽度用） */
export function clamp(v: number, lo: number, hi: number) {
  return Math.min(hi, Math.max(lo, v));
}
