import { useLayoutEffect, useRef } from 'react';
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
  /** 贴底跟随标记（ChatHomepage 维护）：true 时内容高度变化持续跳底 */
  pinnedRef: RefObject<boolean>;
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
  isStreaming, pinnedRef, streamingMsgId, feedbackMap, chatScrollRef, messageEndRef,
  setShowJumpToBottom, showJumpToBottom, theme,
  onAnswer, onEditMessage, inputTextareaRef, onDismissInterrupt, onApprovePlan, onVote, onRegenerate,
}: MessageListProps) {
  // 浮标 = 「用户主动上翻」驱动，而非距底距离采样——程序跳底后内容继续
  // 撑高（气泡布局/图片加载）会让离散采样误判成用户上翻，新会话首帧必现。
  const lastScrollTopRef = useRef(0);
  // 贴底持续跟随：ResizeObserver 观察内容高度变化（含卡片收起/展开的
  // 300ms grid 动画期间——离散的 liveMessages layout effect 在动画渐变
  // 中会滞后，动画结束时一次性跳正 = 视口"闪一下"）。
  useLayoutEffect(() => {
    const el = chatScrollRef.current;
    const inner = el?.firstElementChild as HTMLElement | null;
    if (!el || !inner) return;
    const ro = new ResizeObserver(() => {
      if (pinnedRef.current) el.scrollTop = el.scrollHeight;
    });
    ro.observe(inner);
    return () => ro.disconnect();
  }, [chatScrollRef]);
  return (
    <>
    {/* overflow-anchor:none：禁用浏览器滚动锚定——展开/收起卡片时锚点元素
        被推挤会触发自动补偿滚动，视口跟着内容窜走（用户要的是原地静止；
        贴底跟随由 ResizeObserver 显式控制，不依赖锚定）。 */}
    <div
      ref={chatScrollRef}
      onScroll={(e) => {
        const el = e.currentTarget;
        const goingUp = el.scrollTop < lastScrollTopRef.current - 2;
        lastScrollTopRef.current = el.scrollTop;
        if (goingUp) {
          // 用户上翻且离底较远 → 提示可跳回最新
          if (el.scrollHeight - el.scrollTop - el.clientHeight > 240) setShowJumpToBottom(true);
        } else if (el.scrollHeight - el.scrollTop - el.clientHeight <= 240) {
          // 下滚回到底部附近 → 浮标消失；程序跳底(差值暂时大)保持现状不清除
          setShowJumpToBottom(false);
        }
      }}
      className="flex-1 min-h-0 overflow-y-auto scrollbar-custom [overflow-anchor:none] px-4 lg:px-6 pt-5 pb-3"
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
          pinnedRef={pinnedRef}
          isLast={mi === messages.length - 1}
          theme={theme}
          streamingMsgId={streamingMsgId}
          isStreaming={isStreaming}
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
