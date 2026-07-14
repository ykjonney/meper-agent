// agent-flow-widget/src/components/ChatWindow.tsx

import { useState, useEffect, useCallback, useRef } from 'preact/hooks';
import { useChat } from '../hooks/useChat';
import { MessageList } from './MessageList';
import { InputBar } from './InputBar';
import { InterruptBlock } from './InterruptBlock';
import { SessionPanel } from './SessionPanel';
import { getConfig } from '../services/api-client';

const STORAGE_KEY = 'agent-chat-window-size';
const DEFAULT_SUGGESTED_QUESTIONS = [
  '搭建工艺路线',
  '追溯SN条码的过站信息',
  '创建自定义表',
  '导入物料',
  '建模工厂数据',
  '查看工单生产状态',
];
const DEFAULT_SIZE = { width: 380, height: 560 };
const MIN_WIDTH = 320;
const MAX_WIDTH = 800;
const MIN_HEIGHT = 400;
const MAX_HEIGHT = 800;

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
    sessionId,
    pendingInterrupt,
    resumeWithAnswer,
    sessions,
    isSessionsLoading,
    loadSessions,
    switchSession,
    deleteSession,
    newSession,
  } = useChat();

  const [size, setSize] = useState(DEFAULT_SIZE);
  const [isResizing, setIsResizing] = useState(false);
  const [showSessions, setShowSessions] = useState(false);
  const [suggestedQuestions, setSuggestedQuestions] = useState<string[]>([]);
  const sizeRef = useRef(size);
  sizeRef.current = size;

  // 预定义问题：config 配置优先，否则使用内置默认值
  useEffect(() => {
    const config = getConfig();
    setSuggestedQuestions(config.suggestedQuestions?.length ? config.suggestedQuestions : DEFAULT_SUGGESTED_QUESTIONS);
  }, []);

  useEffect(() => {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved) {
      try {
        const parsed = JSON.parse(saved);
        if (parsed.width && parsed.height) {
          setSize({
            width: Math.min(Math.max(parsed.width, MIN_WIDTH), MAX_WIDTH),
            height: Math.min(Math.max(parsed.height, MIN_HEIGHT), MAX_HEIGHT),
          });
        }
      } catch { /* ignore */ }
    }
  }, []);

  // Load sessions when panel opens
  useEffect(() => {
    if (showSessions) {
      loadSessions();
    }
  }, [showSessions, loadSessions]);

  const handleResizeStart = useCallback((e: MouseEvent) => {
    e.preventDefault();
    setIsResizing(true);
    const startX = e.clientX;
    const startY = e.clientY;
    const startWidth = sizeRef.current.width;
    const startHeight = sizeRef.current.height;

    // 左上角拖拽：鼠标向左/向上 = 窗口变大
    const handleMouseMove = (e: MouseEvent) => {
      const newWidth = Math.min(Math.max(startWidth - (e.clientX - startX), MIN_WIDTH), MAX_WIDTH);
      const newHeight = Math.min(Math.max(startHeight - (e.clientY - startY), MIN_HEIGHT), MAX_HEIGHT);
      setSize({ width: newWidth, height: newHeight });
    };

    const handleMouseUp = () => {
      setIsResizing(false);
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
      localStorage.setItem(STORAGE_KEY, JSON.stringify(sizeRef.current));
    };

    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);
  }, []);

  const windowStyle: preact.JSX.CSSProperties = {
    position: 'fixed',
    bottom: '90px',
    right: '20px',
    width: `${size.width}px`,
    height: `${size.height}px`,
    backgroundColor: 'white',
    borderRadius: '16px',
    boxShadow: '0 8px 32px rgba(0, 0, 0, 0.12)',
    display: 'flex',
    flexDirection: 'column',
    overflow: 'hidden',
    zIndex: 999999,
    userSelect: isResizing ? 'none' : 'auto',
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

  const handleSwitchSession = (id: string) => {
    switchSession(id);
    setShowSessions(false);
  };

  const handleNewSession = () => {
    newSession();
    setShowSessions(false);
  };

  const handleDeleteSession = async (id: string) => {
    if (confirm('确定删除该会话？')) {
      await deleteSession(id);
    }
  };

  const bodyStyle: preact.JSX.CSSProperties = {
    flex: 1,
    display: 'flex',
    flexDirection: 'column',
    position: 'relative',
    overflow: 'hidden',
  };

  return (
    <div style={windowStyle}>
      <div style={headerStyle}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <button
            onClick={() => setShowSessions((v) => !v)}
            style={closeButtonStyle}
            title="历史会话"
          >
            ☰
          </button>
          <span style={{ fontSize: '16px', fontWeight: 600 }}>{title}</span>
        </div>
        <div>
          {messages.length > 0 && (
            <button
              onClick={handleNewSession}
              style={{ ...closeButtonStyle, marginRight: '12px', fontSize: '14px' }}
              title="新建对话"
            >
              +
            </button>
          )}
          <button onClick={onClose} style={closeButtonStyle}>×</button>
        </div>
      </div>

      <div style={bodyStyle}>
        {error && <div style={errorStyle}>{error}</div>}

        <MessageList
          messages={messages}
          timeline={timeline}
          isLoading={isLoading}
          pendingInterrupt={pendingInterrupt}
          onInterruptAnswer={resumeWithAnswer}
          suggestedQuestions={suggestedQuestions}
          onSuggestedQuestion={(q) => setInput(q)}
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

        {showSessions && (
          <SessionPanel
            sessions={sessions}
            currentSessionId={sessionId}
            onSwitchSession={handleSwitchSession}
            onDeleteSession={handleDeleteSession}
            onNewSession={handleNewSession}
            onClose={() => setShowSessions(false)}
            isLoading={isSessionsLoading}
          />
        )}
      </div>

      <div
        onMouseDown={handleResizeStart as any}
        style={{
          position: 'absolute',
          top: 0,
          left: 0,
          width: '16px',
          height: '16px',
          cursor: 'nwse-resize',
          zIndex: 1,
        }}
        title="拖拽调整大小"
      >
        <svg
          width="10"
          height="10"
          viewBox="0 0 10 10"
          style={{ position: 'absolute', left: '3px', top: '3px' }}
        >
          <path d="M1 1L9 9M1 5L5 9M1 1L1 1" stroke="#999" strokeWidth="1.2" strokeLinecap="round" />
        </svg>
      </div>
    </div>
  );
}
