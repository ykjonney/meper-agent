import { type RefObject } from 'react';
import { Copy, RotateCcw, ThumbsUp, ThumbsDown } from 'lucide-react';
import { toast } from '../ui/toast';
import AvatarRender from '../AvatarRender';
import { Markdown } from '../Markdown';
import type { Message, TimelineEntry } from '../../types';
import type { SessionFeedbackItem } from '../../services/user-skills-api';
import { ActivityGroup, StreamingDots } from './ActivityGroup';
import { ChatAttachmentCard } from './ChatAttachmentCard';
import { ToolEntryCard } from './ToolEntryCard';
import { formatToolDuration, isChartResultEntry } from './tool-details';

interface MessageItemProps {
  msg: Message;
  /** 贴底跟随锁（ChatHomepage 维护）：用户手动展开/收起卡片时解锁，
   *  避免高度变化触发贴底跳转把视口拽走 */
  pinnedRef?: RefObject<boolean>;
  isLast: boolean;
  theme: 'dark' | 'light';
  streamingMsgId: string | null;
  isStreaming: boolean;
  activeSessionId: string | null;
  feedbackMap: Record<string, SessionFeedbackItem>;
  inputTextareaRef: RefObject<HTMLTextAreaElement | null>;
  onAnswer: (text: string) => void;
  /** 用上一条输入重新生成（父级负责查找 lastUser 并触发发送） */
  onRegenerate: () => void;
  onDismissInterrupt: (msgId: string) => void;
  onApprovePlan: (msgId: string, plan: string) => void;
  onVote: (requestId: string, value: 1 | -1) => void;
}

/** 单条聊天消息：user 单气泡 / agent 按 timeline 轮次渲染（活动组+正文），
 *  含附件卡、生成中动效、复制/重新生成、消息级反馈。 */
