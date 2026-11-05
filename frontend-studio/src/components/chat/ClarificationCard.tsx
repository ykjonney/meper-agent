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
import { TOOL_STATUS_CFG } from './tool-details';

export function ClarificationCard({
  entry,
  interrupted,
  onAnswer,
  onDismiss,
}: {
  entry: TimelineEntry;
  interrupted: boolean;
  onAnswer?: (answer: string) => void;
  onDismiss?: () => void;
}) {
  const args = entry.args ?? {};
  const question = args.question ? String(args.question) : '';
  // LLM 可能把 options 传成 JSON 字符串，做一次兼容解析。
  const rawOptions = args.options;
  let options: string[] = [];
  if (Array.isArray(rawOptions)) options = rawOptions as string[];
  else if (typeof rawOptions === 'string') {
    try {
      options = JSON.parse(rawOptions);
    } catch {
      /* ignore */
    }
  }
  const clarificationType = args.clarification_type
    ? String(args.clarification_type)
    : 'missing_info';
  const answered = !!entry.result;
  // 交互态：只要未回答就可交互。不再门控 interrupted 标志——该标志用于 /resume
  // 路由判断，不应影响卡片交互元素的可见性（否则 interrupt 状态没及时传递时
  // 选项/输入框会被隐藏，导致卡片「看不清楚」）。
  void interrupted; // 保留 prop 以兼容调用方，但不再用作交互门控
  const interactive = !answered;

  // fields 向导模式：ask_clarification 带 fields 时渲染多步结构化表单，
  // 单次收集多个字段。fields 可能是数组或 JSON 字符串（LLM 容错）。
  const rawFields = args.fields;
  let formFields: ClarificationField[] = [];
  if (Array.isArray(rawFields)) formFields = rawFields as ClarificationField[];
  else if (typeof rawFields === 'string') {
    try {
      const parsed = JSON.parse(rawFields);
      if (Array.isArray(parsed)) formFields = parsed as ClarificationField[];
    } catch {
      /* ignore */
    }
  }
  if (formFields.length > 0) {
    return (
      <ClarificationFormCard
        question={question}
        context={args.context ? String(args.context) : undefined}
        fields={formFields}
        answered={answered}
        result={entry.result}
        onSubmit={(jsonStr) => onAnswer?.(jsonStr)}
        onDismiss={onDismiss}
      />
    );
  }

  const [inlineText, setInlineText] = useState('');
  const submitInline = () => {
    const t = inlineText.trim();
    if (!t) return;
    onAnswer?.(t);
    setInlineText('');
  };

  const isRisk = clarificationType === 'risk_confirmation';
  const isSuggestion = clarificationType === 'suggestion';
  const verticalOptions =
    clarificationType === 'approach_choice' || clarificationType === 'ambiguous_requirement';
  const dismissed = entry.result === DISMISSED_CLARIFICATION_TEXT;

  // 配色完全复用 TOOL_STATUS_CFG 的视觉语言（已验证好看 + 协调）：
  // 外层用淡彩透明底（/10）+ 彩色边框（/30），标题文字用彩色（-400）。
  // 问题正文放在实底深色内嵌区块（bg-page，和通用工具卡 detail pane 的
  // <pre> 一致）里，用白字——这样背景好看、文字清晰，两全其美。
  const accent = isRisk
    ? { icon: 'text-sig-wait', wrap: 'bg-sig-wait-soft border-line', sym: '⚠️' }
    : isSuggestion
      ? { icon: 'text-sig-ok', wrap: 'bg-sig-ok-soft border-line', sym: '💡' }
      : { icon: 'text-brand', wrap: 'bg-brand-soft border-indigo-500/30', sym: '❓' };

  return (
    <div className={`rounded-xl rounded-tl-none border overflow-hidden font-sans shadow-sm ${accent.wrap}`}>
      {/* 标题行：与通用工具卡 header 一致（透明底 + 彩色字） */}
      <div className="flex items-center gap-2 px-3.5 py-2.5">
        {answered ? (
          <CheckCircle className={`w-3.5 h-3.5 shrink-0 ${accent.icon}`} />
        ) : (
          <Loader2 className={`w-3.5 h-3.5 shrink-0 ${accent.icon} animate-spin`} />
        )}
        <span className={`text-xs font-semibold truncate ${accent.icon}`}>澄清提问</span>
        <span className={`text-[11px] ${accent.icon} opacity-70`}>
          {answered ? (dismissed ? '已忽略' : '已回答') : '等待回答'}
        </span>
        {/* 跳过入口移至交互区（「跳过此问题，直接继续」）——此处不再放小字按钮 */}
      </div>

      {/* 问题正文 + 交互区：实底深色内嵌区块（bg-page）+ 白字，可读性优先 */}
      <div className="mx-2.5 mb-2.5 rounded-lg bg-page border border-line px-3.5 py-3">
        <div className="flex items-start gap-2.5">
          <span className={`text-sm mt-0.5 select-none ${accent.icon}`}>{accent.sym}</span>
          <div className="flex-1 min-w-0">
            <div className="text-[13px] font-medium whitespace-pre-wrap leading-relaxed text-ink">
              {question}
            </div>

            {options.length > 0 && (
              <div className={`flex gap-2 mt-3 ${verticalOptions ? 'flex-col' : 'flex-wrap'}`}>
                {options.map((opt, i) =>
                  interactive ? (
                    <button
                      key={i}
                      type="button"
                      onClick={() => onAnswer?.(opt)}
                      className="text-left px-3 py-1.5 rounded-lg text-xs border bg-well border-line-strong text-ink hover:border-brand hover:bg-brand-soft transition cursor-pointer"
                    >
                      {opt}
                    </button>
                  ) : (
                    <div
                      key={i}
                      className={`px-3 py-1.5 rounded-lg text-xs border transition-colors ${
                        entry.result === opt
                          ? 'bg-brand-soft border-brand text-ink font-medium'
                          : 'bg-well border-line text-ink-dim'
                      }`}
                    >
                      {opt}
                      {entry.result === opt && <span className="ml-1.5 text-brand">✓</span>}
                    </div>
                  ),
                )}
              </div>
            )}

            {/* risk_confirmation：确认执行 / 取消 */}
            {interactive && isRisk && (
              <div className="flex gap-2 mt-3">
                <button
                  type="button"
                  onClick={() => onAnswer?.('确认')}
                  className="px-3.5 py-1.5 rounded-lg text-xs bg-rose-600 text-white hover:bg-sig-fail transition cursor-pointer"
                >
                  确认执行
                </button>
                <button
                  type="button"
                  onClick={() => onAnswer?.('取消')}
                  className="px-3.5 py-1.5 rounded-lg text-xs bg-well border border-line-strong text-ink hover:bg-line transition cursor-pointer"
                >
                  取消
                </button>
              </div>
            )}

            {/* suggestion：接受按钮 */}
            {interactive && isSuggestion && (
              <div className="flex gap-2 mt-3 items-center">
                <button
                  type="button"
                  onClick={() => onAnswer?.('接受建议')}
                  className="px-3.5 py-1.5 rounded-lg text-xs bg-sig-ok text-white hover:bg-sig-ok transition cursor-pointer"
                >
                  接受
                </button>
                <span className="text-[11px] text-ink-dim">或输入其他回答</span>
              </div>
            )}

            {/* 内联自由输入（交互态通用兜底） */}
            {interactive && (
              <div className="flex gap-1.5 mt-2.5">
                <input
                  type="text"
                  value={inlineText}
                  onChange={(e) => setInlineText(e.target.value)}
                  onKeyDown={(e) => {
                    // 中文 IME 选词的 Enter 不是提交回答
                    if (isImeComposing(e)) return;
                    if (e.key === 'Enter' && !e.shiftKey) {
                      e.preventDefault();
                      submitInline();
                    }
                  }}
                  placeholder="输入你的回答…"
                  className="flex-1 min-w-0 px-2.5 py-1.5 rounded-lg text-xs border border-line-strong bg-well text-ink placeholder:text-ink-dim focus:outline-none focus:border-brand"
                />
                <button
                  type="button"
                  onClick={submitInline}
                  disabled={!inlineText.trim()}
                  className="px-2.5 py-1.5 rounded-lg text-xs bg-brand text-white hover:bg-brand disabled:opacity-40 transition cursor-pointer"
                >
                  发送
                </button>
              </div>
            )}

            {/* 跳过入口：可选问题允许不回答直接继续（下一条消息走普通 stream，
                不注入本卡）。原入口是右上角 10px 小字「忽略」，太隐蔽用户找不到
                ——改到交互区，文案说明后果，与表单卡「忽略此问题」同级。 */}
            {interactive && onDismiss && (
              <button
                type="button"
                onClick={onDismiss}
                className="mt-2 text-xs text-ink-dim hover:text-ink-dim transition cursor-pointer"
              >
                跳过此问题，直接继续 →
              </button>
            )}

            {/* 已答：答案在卡片内部展示（紧贴问题下方，与 ClarificationFormCard 一致），
                不再渲染独立的右对齐气泡。已忽略则只给一行提示。 */}
            {dismissed && (
              <div className="mt-3 pt-3 border-t border-line text-xs text-ink-dim">
                已忽略此问题——可直接在输入框重新描述需求或上传文件
              </div>
            )}
            {answered && entry.result && !dismissed && !options.includes(entry.result) && (
              <div className="mt-3 pt-3 border-t border-line flex items-baseline gap-2 text-xs">
                <span className={`shrink-0 ${accent.icon}`}>你的回答:</span>
                <span className="text-ink font-medium break-all whitespace-pre-wrap">
                  {entry.result}
                </span>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
