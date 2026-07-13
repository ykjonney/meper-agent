// agent-flow-widget/src/components/ChatWindow.tsx

import { useChat } from '../hooks/useChat';
import { MessageList } from './MessageList';
import { InputBar } from './InputBar';
import { InterruptBlock } from './InterruptBlock';

interface ChatWindowProps {
  title: string;
  onClose: () => void;
}

export function ChatWindow({ title, onClose }: ChatWindowProps) {
  const {
    messages,
    timeline,
    input,
    setInput,
    sendMessage,
    isLoading,
    error,
    clearMessages,
    pendingInterrupt,
    resumeWithAnswer,
  } = useChat();

  const windowStyle: preact.JSX.CSSProperties = {
    position: 'fixed',
    bottom: '90px',
    right: '20px',
    width: '380px',
    height: '560px',
    backgroundColor: 'white',
    borderRadius: '16px',
    boxShadow: '0 8px 32px rgba(0, 0, 0, 0.12)',
    display: 'flex',
    flexDirection: 'column',
    overflow: 'hidden',
    zIndex: 999999,
  };

  const headerStyle: preact.JSX.CSSProperties = {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '16px 20px',
    backgroundColor: '#4F46E5',
    color: 'white',
  };

  const closeButtonStyle: preact.JSX.CSSProperties = {
    background: 'none',
    border: 'none',
    color: 'white',
    fontSize: '20px',
    cursor: 'pointer',
    padding: '0',
    lineHeight: 1,
    opacity: 0.8,
  };

  const errorStyle: preact.JSX.CSSProperties = {
    padding: '8px 16px',
    backgroundColor: '#FEE2E2',
    color: '#991B1B',
    fontSize: '12px',
    textAlign: 'center',
  };

  const handleSubmit = pendingInterrupt
    ? () => {
        if (input.trim()) {
          resumeWithAnswer(input.trim());
          setInput('');
        }
      }
    : sendMessage;

  const inputPlaceholder = pendingInterrupt
    ? '输入回答...'
    : '输入消息...';

  return (
    <div style={windowStyle}>
      <div style={headerStyle}>
        <span style={{ fontSize: '16px', fontWeight: 600 }}>{title}</span>
        <div>
          {messages.length > 0 && (
            <button
              onClick={clearMessages}
              style={{ ...closeButtonStyle, marginRight: '12px', fontSize: '14px' }}
              title="新建对话"
            >
              +
            </button>
          )}
          <button onClick={onClose} style={closeButtonStyle}>×</button>
        </div>
      </div>

      {error && <div style={errorStyle}>{error}</div>}

      <MessageList
        messages={messages}
        timeline={timeline}
        isLoading={isLoading}
        pendingInterrupt={pendingInterrupt}
        onInterruptAnswer={resumeWithAnswer}
      />

      {/* 中断提示（在消息区下方、输入框上方） */}
      {pendingInterrupt && (
        <InterruptBlock
          data={pendingInterrupt}
          onAnswer={resumeWithAnswer}
          disabled={isLoading}
        />
      )}

      <InputBar
        value={input}
        onChange={setInput}
        onSubmit={handleSubmit}
        disabled={isLoading}
        placeholder={inputPlaceholder}
      />
    </div>
  );
}