export function MessageItem({
  msg, pinnedRef, isLast, theme, streamingMsgId, isStreaming, activeSessionId, feedbackMap,
  inputTextareaRef, onAnswer, onRegenerate, onDismissInterrupt, onApprovePlan, onVote,
}: MessageItemProps) {
  const isUser = msg.role === 'user';
  // agent 消息靠 timeline 渲染（text/tool/thinking/error 按顺序）；
  // user 消息保持单个气泡。
  const hasTimeline = msg.role === 'agent' && !!msg.timeline && msg.timeline.length > 0;
  // 本条是否流式生成中——消息级"生成中"动效判据（见 streamingMsgId 声明处
  // 注释：msg.status 在轮次空窗期会被清空，不能作判据）。
  const inFlight = streamingMsgId === msg.id;
  return (
    <div
      key={msg.id}
      className={`relative flex items-start gap-3 animate-fade-in ${isUser ? 'ml-auto flex-row-reverse' : ''}`}
    >
      <div className={`w-6 h-6 rounded-full flex items-center justify-center shrink-0 select-none text-[11px] ${
        isUser ? 'bg-raise text-ink-soft' : 'bg-brand-soft text-brand'
      }`}>
        {isUser ? 'A' : '✦'}
      </div>
      <div className="space-y-1 min-w-0 flex-1">
        <div className={`flex items-center gap-2 text-[10.5px] font-mono uppercase tracking-wider text-ink-faint ${isUser ? 'justify-end' : ''}`}>
          {!isUser && (
            <span className="font-bold text-ink-dim font-sans">{msg.senderName}</span>
          )}
          <span className="text-ink-dim font-mono">{msg.timestamp}</span>
          {!isUser && msg.usage?.total_tokens ? (
            <span className="text-ink-dim font-mono">
              · {msg.usage.total_tokens.toLocaleString()} tokens
              {msg.usage.llm_calls != null && msg.usage.llm_calls > 1
                ? ` · ${msg.usage.llm_calls} 轮`
                : ''}
            </span>
          ) : null}
        </div>
        {hasTimeline ? (() => {
          /* 方案 1（对齐 ChatGPT/Claude.ai）：所有 text 一律卡外，按时序、
             正文样式平铺（中间小结与最终回答同款式）；卡 = 连续的
             thinking/tool 段（被 text 切开即新卡）。段后出现 text = 该段
             过程确定结束 → 该卡收起为摘要行；最后一段由流结束（done）收起。
             收起信号是确定性的段边界，无任何启发式猜测。 */
          const tl = msg.timeline!;
          // 消息级执行用时（LLM+工具累计，秒→ms）。老消息 usage 无 duration 字段 → 0 → 不显示用时。
          const execMs =
            ((msg.usage?.llm_duration ?? 0) + (msg.usage?.tool_duration ?? 0)) * 1000;
          const execDurationLabel = execMs > 0 ? formatToolDuration(execMs) : '';
          let lastTextIdx = -1;
          let finalTextIdx = -1;
          tl.forEach((e, i) => {
            if (e.type === 'text') lastTextIdx = i;
            if (e.type === 'text' && e.final) finalTextIdx = i;
          });
          /* 三层形态（用户模型）：① 执行过程组（最终回答前全部条目按原序，含
             中间轮 text（final=false，后接工具调用）与图表调用行，可收起）；
             ② 产物层（render_chart 成品，组外常驻不收起，Markdown 识别 echarts
             出图）；③ 最终回答平铺。「已完成」只有一种：输出了最终文本
             （final=true）。历史终态兜底：流已结束且无 final 标志（旧数据）时
             最后一个 text 即最终回答。 */
          const hasFinalText = finalTextIdx >= 0
            || (!inFlight && lastTextIdx >= 0);
          const anchor = finalTextIdx >= 0 ? finalTextIdx : lastTextIdx;
          const procEntries = anchor >= 0 ? tl.slice(0, anchor) : tl;
          const chartProducts = tl.filter(isChartResultEntry);
          const finalTexts = anchor >= 0 ? tl.slice(anchor) : [];
          return (
            <div className="space-y-2">
              <ActivityGroup
                entries={procEntries}
                msgId={msg.id}
                pinnedRef={pinnedRef}
                interrupted={!!msg.isInterrupted}
                theme={theme}
                thinkingActive={msg.status === 'thinking'}
                /* 最终回答（final=true）已出现 → 过程确定结束 → 收起为摘要行 */
                hasOwnText={hasFinalText}
                msgStreaming={inFlight}
                execDurationLabel={execDurationLabel}
                chartsInProducts
                onAnswer={onAnswer}
                onDismiss={() => onDismissInterrupt(msg.id)}
                onApprovePlan={(plan) => onApprovePlan(msg.id, plan)}
                planVersion={undefined}
              />
              {chartProducts.map((entry, i) => (
                <div key={`chart-${i}`} className="rounded-[10px] bg-page border border-line px-3 py-2.5">
                  <Markdown content={entry.result ?? ''} />
                </div>
              ))}
              {finalTexts.map((entry, i) =>
                entry.type === 'text' ? (
                  <div
                    key={`tx-${i}`}
                    className="text-[14px] leading-[1.75] font-sans select-text text-ink"
                  >
                    <Markdown content={entry.content} />
                    {/* 产出附件挂最终正文（最后一段 text）后面 */}
                    {i === finalTexts.length - 1 && msg.attachments && msg.attachments.length > 0 && (
                      <div className="flex flex-wrap gap-2 mt-3 pt-3 border-t border-line">
                        {msg.attachments.map((att, ai) => (
                          <ChatAttachmentCard
                            key={`${msg.id}-att-${ai}-${att.ref}`}
                            att={att}
                            sessionId={activeSessionId}
                          />
                        ))}
                      </div>
                    )}
                  </div>
                ) : (
                  /* 挂起的 HITL 交互卡（ask_clarification 等位于最后 text 之后）：
                     必须以交互卡渲染——吞进 text 平铺会让澄清卡凭空消失 */
                  <ToolEntryCard
                    key={`tool-${i}`}
                    entry={entry}
                    msgId={msg.id}
                    pinnedRef={pinnedRef}
                    interrupted={!!msg.isInterrupted}
                    theme={theme}
                    onAnswer={onAnswer}
                    onDismiss={() => onDismissInterrupt(msg.id)}
                    onApprovePlan={(plan) => onApprovePlan(msg.id, plan)}
                  />
                ),
              )}
            </div>
          );
        })() : (
        <div
          className={`font-sans select-text ${
            msg.status === 'thinking'
              ? 'text-[14px] leading-[1.75] text-brand'
              : isUser
                ? 'p-3 px-3.5 rounded-[10px] text-[13.5px] leading-relaxed bg-panel shadow-[var(--shadow-card)] text-ink w-fit max-w-full ml-auto'
                : 'text-[14px] leading-[1.75] text-ink'
          }`}
        >
          {msg.content
            ? <Markdown content={msg.content} />
            : (inFlight ? (
                /* 首 token 等待期：执行中动效（原为静态 '…'） */
                <span className="inline-flex items-center gap-1.5">
                  正在响应
                  <StreamingDots />
                </span>
              ) : '')}
          {/* 可预览附件挂在气泡内部。有正文时隔开 + 分隔线；
              仅附件（无文字）时直接贴边，不留空隙不画线。 */}
          {msg.attachments && msg.attachments.length > 0 && (
            <div className={`flex flex-wrap gap-2 ${msg.content ? 'mt-3 pt-3 border-t border-current/10' : ''} ${isUser ? 'justify-end' : ''}`}>
              {msg.attachments.map((att, i) => (
                <ChatAttachmentCard
                  key={`${msg.id}-att-${i}-${att.ref}`}
                  att={att}
                  sessionId={activeSessionId}
                />
              ))}
            </div>
          )}
        </div>
        )}
        {/* 消息级"生成中"动效：流式全程显示——覆盖思考完成→正文生成、
            工具完成→下一轮等 status 已被清空的空窗期，让用户始终能
            分清"回答结束了"还是"仍在等"；流结束/中止/出错即消失 */}
        {inFlight && hasTimeline && (
          <div className="flex items-center gap-1.5 text-[11px] text-brand font-sans">
            <StreamingDots />
            <span>生成中…</span>
          </div>
        )}
        {/* 回答下方：复制 / 重新生成（仅最后一轮）/ 反馈——淡入，避免流结束瞬间突兀弹出 */}
        {!isUser && !isStreaming && (
          <div className="flex items-center gap-0.5 pt-1 animate-fade-in">
            <button
              title="复制回答"
              onClick={() => {
                const raw = hasTimeline
                  ? (msg.timeline ?? []).filter((e) => e.type === 'text').map((e) => e.content).join('\n\n')
                  : msg.content;
                navigator.clipboard?.writeText(raw).catch(() => {});
                toast.success('已复制回答');
              }}
              className={`border-0 bg-transparent rounded-md w-7 h-7 flex items-center justify-center cursor-pointer transition ${
                'text-ink-dim hover:text-brand'
              }`}
            >
              <Copy size={15} />
            </button>
            {isLast && msg.role === 'agent' && (
              <button
                title="用上一条输入重新生成"
                onClick={onRegenerate}
                className="border-0 bg-transparent rounded-md w-7 h-7 flex items-center justify-center cursor-pointer transition text-ink-dim hover:text-brand"
              >
                <RotateCcw size={15} />
              </button>
            )}
            {/* 消息级反馈（§8.2 v2）——赞回复→本轮技能派生加分；与复制同行 */}
            {msg.requestId && (
              <button
                aria-label="msg-vote-up"
                title={feedbackMap[msg.requestId]?.value === 1 ? '已点过赞' : '这轮回复有帮助'}
                onClick={() => onVote(msg.requestId!, 1)}
                className={`border-0 bg-transparent rounded-md w-7 h-7 flex items-center justify-center cursor-pointer transition ${
                  feedbackMap[msg.requestId]?.value === 1 ? 'text-brand' : 'text-ink-dim hover:text-brand'
                }`}
              >
                <ThumbsUp size={15} />
              </button>
            )}
            {msg.requestId && (
              <button
                aria-label="msg-vote-down"
                title={feedbackMap[msg.requestId]?.value === -1 ? '已点过踩' : '这轮回复没帮助'}
                onClick={() => onVote(msg.requestId!, -1)}
                className={`border-0 bg-transparent rounded-md w-7 h-7 flex items-center justify-center cursor-pointer transition ${
                  feedbackMap[msg.requestId]?.value === -1 ? 'text-sig-fail' : 'text-ink-dim hover:text-sig-fail'
                }`}
              >
                <ThumbsDown size={15} />
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
