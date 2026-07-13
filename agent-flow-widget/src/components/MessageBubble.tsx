// agent-flow-widget/src/components/MessageBubble.tsx

import type { Message } from '../types';

interface MessageBubbleProps {
  message: Message;
}

function renderMarkdown(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/`(.+?)`/g, '<code style="background:#f3f4f6;padding:2px 4px;border-radius:3px;font-size:0.9em;">$1</code>')
    .replace(/\n/g, '<br>');
}

export function MessageBubble({ message }: MessageBubbleProps) {
  const isUser = message.role === 'user';

  const containerStyle: preact.JSX.CSSProperties = {
    display: 'flex',
    justifyContent: isUser ? 'flex-end' : 'flex-start',
    marginBottom: '12px',
    padding: '0 16px',
  };

  const bubbleStyle: preact.JSX.CSSProperties = {
    maxWidth: '80%',
    padding: '10px 14px',
    borderRadius: isUser ? '16px 16px 4px 16px' : '16px 16px 16px 4px',
    backgroundColor: isUser ? '#4F46E5' : '#F3F4F6',
    color: isUser ? 'white' : '#1F2937',
    fontSize: '14px',
    lineHeight: '1.5',
    wordBreak: 'break-word',
  };

  return (
    <div style={containerStyle}>
      <div style={bubbleStyle}>
        <div dangerouslySetInnerHTML={{ __html: renderMarkdown(message.content) }} />
        {message.streaming && (
          <span style={{ display: 'inline-block', marginLeft: '4px' }}>▊</span>
        )}
      </div>
    </div>
  );
}
