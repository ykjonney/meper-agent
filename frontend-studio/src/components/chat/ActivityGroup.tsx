import { useState, useRef, useEffect, useLayoutEffect, useMemo, Fragment, FormEvent, useCallback, type MouseEvent, type ChangeEvent, type ReactNode } from 'react';
import { Agent, Message, type ChatAttachment, type TimelineEntry } from '../../types'
import {
  Send, Plus, Trash2, FileCode, CheckCircle, Check,
  Bot, Terminal, Loader2, Paperclip, Brain, X, ClipboardList, ShieldAlert,
  Wrench, AlertTriangle, ChevronRight, ChevronDown, User, Download, FileText, Image as ImageIcon, Mic, Copy, RotateCcw,
  PenLine, SquarePen, FolderSearch, Search, Globe, Link2, BarChart3, FileSearch, BookOpen,
  ThumbsUp, ThumbsDown, PanelRight, Workflow,
  FolderOpen, LayoutDashboard, Shield, ArrowLeftRight, Key,
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
import { ThinkingEntryCard, ToolEntryCard } from './ToolEntryCard';
import { isInteractiveTool } from './tool-details';

export function StreamingDots() {
  return (
    <span className="inline-flex items-center gap-[3px] align-baseline" aria-hidden="true">
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className="w-1 h-1 rounded-full bg-brand animate-thinking-dot"
          style={{ animationDelay: `${i * 0.18}s` }}
        />
      ))}
    </span>
  );
}

/** Thinking entry — collapsible reasoning card with streaming animation.
 *  内容区固定最大高度（内部滚动），避免长思考撑爆版面；流式期间内部
 *  贴底跟随（终端效果），思考结束自动收起。 */
/**
 * 工具调用单行人话摘要（参考主流 agent UI：动词 + 关键参数，超长截断）。
 * 不同工具取不同参数作为摘要主体，避免把整个 args JSON 糊给用户。
 */
