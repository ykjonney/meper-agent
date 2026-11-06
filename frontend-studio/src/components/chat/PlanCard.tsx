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
import { PLAN_SECTION_ORDER, parsePlanSections, planCheckboxGlyphs } from './tool-details';
import { ClarificationCard } from './ClarificationCard';
import { extractPlanToolHints } from './message-utils';

export function PlanCard({
  entry,
  interrupted,
  onAnswer,
  onDismiss,
  onApprovePlan,
  planVersion,
  theme,
}: {
  entry: TimelineEntry;
  interrupted: boolean;
  onAnswer?: (answer: string) => void;
  onDismiss?: () => void;
  /** 零 LLM 批准：写 PLAN.md + 合成 tool_result（ChatHomepage 接线后自动 kickoff） */
  onApprovePlan?: (plan: string) => void;
  /** ④ 修订版本号（同一消息内第几次提交；>1 时显示 v{n}）。 */
  planVersion?: number;
  theme: 'dark' | 'light';
}) {
  const [feedback, setFeedback] = useState("");
  // 编辑模式：直接改计划全文——[按此版本批准]（编辑稿落盘 PLAN.md）或
  // [作为反馈提交]（编辑稿走 resume 修订通道）。零 LLM 的精确修正路径。
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const plan = String(entry.args?.plan ?? "");
  const result = entry.result ?? "";
  const answered = Boolean(result);
  const toolHints = extractPlanToolHints(plan);
  // approved 判定：稳定前缀（后端 PLAN_APPROVED_RESULT_TEXT 与 plan_tool
  // 批准返回文案均以"用户已批准"开头——两侧同源，勿改开头措辞）。
  const approved = result.startsWith("用户已批准");

  const sections = parsePlanSections(plan);
  // 规范五段顺序排前，未知节殿后（可演化的计划允许加节）。
  const ordered = [
    ...PLAN_SECTION_ORDER.map((t) => sections.find((s) => s.title === t)),
    ...sections.filter((s) => !PLAN_SECTION_ORDER.includes(s.title)),
  ].filter((s): s is { title: string; body: string } => Boolean(s));
  const isObjective = (title: string) => title === "目标";

  // 语义类随主题挂载链自动适配（卡片底色必须与 prose-chat 正文色同步）。
  const shellCls = 'border-line bg-panel';
  const headerCls = 'bg-panel-hover border-line';
  const bodyCls = 'bg-panel';
  const footerCls = 'bg-page border-line';
  const titleCls = 'text-ink';
  const subtitleCls = 'text-ink-dim';
  const sectionTitleCls = 'text-brand';
  const dashCls = 'border-line-strong';
  const objectiveTextCls = 'text-ink';
  const bodyTextCls = 'text-ink-soft';
  const badge = answered
    ? approved
      ? 'bg-sig-ok-soft text-sig-ok border-line'
      : 'bg-sig-wait-soft text-sig-wait border-line'
    : 'bg-brand-soft text-brand border-brand';
  const ghostBtnCls = 'border-line-strong text-ink-dim hover:text-ink hover:border-line-strong';
  const inputCls = 'bg-panel border-line-strong text-ink placeholder:text-ink-dim focus:border-brand';
  const secondaryBtnCls = 'bg-line hover:bg-raise text-ink';
  const resultTextCls = 'text-ink-dim';

  return (
    <div className={`rounded-xl rounded-tl-none border overflow-hidden font-sans shadow-lg max-w-full ${shellCls}`}>
      {/* 文档标题栏 */}
      <div className={`flex items-center justify-between px-5 py-3 border-b ${headerCls}`}>
        <div className="flex items-center gap-2.5">
          <div className="w-7 h-7 rounded-md bg-brand-soft border border-brand flex items-center justify-center">
            <ClipboardList className="w-3.5 h-3.5 text-brand" />
          </div>
          <div>
            <div className={`text-[13px] font-bold tracking-widest ${titleCls}`}>
              执行计划书{planVersion && planVersion > 1 ? ` · v${planVersion}` : ''}
            </div>
            <div className={`text-[11px] tracking-wide ${subtitleCls}`}>
              PLAN{planVersion && planVersion > 4 ? ` · 已修订 ${planVersion} 轮` : ' · 待人工审批后执行'}
            </div>
          </div>
        </div>
        <span className={`text-[11px] font-semibold px-2 py-1 rounded border ${badge}`}>
          {answered ? (approved ? "✓ 已批准" : "已反馈") : "待审批"}
        </span>
      </div>

      {/* ① 工具清单警示条：审批焦点从"步骤合理"降到"会碰什么"（变更类⚠高亮） */}
      {toolHints.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 px-5 py-2 border-b border-raise bg-page">
          <span className={`text-[11px] font-semibold tracking-wide ${subtitleCls}`}>本计划将使用：</span>
          {toolHints.map((h) => (
            <span
              key={h.label}
              className={`text-[11px] font-mono px-1.5 py-0.5 rounded border ${
                h.mutating
                  ? 'bg-sig-wait-soft border-line text-sig-wait'
                  : 'bg-raise border-line text-ink-dim'
              }`}
            >
              {h.mutating ? '⚠ ' : ''}{h.label}
            </span>
          ))}
        </div>
      )}

      {/* 纸面正文：分节渲染 */}
      <div className={`px-6 py-4 max-h-96 overflow-y-auto space-y-4 ${bodyCls}`}>
        {ordered.length === 0 && <p className={`text-xs ${subtitleCls}`}>（计划内容缺失）</p>}
        {ordered.map((sec, i) => (
          <div key={i}>
            {sec.title && (
              <div className="flex items-center gap-1.5 mb-1.5">
                <span className="w-1 h-3.5 bg-brand/70 rounded-full" />
                <h4 className={`text-[11px] font-bold tracking-widest uppercase ${sectionTitleCls}`}>{sec.title}</h4>
                <span className={`flex-1 border-t border-dashed ${dashCls}`} />
              </div>
            )}
            {isObjective(sec.title) ? (
              <div className={`px-3 py-2 rounded-md bg-brand-soft/50 border-l-2 border-brand/60 text-[13px] font-medium leading-relaxed ${objectiveTextCls}`}>
                <Markdown content={planCheckboxGlyphs(sec.body.trim())} />
              </div>
            ) : (
              <div className={`text-[12px] leading-relaxed pl-1 ${bodyTextCls}`}>
                <Markdown content={planCheckboxGlyphs(sec.body.trim() || "—")} />
              </div>
            )}
          </div>
        ))}
      </div>

      {/* 页脚：审批操作（未答态） */}
      {!answered && interrupted && (
        <div className={`px-5 py-3 border-t space-y-2 ${footerCls}`}>
          {editing ? (
            <div className="space-y-2">
              <textarea
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                rows={10}
                spellCheck={false}
                className={`w-full px-3 py-2 rounded-md text-xs font-mono leading-relaxed outline-none transition resize-y ${inputCls}`}
              />
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  disabled={!draft.trim()}
                  onClick={() => {
                    setEditing(false);
                    onApprovePlan?.(draft.trim());
                  }}
                  className="px-4 py-1.5 rounded-md bg-brand hover:bg-brand-hover text-white text-xs font-semibold cursor-pointer transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  按此版本批准
                </button>
                <button
                  type="button"
                  disabled={!draft.trim()}
                  onClick={() => {
                    setEditing(false);
                    onAnswer?.(`以下为用户修改后的计划全文，请据此修订并重新提交：\n\n${draft.trim()}`);
                    setFeedback("");
                  }}
                  className={`px-4 py-1.5 rounded-md border text-xs font-semibold cursor-pointer transition-colors disabled:opacity-40 disabled:cursor-not-allowed ${ghostBtnCls}`}
                >
                  作为反馈提交
                </button>
                <button
                  type="button"
                  onClick={() => setEditing(false)}
                  className="px-3 py-1.5 rounded-md text-xs text-ink-dim hover:text-ink-dim cursor-pointer transition"
                >
                  取消
                </button>
              </div>
            </div>
          ) : (
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => onApprovePlan?.(plan)}
              className="px-4 py-1.5 rounded-md bg-brand hover:bg-brand-hover text-white text-xs font-semibold cursor-pointer transition-colors"
            >
              同意执行
            </button>
            <button
              type="button"
              onClick={() => {
                setDraft(plan);
                setEditing(true);
              }}
              className={`px-4 py-1.5 rounded-md border text-xs font-semibold cursor-pointer transition-colors ${ghostBtnCls}`}
            >
              编辑
            </button>
            <button
              type="button"
              onClick={onDismiss}
              className={`px-4 py-1.5 rounded-md border text-xs font-semibold cursor-pointer transition-colors ${ghostBtnCls}`}
            >
              拒绝
            </button>
          </div>
          )}
          <div className="flex gap-2">
            <input
              type="text"
              value={feedback}
              onChange={(e) => setFeedback(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && feedback.trim()) {
                  e.preventDefault();
                  onAnswer?.(feedback.trim());
                  setFeedback("");
                }
              }}
              placeholder="输入修改意见，agent 修订后将重新提交计划书…"
              className={`flex-1 px-3 py-1.5 rounded-md text-xs outline-none transition ${inputCls}`}
            />
            <button
              type="button"
              disabled={!feedback.trim()}
              onClick={() => {
                onAnswer?.(feedback.trim());
                setFeedback("");
              }}
              className={`px-3 py-1.5 rounded-md text-xs font-semibold cursor-pointer transition disabled:opacity-40 disabled:cursor-not-allowed ${secondaryBtnCls}`}
            >
              提交反馈
            </button>
          </div>
        </div>
      )}

      {/* 已答态：结果摘要 */}
      {answered && result && (
        <div className={`px-5 py-2.5 border-t text-[11px] ${footerCls} ${resultTextCls}`}>
          {approved ? "✅ 计划已批准 — 对话中说“开始执行”即可按计划推进" : `反馈：${result}`}
        </div>
      )}
    </div>
  );
}

