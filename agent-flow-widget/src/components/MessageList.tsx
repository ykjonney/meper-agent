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
  suggestedQuestions?: string[];
  onSuggestedQuestion?: (question: string) => void;
}

export function MessageList({
  messages,
  timeline,
  isLoading,
  pendingInterrupt,
  onInterruptAnswer,
  suggestedQuestions,
  onSuggestedQuestion,
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

  const chipStyle: preact.JSX.CSSProperties = {
    padding: '8px 14px',
    borderRadius: '18px',
    border: '1px solid #E5E7EB',
    backgroundColor: 'white',
    color: '#374151',
    fontSize: '13px',
    cursor: 'pointer',
    transition: 'all 0.15s',
    textAlign: 'left',
    lineHeight: '1.4',
  };

  const hasUserMessages = messages.some(m => m.role === 'user');

  if (!hasUserMessages && timeline.length === 0 && !pendingInterrupt) {
    return (
      <div style={containerStyle}>
        <div style={emptyStyle}>
          <div style={{ fontSize: '32px', marginBottom: '12px' }}>👋</div>
          <div style={{ marginBottom: '16px' }}>你好！有什么我可以帮你的吗？</div>
          {suggestedQuestions && suggestedQuestions.length > 0 && (
            <div style={{
              display: 'flex',
              flexDirection: 'column',
              gap: '8px',
              width: '100%',
              maxWidth: '280px',
            }}>
              {suggestedQuestions.map((q, i) => (
                <button
                  key={i}
                  style={chipStyle}
                  onClick={() => onSuggestedQuestion?.(q)}
                  onMouseEnter={(e) => {
                    const btn = e.currentTarget as HTMLButtonElement;
                    btn.style.backgroundColor = '#F3F4F6';
                    btn.style.borderColor = '#4F46E5';
                    btn.style.color = '#4F46E5';
                  }}
                  onMouseLeave={(e) => {
                    const btn = e.currentTarget as HTMLButtonElement;
                    btn.style.backgroundColor = 'white';
                    btn.style.borderColor = '#E5E7EB';
                    btn.style.color = '#374151';
                  }}
                >
                  {q}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    );
  }

  return (
    <div ref={containerRef} style={containerStyle}>
      {/* 按顺序渲染每条消息 */}
      {messages.map((msg) => {
        if (msg.role === 'user') {
          return <MessageBubble key={msg.id} message={msg} />;
        }

        // assistant 消息：正在流式输出时跳过（由下方 TimelineRenderer 处理）
        if (msg.streaming) return null;

        // 有 timeline 的历史 assistant 消息（从会话加载）：用 TimelineRenderer 渲染
        if (msg.timeline && msg.timeline.length > 0) {
          return <TimelineRenderer key={msg.id} timeline={msg.timeline} />;
        }

        // 普通 assistant 消息：用 MessageBubble 渲染
        return <MessageBubble key={msg.id} message={msg} />;
      })}

      {/* 当前流式时间线（包含 assistant 的 text/thinking/tool_call 等） */}
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