export function ParallelToolBatch({ entries, msgId }: { entries: TimelineEntry[]; msgId: string }) {
  const anyRunning = entries.some(
    (e) => e.toolStatus === 'running' || e.toolStatus === 'pending',
  );
  const [open, setOpen] = useState(anyRunning);
  const prevRunning = useRef(anyRunning);
  useEffect(() => {
    if (prevRunning.current !== anyRunning) {
      prevRunning.current = anyRunning;
      setOpen(anyRunning);
    }
  }, [anyRunning]);

  const doneCount = entries.filter((e) => e.toolStatus === 'success').length;
  const failCount = entries.filter((e) => e.toolStatus === 'error').length;

  return (
    <div className="rounded-lg bg-raise/60 overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-2 px-2.5 py-1.5 border-0 bg-transparent text-left cursor-pointer text-[12px] text-ink-dim hover:text-ink transition-colors"
      >
        {anyRunning ? (
          <Loader2 className="w-3 h-3 animate-spin text-sig-wait shrink-0" />
        ) : failCount > 0 ? (
          <AlertTriangle className="w-3 h-3 text-sig-fail shrink-0" />
        ) : (
          <CheckCircle className="w-3 h-3 text-ink-faint shrink-0" />
        )}
        执行了 {entries.length} 个工具
        {anyRunning ? (
          <span className="text-[10.5px] text-ink-faint font-mono">· 执行中</span>
        ) : failCount > 0 ? (
          <span className="text-[10.5px] text-sig-fail font-mono">· {failCount} 失败</span>
        ) : (
          <span className="text-[10.5px] text-ink-faint font-mono">· 已完成</span>
        )}
        <ChevronRight
          className={`w-3 h-3 ml-auto transition-transform shrink-0 ${open ? 'rotate-90' : ''}`}
        />
      </button>
      <div
        className={`grid transition-[grid-template-rows] duration-300 ease-out ${open ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'}`}
      >
        <div className="overflow-hidden min-h-0">
          <div className="pb-1.5 space-y-0.5">
            {entries.map((entry, ei) => (
              <ToolEntryCard
                key={`te-${ei}`}
                entry={entry}
                msgId={msgId}
                interrupted={false}
                theme="dark"
                planVersion={undefined}
              />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

/**
 * ActivityGroup — 执行过程组：连续的 thinking/tool 调用合并为一张卡。
 * - 运行中：自动展开实时明细
 * - 全部完成：自动收起为组头一行（执行过程 · N 个工具调用 · 已完成）
 * - 用户手动展开/收起后，仅在运行状态跃迁时跟随一次
 */
export function ActivityGroup({
  entries,
  msgId,
  interrupted,
  theme,
  thinkingActive,
  hasOwnText,
  msgStreaming,
  onAnswer,
  onDismiss,
  onApprovePlan,
  planVersion,
}: {
  entries: TimelineEntry[];
  msgId: string;
  interrupted: boolean;
  theme: 'dark' | 'light';
  /** 消息是否仍处于思考态（空 thinking 保留动效的判据） */
  thinkingActive?: boolean;
  /** 本轮正文已开始输出 → 该轮活动组收起（答案开始才折叠过程） */
  hasOwnText?: boolean;
  /** 消息整体是否仍在流式输出（inFlight） */
  msgStreaming?: boolean;
  onAnswer?: (answer: string) => void;
  onDismiss?: () => void;
  onApprovePlan?: (plan: string) => void;
  planVersion?: number;
}) {
  // 空条目过滤：模型没有实际输出时（如请求即报错），流式路径会残留
  // content 为空的 thinking / 占位 tool——这些不该渲染出"执行过程 思考"空组。
  // 空 thinking 一律过滤：流式刚开始的空窗极短（首个 delta 即填充），
  // 消息级"正在响应"动效兜底；thinkingActive 不作为保留例外（错误后 status 残留）。
  const meaningful = entries.filter((e) => {
    if (e.type === 'thinking' && !(e.content ?? '').trim()) return false;
    if (e.type === 'tool') return Boolean(e.toolName);
    return true;
  });
  if (meaningful.length === 0) return null;
  const liveEntries = meaningful;
  const toolEntries = liveEntries.filter((e) => e.type === 'tool');
  // 交互类工具（澄清/计划/确认）以卡片呈现，不计入「工具调用」行数——
  // 组头计数必须与展开后的工具行数一致，否则用户会觉得"少了一个"
  const realTools = toolEntries.filter((e) => !isInteractiveTool(e));
  const toolCount = realTools.length;
  const runningCount = realTools.filter(
    (e) => e.toolStatus === 'running' || e.toolStatus === 'pending',
  ).length;
  const isRunning = runningCount > 0;
  const doneCount = toolCount - runningCount;
  // 组内含错误 → 默认展开（错误信息必须立即可见，不能折叠藏起来）
  const hasError = entries.some((e) => e.type === 'error');
  // 组内有待回答的交互卡（澄清/计划未答：success 但无 result）→ 不能折叠藏起来
  const hasOpenInteractive = toolEntries.some(
    (e) => isInteractiveTool(e) && !e.result,
  );
  // 组耗时：前端流式记录的工具时间跨度（历史数据无时间戳 → 不显示）
  const durationLabel = (() => {
    const timed = toolEntries.filter((e) => e.startedAt != null);
    if (!timed.length) return '';
    const ends = timed.filter((e) => e.endedAt != null);
    if (ends.length < timed.length) return ''; // 仍有工具在跑或数据不全
    const ms = Math.max(...timed.map((e) => e.endedAt!)) - Math.min(...timed.map((e) => e.startedAt!));
    return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)}s`;
  })();
  // 纯思考动效判据：消息流式中 && 本轮正文未开始
  const isLive = !!msgStreaming && !hasOwnText;
  // 本轮已结束（正文开始输出，或流已终止）→ 折叠为一行摘要；
  // 流式中 → 条目直接平铺（无组头包装），用户实时看到过程。
  const finished = !!hasOwnText || !msgStreaming;
  const [open, setOpen] = useState(!finished || hasOpenInteractive);
  const prevFinished = useRef(finished);
  // 组内 thinking 块的展开态（本地管理，不回写消息树）
  const [openThinkings, setOpenThinkings] = useState<Set<string>>(new Set());
  const toggleThinking = (id: string) =>
    setOpenThinkings((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  useEffect(() => {
    // 本轮结束跃迁 → 收起为摘要行（出错/待回答的交互卡保持展开不藏）
    if (prevFinished.current !== finished) {
      prevFinished.current = finished;
      if (finished && !hasError && !interrupted && !hasOpenInteractive) setOpen(false);
    }
  }, [finished, hasError, interrupted, hasOpenInteractive]);

  // 过程条目：按时序渲染；紧邻的普通工具 = 同一批并行调用 → 合并为一个
  // 「执行了 N 个工具」折叠条目（点击展开每条），执行顺序不丢失
  const renderEntries = () => {
    const slots: TimelineEntry[][] = [];
    let batch: TimelineEntry[] = [];
    const isChartEntry = (e: TimelineEntry) =>
      e.type === 'tool' &&
      e.toolName === 'render_chart' &&
      /```(?:echarts|chart)\s*\n/i.test(e.result ?? '');
    for (const entry of entries) {
      const isNormalTool = entry.type === 'tool' && !isInteractiveTool(entry);
      // 图表是核心产出：独立直出（默认展开），永不收进折叠批次
      if (isNormalTool && !isChartEntry(entry)) {
        batch.push(entry);
      } else {
        if (batch.length) slots.push(batch);
        batch = [];
        slots.push([entry]);
      }
    }
    if (batch.length) slots.push(batch);
    return slots.map((slot, si) => {
      if (slot.length === 1) {
        const entry = slot[0];
        if (entry.type === 'thinking') {
          return (
            <ThinkingEntryCard
              key={`sl-${si}`}
              entry={{ ...entry, expanded: openThinkings.has(entry.id) }}
              streaming={
                entry === liveEntries[liveEntries.length - 1] &&
                !!thinkingActive &&
                isLive &&
                !isRunning
              }
              onToggle={() => toggleThinking(entry.id)}
            />
          );
        }
        if (entry.type === 'error') {
          return (
            <div
              key={`sl-${si}`}
              className="px-3 py-2 rounded-lg bg-sig-fail-soft text-sig-fail text-[12.5px] font-sans"
            >
              {entry.content}
            </div>
          );
        }
        if (entry.type === 'text') {
          return (
            <div
              key={`sl-${si}`}
              className="px-2.5 py-1 text-[13px] leading-relaxed text-ink-dim font-sans"
            >
              <Markdown content={entry.content} />
            </div>
          );
        }
        // 单条交互卡 / 单条工具
        return (
          <ToolEntryCard
            key={`sl-${si}`}
            entry={entry}
            msgId={msgId}
            interrupted={interrupted}
            theme={theme}
            onAnswer={onAnswer}
            onDismiss={onDismiss}
            onApprovePlan={onApprovePlan}
            planVersion={planVersion}
          />
        );
      }
      // 并行批次：N ≥ 2 → 折叠为一个条目
      return (
        <ParallelToolBatch
          key={`batch-${msgId}-${si}`}
          entries={slot}
          msgId={msgId}
        />
      );
    });
  };

  // 统一形态：流式中与完成后都是同一张折叠卡（流式中默认展开）——
  // 仅组头状态与 open 随运行状态变化。原实现流式中"平铺"、结束瞬间
  // 切换为折叠卡，整个 DOM 形态重建 → 几百 px 高度瞬间塌缩 = 刷一下。
  // 明细区用 grid-rows 高度过渡，收起/展开平滑进行（主流 agent UI 做法）。
  return (
    <div className="rounded-[10px] bg-page overflow-hidden font-sans">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-2 px-3 py-2 border-0 bg-transparent cursor-pointer text-left hover:bg-raise transition-colors rounded-[10px]"
      >
        {isRunning ? (
          <Loader2 className="w-3.5 h-3.5 self-center text-sig-wait shrink-0 animate-spin" />
        ) : hasError ? (
          <AlertTriangle className="w-3.5 h-3.5 self-center text-sig-fail shrink-0" />
        ) : (
          <CheckCircle className="w-3.5 h-3.5 self-center text-ink-faint shrink-0" />
        )}
        <span className="text-xs font-medium text-ink-dim shrink-0 leading-none">
          执行过程
        </span>
        <span className="text-[11px] text-ink-faint font-mono shrink-0">
          {hasError
            ? '执行出错'
            : isRunning
              ? '执行中'
              : toolCount > 0
                ? `${toolCount} 个工具调用`
                : '思考过程'}
          {durationLabel ? ` · ${durationLabel}` : ''}
        </span>
        {interrupted && (
          <span className="text-[11px] text-sig-fail shrink-0">· 已中断</span>
        )}
        <ChevronRight
          className={`w-3 h-3 text-ink-faint ml-auto transition-transform shrink-0 ${open ? 'rotate-90' : ''}`}
        />
      </button>
      <div
        className={`grid transition-[grid-template-rows] duration-300 ease-out ${open ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'}`}
      >
        <div className="overflow-hidden min-h-0">
          <div className="pb-2 space-y-1">
            {renderEntries()}
          </div>
        </div>
      </div>
    </div>
  );
}

/** 相邻同类工具（同 toolName + 同摘要）合并为一项 ×N——循环打磨场景
 *  连续 read/write 不再逐条刷屏（参考主流 agent UI 的 run 分组）。 */