/** 授权守卫引导条 — ask_clarification 被 authorization_guard_veto 拦截
 * （存在未授权应用时防模型向用户索要凭证）的呈现形态。与澄清卡区分：
 * 这是系统级安全引导（指向 request_app_authorization），不是一次提问。 */
export function GuardRedirectNote({ text }: { text: string; theme?: 'dark' | 'light' }) {
  return (
    <div className="rounded-xl rounded-tl-none border border-line px-4 py-3 font-sans shadow-sm bg-sig-wait-soft">
      <div className="flex items-center gap-2 text-xs font-semibold text-sig-wait">
        <ShieldAlert className="w-3.5 h-3.5 shrink-0" />
        系统安全引导（追问已拦截）
      </div>
      <p className="mt-1.5 text-[11.5px] leading-relaxed text-ink-soft">
        {text}
      </p>
      <p className="mt-1 text-[11px] text-ink-dim">
        模型被引导改用应用授权流程（request_app_authorization），凭证永不进入对话。
      </p>
    </div>
  );
}

/* ────────────────────────────────────────────────────────────
   ClarificationCard — ask_clarification 交互卡片
   按 clarification_type 分样式渲染问题 + 选项/按钮 + 内联输入。
   交互态（!answered && clarificationActive）选项可点、内联可填；已回答后选项
   静态高亮、答案以 indigo 气泡附在卡片下方。暗色配色用 Tailwind opacity token，
   明暗主题通用。对照 frontend/src/components/chat-panel.tsx 的 ask_clarification 渲染。
   ──────────────────────────────────────────────────────────── */
