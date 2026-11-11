import { useState, useRef, useEffect, useLayoutEffect, useMemo, Fragment, FormEvent, useCallback, type MouseEvent, type ChangeEvent, type ReactNode, type RefObject } from 'react';
import { Agent, Message, type ChatAttachment, type TimelineEntry } from '../../types'
import {
  Send, Plus, Trash2, FileCode, CheckCircle, Check,
  Bot, Terminal, Loader2, Paperclip, Brain, X, ShieldAlert,
  Wrench, AlertTriangle, ChevronDown, ChevronRight, User, Download, FileText, Image as ImageIcon, Mic, Copy, RotateCcw,
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
import { RESULT_COLLAPSE_THRESHOLD, TOOL_STATUS_CFG, ToolTypeIcon, formatToolArgs, formatToolDuration, formatToolResult, isChartResultEntry, toolDetail, toolSummary } from './tool-details';
import { ClarificationCard } from './ClarificationCard';
import { GuardRedirectNote, PlanCard } from './PlanCard';

export function ThinkingEntryCard({
  entry,
  streaming,
  onToggle,
}: {
  entry: TimelineEntry;
  /** 本轮思考正在流式输出（消息 thinking 中且该 entry 是最新条目）→ 头部脉冲 + 打字光标 */
  streaming?: boolean;
  onToggle: () => void;
}) {
  const expanded = !!entry.expanded;
  const contentRef = useRef<HTMLDivElement>(null);

  // 流式期间内容超出固定高度时，内部滚动条贴底跟随最新输出。
  useEffect(() => {
    if (streaming && contentRef.current) {
      contentRef.current.scrollTop = contentRef.current.scrollHeight;
    }
  }, [entry.content, streaming]);

  return (
    <div className="rounded-[10px] bg-page overflow-hidden font-sans">
      <button
        type="button"
        onClick={onToggle}
        className="w-full flex items-center gap-2 px-3 py-2 border-0 bg-transparent cursor-pointer text-left hover:bg-raise transition-colors rounded-[10px]"
      >
        <Brain className={`text-ink-dim ${streaming ? 'animate-pulse' : ''}`} size={13} />
        <span className="text-xs font-medium text-ink-dim">
          {streaming ? '思考中' : '思考过程'}
        </span>
        {streaming ? (
          <span className="flex items-center gap-[3px]">
            {[0, 1, 2].map((i) => (
              <span
                key={i}
                className="w-1 h-1 rounded-full bg-ink-dim animate-thinking-dot"
                style={{ animationDelay: `${i * 0.18}s` }}
              />
            ))}
          </span>
        ) : (
          !!entry.content && (
            <span className="text-[11px] text-ink-faint font-mono">{countZi(entry.content)} 字</span>
          )
        )}
      </button>
      {expanded && (
        <div
          ref={contentRef}
          className="px-3 pb-2 pt-2 text-xs text-ink-dim whitespace-pre-wrap leading-relaxed border-t border-line max-h-64 overflow-y-auto scrollbar-custom"
        >
          {entry.content}
          {streaming && <span className="animate-caret-blink">▍</span>}
        </div>
      )}
    </div>
  );
}

/** Tool entry card — renders a timeline tool entry. Dispatches to
 *  ClarificationCard / WorkflowProposalCard / WorkflowTaskCard for known
 *  tool types, else a generic collapsible tool card. Reads entry fields
 *  (toolName/args/result/toolStatus) instead of flat message fields. */
export function ToolEntryCard({
  entry,
  msgId,
  pinnedRef,
  interrupted,
  onAnswer,
  onDismiss,
  onApprovePlan,
  planVersion,
  theme,
  suppressChartBody,
}: {
  entry: TimelineEntry;
  msgId: string;
  /** 贴底跟随锁：用户手动展开/收起卡片时置 false，防止高度变化被贴底跳转拽走视口 */
  pinnedRef?: RefObject<boolean>;
  interrupted: boolean;
  onAnswer?: (answer: string) => void;
  onDismiss?: () => void;
  onApprovePlan?: (plan: string) => void;
  /** ④ 修订版本号：本条消息内第几次提交计划（反馈循环轮次可见）。 */
  planVersion?: number;
  /** 明暗主题——计划书卡片等使用实色底的组件必须感知（prose-chat 的
   *  正文色随主题切换，深色卡片在浅色主题下会深字深底看不清）。 */
  theme: 'dark' | 'light';
  /** 组内图表调用行：图表成品已由 MessageItem 产物层渲染（组外常驻），
   *  本条目退化为普通工具行——不默认展开、不出图、detail 不重复展示 result。 */
  suppressChartBody?: boolean;
}) {
  // ask_clarification 走专门的交互卡片（按 clarification_type 分样式）。
  // Hooks 顺序红线：组件有多个条件提前 return 的专属卡片分支，**所有
  // useState 必须集中在此处无条件调用**——散落在主路径的话，「普通工具
  // ↔ 澄清条目」的 fiber 复用场景 hooks 数量不一致，切会话时 React 直接
  // 崩溃白屏（Rendered more hooks than during the previous render）。
  const answeredClarification = !!entry.result;
  // render_chart：结果含 ```echarts fenced block → 详情区走 Markdown 自动出图，
  // 且默认展开（图表是工具的核心产出）。suppressChartBody（组内调用行）时
  // 退化为普通工具行——成品在产物层渲染，不重复出图、detail 不含 result。
  const isChartResult = !suppressChartBody && isChartResultEntry(entry);
  const [clarExpanded, setClarExpanded] = useState(!answeredClarification);
  const [expanded, setExpanded] = useState(isChartResult);
  const [resultExpanded, setResultExpanded] = useState(false);
  if (entry.toolName === 'ask_clarification') {
    // 授权守卫 veto（toolStatus=error）：被拦截的追问渲染为系统引导条
    // 而非澄清卡——否则"被拦的假澄清 + 后续真澄清"看起来像重复提问。
    if (entry.result && entry.toolStatus === 'error') {
      return <GuardRedirectNote text={entry.result} theme={theme} />;
    }
    // 已回答（含忽略）→ 默认收起为一行摘要，点击展开完整卡片；
    // 未答 → 交互卡原样显眼展示。useState 初始值只在挂载时生效：
    // 流式中刚回答完组件不重挂 → 保持展开可见，历史加载/刷新才默认收起。
    if (!answeredClarification) {
      return (
        <ClarificationCard
          entry={entry}
          interrupted={interrupted}
          onAnswer={onAnswer}
          onDismiss={onDismiss}
        />
      );
    }
    const dismissedClarification = entry.result === DISMISSED_CLARIFICATION_TEXT;
    return (
      <div className="rounded-[10px] bg-page overflow-hidden font-sans">
        <button
          type="button"
          onClick={() => setClarExpanded((v) => !v)}
          className="w-full flex items-center gap-2 px-3 py-2 border-0 bg-transparent cursor-pointer text-left hover:bg-raise transition-colors rounded-[10px]"
        >
          <CheckCircle className="w-3.5 h-3.5 shrink-0 text-ink-faint" />
          <span className="text-xs font-medium text-ink-dim">
            {dismissedClarification ? '已忽略一个问题' : '已回答一个问题'}
          </span>
          <ChevronRight
            className={`w-3 h-3 text-ink-faint ml-auto transition-transform shrink-0 ${clarExpanded ? 'rotate-90' : ''}`}
          />
        </button>
        {clarExpanded && (
          <div className="px-2 pb-2">
            <ClarificationCard
              entry={entry}
              interrupted={interrupted}
              onAnswer={onAnswer}
              onDismiss={onDismiss}
            />
          </div>
        )}
      </div>
    );
  }
  // confirm_workflow：工作流确认卡片（从 tool_call args 渲染，tool_result 决定终态）。
  if (entry.toolName === 'propose_plan') {
    return (
      <PlanCard
        entry={entry}
        interrupted={interrupted}
        theme={theme}
        planVersion={planVersion}
        onAnswer={onAnswer}
        onDismiss={onDismiss}
        onApprovePlan={onApprovePlan}
      />
    );
  }
  if (entry.toolName === 'confirm_workflow') {
    const args = entry.args ?? {};
    const resultText = entry.result ?? '';
    const isRejection = /取消|拒绝|忽略|cancel/i.test(resultText);
    const forceAction = entry.result ? (isRejection ? 'rejected' : 'confirmed') : undefined;
    return (
      <WorkflowProposalCard
        proposal={{
          type: 'workflow_proposal',
          workflow_name: String(args.workflow_name ?? ''),
          workflow_description: String(args.description ?? ''),
          input_preview: (args.params ?? {}) as Record<string, unknown>,
        }}
        forceAction={forceAction}
        onConfirm={(wfName) => {
          onAnswer?.(`确认执行 ${wfName}`);
          return true;
        }}
        onDismiss={onDismiss}
      />
    );
  }
  // dispatch_workflow：解析 task_created → 内嵌可展开 task 卡片。
  if (entry.toolName === 'dispatch_workflow') {
    const created = parseTaskCreated(entry.result);
    if (created) return <WorkflowTaskCard created={created} />;
  }
  const status = entry.toolStatus ?? 'running';
  const cfg = TOOL_STATUS_CFG[status];
  // render_chart：结果含 ```echarts fenced block → 详情区走 Markdown 自动出图，
  // 且默认展开——isChartResult 已在组件顶部（Hooks 无条件区）计算。
  // parse_file：成功解析（返回 markdown 首行 "# 文件名（类型，摘要）"）→ 专属
  // 文件卡片（FileText 图标 + 文件名标题 + 元信息徽标），详情区 Markdown 渲染，
  // 默认折叠（提取内容通常较长）。失败（[parse_file] 前缀错误文本）走通用卡片。
  const isParseResult =
    entry.toolName === 'parse_file' &&
    Boolean(entry.result) &&
    !entry.result!.startsWith('[parse_file]');
  const parseArgs = entry.args ?? {};
  const parseLabel = isParseResult
    ? String(parseArgs.path ?? parseArgs.file_id ?? '文件').split('/').pop()
    : '';
  const parseMetaMatch = isParseResult ? /^# .+（(.+?)）/.exec(entry.result ?? '') : null;
  const parseMeta = parseMetaMatch ? parseMetaMatch[1] : '';
  // delegate_to_subagent：子 Agent 委派——标题直接显示执行主体名（谁在干活），
  // 而非 delegate_to_subagent 工具名；task 摘要挂在标题旁。
  const isDelegation = entry.toolName === 'delegate_to_subagent';
  const delegationArgs = (entry.args ?? {}) as { subagent_name?: string; task?: string };
  const delegatedName = isDelegation ? String(delegationArgs.subagent_name ?? '子 Agent') : '';
  const delegatedTask = isDelegation ? String(delegationArgs.task ?? '') : '';

  const argsText = formatToolArgs(entry.args);
  const result = formatToolResult(entry.result);
  // suppressChartBody：组内图表调用行是纯展示行（成品已在产物层），
  // 不可点击展开、无 detail 区
  const hasDetail = !suppressChartBody && (Boolean(argsText) || Boolean(result.text));
  const resultTooLong = countZi(result.text) > RESULT_COLLAPSE_THRESHOLD;
  const shownResult =
    !resultExpanded && resultTooLong
      ? truncateByZi(result.text, RESULT_COLLAPSE_THRESHOLD) + '…'
      : result.text;

  const StatusIcon =
    status === 'running' || status === 'pending' ? Loader2 : status === 'success' ? CheckCircle : AlertTriangle;

  // 单行人话摘要：动词 + 关键参数（toolSummary 按工具类型取参）
  const base = toolSummary(entry);
  const verb = isParseResult ? '解析文件' : isDelegation ? '委派子任务' : base.verb;
  const detail = isParseResult
    ? parseLabel
    : isDelegation
      ? delegatedName
      : base.detail;
  const running = status === 'running' || status === 'pending';

  return (
    <div className="rounded-lg overflow-hidden font-sans">
      {/* 单行摘要：点击展开原始参数与结果 */}
      <button
        type="button"
        onClick={() => {
          // 手动展开/收起 = 原地查看 → 解除贴底锁（防 RO 跳底拽走视口）
          if (!hasDetail) return;
          if (pinnedRef) pinnedRef.current = false;
          setExpanded((v) => !v);
        }}
        className={`w-full flex items-center gap-2 px-2.5 py-1.5 bg-transparent border-0 text-left transition-colors rounded-lg ${
          hasDetail ? `cursor-pointer ${cfg.hover}` : 'cursor-default'
        }`}
      >
        {running ? (
          <Loader2 className="w-3.5 h-3.5 shrink-0 animate-spin text-sig-wait" />
        ) : status === 'error' ? (
          <AlertTriangle className="w-3.5 h-3.5 shrink-0 text-sig-fail" />
        ) : (
          <ToolTypeIcon toolName={entry.toolName} className="w-3.5 h-3.5 shrink-0 text-ink-dim" />
        )}
        <span className="text-[12.5px] font-medium text-ink shrink-0 leading-none">{verb}</span>
        <span className="flex-1 min-w-0 text-[11.5px] font-mono text-ink-dim truncate text-left">
          {detail || (running ? '…' : '—')}
        </span>
        {!running && entry.startedAt && entry.endedAt && (
          <span className="shrink-0 text-[10.5px] text-ink-faint font-mono">
            {formatToolDuration(entry.endedAt - entry.startedAt)}
          </span>
        )}
      </button>

      {/* Detail pane */}
      {expanded && hasDetail && (
        <div className="border-t border-line px-3.5 pb-3 pt-2.5 space-y-2.5">
          {isDelegation && delegatedTask && (
            <div>
              <div className={`text-[11px] font-semibold mb-1 opacity-60 ${cfg.icon}`}>
                委派任务
              </div>
              <pre className="text-[11px] leading-relaxed whitespace-pre-wrap break-all rounded-lg p-2 bg-page border border-line text-ink-dim font-mono max-h-48 overflow-y-auto">
                {delegatedTask}
              </pre>
            </div>
          )}
          {/* 委派条目不重复展示请求参数——args 即 {subagent_name, task}，
              已被标题（执行主体名）与「委派任务」块完整覆盖。 */}
          {!isDelegation && (() => {
            const det = toolDetail(entry);
            if (det.kind === 'none') return null;
            if (det.kind === 'command') {
              // 终端命令原文：等宽 + 保留换行，无键名无转义
              return (
                <div>
                  <div className={`text-[11px] font-semibold mb-1 opacity-60 ${cfg.icon}`}>命令</div>
                  <pre className="text-[11.5px] leading-relaxed whitespace-pre-wrap break-all rounded-lg p-2.5 bg-well border border-line text-ink-soft font-mono max-h-64 overflow-y-auto">
                    {det.payload}
                  </pre>
                </div>
              );
            }
            if (det.kind === 'diff') {
              // 编辑差异：删除行红 / 新增行绿，逐行对照
              const delLines = det.diffOld ? det.diffOld.split('\n') : [];
              const addLines = det.diffNew ? det.diffNew.split('\n') : [];
              return (
                <div>
                  <div className={`text-[11px] font-semibold mb-1 opacity-60 ${cfg.icon}`}>
                    变更差异 <span className="font-mono normal-case opacity-70">{det.payload}</span>
                  </div>
                  <div className="rounded-lg p-2 bg-well border border-line font-mono text-[11px] leading-relaxed max-h-64 overflow-y-auto">
                    {delLines.map((l, i) => (
                      <div key={`d${i}`} className="text-sig-fail bg-sig-fail-soft rounded px-1.5 my-px whitespace-pre-wrap break-all">
                        - {l}
                      </div>
                    ))}
                    {addLines.map((l, i) => (
                      <div key={`a${i}`} className="text-sig-ok bg-sig-ok-soft rounded px-1.5 my-px whitespace-pre-wrap break-all">
                        + {l}
                      </div>
                    ))}
                  </div>
                </div>
              );
            }
            if (det.kind === 'code') {
              // 写入的内容：等宽展示（保留换行）
              return (
                <div>
                  <div className={`text-[11px] font-semibold mb-1 opacity-60 ${cfg.icon}`}>写入内容</div>
                  <pre className="text-[11.5px] leading-relaxed whitespace-pre-wrap break-all rounded-lg p-2.5 bg-well border border-line text-ink-soft font-mono max-h-64 overflow-y-auto">
                    {det.payload}
                  </pre>
                </div>
              );
            }
            // JSON 兜底
            return (
              <div>
                <div className={`text-[11px] font-semibold mb-1 opacity-60 ${cfg.icon}`}>
                  请求参数
                </div>
                <pre className="text-[11px] leading-relaxed whitespace-pre-wrap break-all rounded-lg p-2 bg-page border border-line text-ink-dim font-mono max-h-48 overflow-y-auto">
                  {det.payload}
                </pre>
              </div>
            );
          })()}
          {!suppressChartBody && result.text && (
            <div>
              <div className={`text-[11px] font-semibold mb-1 opacity-60 ${cfg.icon} flex items-center gap-1.5`}>
                返回结果
                {result.isJson && (
                  <span className="px-1 py-0 rounded bg-line text-[11px] opacity-80">JSON</span>
                )}
              </div>
              {isChartResult || isParseResult ? (
                // render_chart：走 Markdown 渲染（识别 ```echarts 出图 + 摘要文本）；
                // parse_file：提取内容是 markdown（标题/表格），同样走 Markdown 渲染。
                <Markdown content={result.text} />
              ) : (
                <pre className="text-[11px] leading-relaxed whitespace-pre-wrap break-all rounded-lg p-2 bg-page border border-line text-ink-dim font-mono max-h-64 overflow-y-auto">
                  {shownResult}
                </pre>
              )}
              {resultTooLong && (
                <button
                  type="button"
                  onClick={() => {
                    if (pinnedRef) pinnedRef.current = false;
                    setResultExpanded((v) => !v);
                  }}
                  className={`mt-1 text-[11px] underline ${cfg.icon} opacity-80 hover:opacity-100 cursor-pointer`}
                >
                  {resultExpanded ? '收起结果' : `展开全部 (${countZi(result.text)} 字)`}
                </button>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/** propose_plan 计划书卡片 — 文档样式呈现五段式计划，底部审批操作。
 *
 * 样式上做成"计划书"：文档标题栏（编号感图标 + 标题 + 状态章）、纸面正文
 * （按 `# 标题` 分节渲染：节标题带竖向强调条，目标节强调展示，步骤节
 * checkbox 转为 ☐/☑ 字形），页脚审批区。
 *
 * 交互（interrupted 且未答）：【同意执行】走 approve 端点（零 LLM：
 * 写 PLAN.md + 合成 tool_result），前端随后自动 kickoff 执行；
 * 【拒绝】走 dismiss（本轮作废）；【反馈输入】任意内容 resume
 * （保持计划模式，agent 修订后重新提交新计划书）。
 * 已答态：状态章（已批准/已反馈）+ 反馈摘要。
 */

/** 把五段式计划 markdown 按 `# 标题` 切成节（未带标题的内容归入首节）。 */
