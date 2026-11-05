import { Fragment, type Dispatch, type ReactNode, type RefObject, type SetStateAction } from 'react';
import { Copy, RotateCcw, ThumbsUp, ThumbsDown } from 'lucide-react';
import { toast } from '../ui/toast';
import AvatarRender from '../AvatarRender';
import { Markdown } from '../Markdown';
import type { Message, TimelineEntry } from '../../types';
import type { SessionFeedbackItem } from '../../services/user-skills-api';
import { ActivityGroup, StreamingDots } from './ActivityGroup';
import { ChatAttachmentCard } from './ChatAttachmentCard';

interface MessageItemProps {
  msg: Message;
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
  /** 编辑草稿回填（hover 用户消息"编辑"）——父级 setInputText */
  setInputText: Dispatch<SetStateAction<string>>;
}

/** 单条聊天消息：user 单气泡 / agent 按 timeline 轮次渲染（活动组+正文），
 *  含附件卡、生成中动效、复制/重新生成、消息级反馈。 */
export function MessageItem({
  msg, isLast, theme, streamingMsgId, isStreaming, activeSessionId, feedbackMap,
  inputTextareaRef, onAnswer, onRegenerate, onDismissInterrupt, onApprovePlan, onVote, setInputText,
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
      className={`group relative flex items-start gap-3 animate-fade-in ${isUser ? 'ml-auto flex-row-reverse' : ''}`}
    >
      <div className={`w-6 h-6 rounded-full flex items-center justify-center shrink-0 select-none text-[11px] ${
        isUser ? 'bg-raise text-ink-soft' : 'bg-brand-soft text-brand'
      }`}>
        {isUser ? 'A' : '✦'}
      </div>
      {/* hover 用户消息：编辑（内容填回输入框，作为新轮次发送） */}
      {isUser && (
        <button
          onClick={(e) => { e.stopPropagation(); setInputText(msg.content); inputTextareaRef.current?.focus(); }}
          className="absolute left-0 top-0 w-full h-full opacity-0 hover:opacity-100 transition-opacity bg-panel/40 items-center justify-center hidden group-hover:flex cursor-pointer z-[1]"
          title="编辑此输入"
        >
          <span className="af-btn af-btn-secondary h-7">编辑</span>
        </button>
      )}
      <div className="space-y-1 min-w-0 flex-1">
        <div className={`flex items-center gap-2 text-[10.5px] font-mono uppercase tracking-wider text-ink-faint ${isUser ? 'justify-end' : ''}`}>
          {!isUser && (
            <span className="font-bold text-ink-dim font-sans">
              {msg.senderName}
              {msg.status === 'thinking' && <span className="text-brand ml-1">· 思考中</span>}
            </span>
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
          /* 按 text 边界切轮：每轮 = text 前的 thinking/工具 + 该轮正文。
             流式过程只单调追加、永不重排——旧实现依赖"最后一个 text 是
             最终回答"启发式，轮间它会漂移（中间 text 先被当作最终回答
             独立渲染、下一轮开始又被吸回组内），导致多组并存/结构重排/
             收起展开抖动。error 保持独立红卡（醒目不折叠）。 */
          const tl = msg.timeline!;
          const rounds: { group: TimelineEntry[]; text?: TimelineEntry }[] = [];
          let cur: TimelineEntry[] = [];
          tl.forEach((entry) => {
            if (entry.type === 'text') {
              rounds.push({ group: cur, text: entry });
              cur = [];
            } else if (entry.type === 'error') {
              if (cur.length) { rounds.push({ group: cur }); cur = []; }
              rounds.push({ group: [entry] });
            } else {
              cur.push(entry);
            }
          });
          // 尾巴：思考/工具进行中（本轮正文尚未开始）→ 活动组
          if (cur.length) rounds.push({ group: cur });
          return (
          <div className="space-y-2">
            {rounds.map((round, ri) => {
              const isLastRound = ri === rounds.length - 1;
              const head = round.text ?? round.group[0];
              if (head.type === 'error') {
                return (
                  <div
                    key={head.id}
                    className="px-3.5 py-2.5 rounded-lg text-[13px] leading-relaxed font-sans bg-sig-fail-soft text-sig-fail"
                  >
                    {head.content}
                  </div>
                );
              }
              const pieces: ReactNode[] = [];
              if (round.group.length > 0) {
                pieces.push(
                  <ActivityGroup
                    key={`grp-${round.group[0].id}`}
                    entries={round.group}
                    msgId={msg.id}
                    interrupted={!!msg.isInterrupted}
                    theme={theme}
                    thinkingActive={msg.status === 'thinking'}
                    /* 本轮正文已开始输出 → 该轮活动组收起（过程是进度
                       指示器，答案开始才折叠；工具跑完不收） */
                    hasOwnText={!!round.text}
                    msgStreaming={inFlight}
                    onAnswer={onAnswer}
                    onDismiss={() => onDismissInterrupt(msg.id)}
                    onApprovePlan={(plan) => onApprovePlan(msg.id, plan)}
                    planVersion={undefined}
                  />,
                );
              }
              if (round.text) {
                pieces.push(
                  <div
                    key={round.text.id}
                    className="text-[14px] leading-[1.75] font-sans select-text text-ink"
                  >
                    <Markdown content={round.text.content} />
                    {/* 产出附件挂最后一轮正文后面 */}
                    {isLastRound && msg.attachments && msg.attachments.length > 0 && (
                      <div className="flex flex-wrap gap-2 mt-3 pt-3 border-t border-line">
                        {msg.attachments.map((att, i) => (
                          <ChatAttachmentCard
                            key={`${msg.id}-att-${i}-${att.ref}`}
                            att={att}
                            sessionId={activeSessionId}
                          />
                        ))}
                      </div>
                    )}
                  </div>,
                );
              }
              return <Fragment key={`round-${round.group[0]?.id ?? round.text?.id}`}>{pieces}</Fragment>;
            })}
          </div>
          );
        })() : (
        <div
          className={`font-sans select-text ${
            msg.status === 'thinking'
              ? 'text-[14px] leading-[1.75] text-brand italic'
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
        {/* 回答下方：复制 / 重新生成（仅最后一轮）/ 反馈 */}
        {!isUser && !isStreaming && (
          <div className="flex items-center gap-0.5 pt-1">
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
          </div>
        )}
        {/* 回答下方：消息级反馈（§8.2 v2）——赞回复→本轮技能派生加分 */}
        {!isUser && !isStreaming && msg.requestId && (
          <div className="flex items-center gap-0.5 pt-1">
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
          </div>
        )}
      </div>
    </div>
  );
}
