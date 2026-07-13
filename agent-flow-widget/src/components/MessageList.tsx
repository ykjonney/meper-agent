// agent-flow-widget/src/components/MessageList.tsx

import { useEffect, useRef } from 'preact/hooks';
import type { Message, TimelineEntry, InterruptData } from '../types';
import { MessageBubble } from './MessageBubble';
import { TimelineRenderer } from './TimelineRenderer';

interface MessageListProps {
  messages: Message[];
  timeline: TimelineEntry[];
  isLoading: boolean;
  pendingInterrupt: InterruptData | null;
  onInterruptAnswer: (answer: string) => void;
}

export function MessageList({
  messages,
  timeline,
  isLoading,
  pendingInterrupt,
  onInterruptAnswer,
}: MessageListProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
    }
  }, [messages, timeline]);

  const containerStyle: preact.JSX.CSSProperties = {
    flex: 1,
    overflowY: 'auto',
    padding: '16px 0',
  };

  const emptyStyle: preact.JSX.CSSProperties = {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    height: '100%',
    color: '#6B7280',
    fontSize: '14px',
    textAlign: 'center',
    padding: '20px',
  };

  const hasUserMessages = messages.some(m => m.role === 'user');

  if (!hasUserMessages && timeline.length === 0 && !pendingInterrupt) {
    return (
      <div style={containerStyle}>
        <div style={emptyStyle}>
          <div style={{ fontSize: '32px', marginBottom: '12px' }}>👋</div>
          <div>你好！有什么我可以帮你的吗？</div>
        </div>
      </div>
    );
  }

  return (
    <div ref={containerRef} style={containerStyle}>
      {messages.map((msg) => (
        <MessageBubble key={msg.id} message={msg} />
      ))}

      {/* 当前流式时间线 */}
      {timeline.length > 0 && (
        <TimelineRenderer
          timeline={timeline}
          onInterruptAnswer={pendingInterrupt ? onInterruptAnswer : undefined}
          interruptDisabled={isLoading}
        />
      )}

      {/* 流式加载指示器 */}
      {isLoading && timeline.length === 0 && (
        <div style={{ padding: '8px 16px', color: '#9CA3AF', fontSize: '13px' }}>
          思考中...
        </div>
      )}
    </div>
  );
}
