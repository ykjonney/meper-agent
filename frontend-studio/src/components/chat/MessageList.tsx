import type { Dispatch, RefObject, SetStateAction } from 'react';
import { ChevronDown } from 'lucide-react';
import { toast } from '../ui/toast';
import AvatarRender from '../AvatarRender';
import type { Agent, Message } from '../../types';
import type { Session } from '../../services/session-api';
import type { SessionFeedbackItem } from '../../services/user-skills-api';
import { MessageItem } from './MessageItem';

interface MessageListProps {
  messages: Message[];
  activeSession: Session | null;
  sessionsLoading: boolean;
  activeAgent: Agent | null;
  activeSessionId: string | null;
  isStreaming: boolean;
  /** 执行过程结束信号（后端 final 标记 / 正文静默启发式）→ 过程卡收起 */
  answerPhase: boolean;
  streamingMsgId: string | null;
  feedbackMap: Record<string, SessionFeedbackItem>;
  chatScrollRef: RefObject<HTMLDivElement | null>;
  messageEndRef: RefObject<HTMLDivElement | null>;
  setShowJumpToBottom: Dispatch<SetStateAction<boolean>>;
  showJumpToBottom: boolean;
  theme: 'dark' | 'light';
  onAnswer: (text: string) => void;
  onEditMessage: (text: string) => void;
  inputTextareaRef: RefObject<HTMLTextAreaElement | null>;
  onDismissInterrupt: (msgId: string) => void;
  onApprovePlan: (msgId: string, plan: string) => void;
  onVote: (requestId: string, value: 1 | -1) => void;
  /** 取最后一条 user 输入重新生成 */
  onRegenerate: (beforeMsg: Message) => void;
}

/** 聊天流滚动区：空会话 Agent 介绍 + 消息列表（MessageItem）+ 底部锚点 + 回到底部浮标 */
export function MessageList({
  messages, activeSession, sessionsLoading, activeAgent, activeSessionId,
  isStreaming, answerPhase, streamingMsgId, feedbackMap, chatScrollRef, messageEndRef,
  setShowJumpToBottom, showJumpToBottom, theme,
  onAnswer, onEditMessage, inputTextareaRef, onDismissInterrupt, onApprovePlan, onVote, onRegenerate,
}: MessageListProps) {
  return (
    <>
    <div
      ref={chatScrollRef}
      onScroll={(e) => {
        const el = e.currentTarget;
        setShowJumpToBottom(el.scrollHeight - el.scrollTop - el.clientHeight > 240);
      }}
      className="flex-1 min-h-0 overflow-y-auto scrollbar-custom px-4 lg:px-6 pt-5 pb-3"
    >
      <div className="max-w-[840px] mx-auto space-y-5">
      {/* 空会话欢迎界面：已选 Agent 但还没有消息 */}
      {activeSession && messages.length === 0 && !sessionsLoading && (
        <div className="flex flex-col items-center justify-center pt-[18vh] text-center animate-fade-in">
          <div className="w-16 h-16 rounded-2xl bg-brand-soft flex items-center justify-center overflow-hidden">
            <AvatarRender value={activeAgent?.avatar} className="w-full h-full p-2 text-2xl" />
          </div>
          <h2 className="mt-5 text-[17px] font-semibold text-ink font-sans">
            {activeAgent?.name ?? 'Agent'}
          </h2>
          <p className="mt-2 text-[13px] text-ink-dim font-sans max-w-[320px] leading-relaxed">
            {activeAgent?.description || '有什么可以帮你的？在下方输入，开始这段对话。'}
          </p>
        </div>
      )}

      {messages.map((msg, mi) => (
        <MessageItem
          key={msg.id}
          msg={msg}
          isLast={mi === messages.length - 1}
          theme={theme}
          streamingMsgId={streamingMsgId}
          isStreaming={isStreaming}
          answerPhase={answerPhase}
          activeSessionId={activeSessionId}
          feedbackMap={feedbackMap}
          inputTextareaRef={inputTextareaRef}
          onAnswer={onAnswer}
          onRegenerate={() => onRegenerate(msg)}
          onDismissInterrupt={onDismissInterrupt}
          onApprovePlan={onApprovePlan}
          onVote={onVote}
          setInputText={onEditMessage}
        />
      ))}
      <div ref={messageEndRef} />
      </div>
    </div>

    {/* 回到底部浮标（面板层，动态避让 composer 高度） */}
    {showJumpToBottom && (
      <button
        onClick={() => {
          const el = chatScrollRef.current;
          el?.scrollTo({ top: el.scrollHeight, behavior: 'smooth' });
          setShowJumpToBottom(false);
        }}
        style={{ bottom: 'calc(var(--composer-h, 120px) + 12px)' }}
        className="absolute left-1/2 -translate-x-1/2 z-20 flex items-center gap-1.5 h-8 px-3.5 rounded-full bg-panel shadow-[var(--shadow-pop)] border border-line text-[12px] text-ink-dim hover:text-ink transition cursor-pointer"
      >
        <ChevronDown className="w-3.5 h-3.5" />
        回到最新
      </button>
    )}
    </>
  );
}
