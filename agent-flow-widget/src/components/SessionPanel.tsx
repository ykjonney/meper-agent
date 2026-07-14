// agent-flow-widget/src/components/SessionPanel.tsx

import type { Session } from '../types';

export interface SessionPanelProps {
  sessions: Session[];
  currentSessionId: string | null;
  onSwitchSession: (sessionId: string) => void;
  onDeleteSession: (sessionId: string) => void;
  onNewSession: () => void;
  onClose: () => void;
  isLoading: boolean;
}

function formatTime(ts: number): string {
  if (!ts) return '';
  const d = new Date(ts);
  const now = new Date();
  const sameDay =
    d.getFullYear() === now.getFullYear() &&
    d.getMonth() === now.getMonth() &&
    d.getDate() === now.getDate();
  if (sameDay) {
    return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
  }
  return `${d.getMonth() + 1}/${d.getDate()}`;
}

export function SessionPanel({
  sessions,
  currentSessionId,
  onSwitchSession,
  onDeleteSession,
  onNewSession,
  onClose,
  isLoading,
}: SessionPanelProps) {
  const panelStyle: preact.JSX.CSSProperties = {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: '#F9FAFB',
    display: 'flex',
    flexDirection: 'column',
    zIndex: 10,
  };

  const headerStyle: preact.JSX.CSSProperties = {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '16px 20px',
    backgroundColor: '#4F46E5',
    color: 'white',
  };

  const iconBtnStyle: preact.JSX.CSSProperties = {
    background: 'none',
    border: 'none',
    color: 'white',
    fontSize: '18px',
    cursor: 'pointer',
    padding: '0',
    lineHeight: 1,
    opacity: 0.8,
  };

  const listStyle: preact.JSX.CSSProperties = {
    flex: 1,
    overflowY: 'auto',
    padding: '8px 0',
  };

  const emptyStyle: preact.JSX.CSSProperties = {
    padding: '40px 20px',
    textAlign: 'center',
    color: '#9CA3AF',
    fontSize: '14px',
  };

  const footerStyle: preact.JSX.CSSProperties = {
    padding: '12px 16px',
    borderTop: '1px solid #E5E7EB',
    backgroundColor: 'white',
  };

  const newBtnStyle: preact.JSX.CSSProperties = {
    width: '100%',
    padding: '10px',
    backgroundColor: '#4F46E5',
    color: 'white',
    border: 'none',
    borderRadius: '8px',
    fontSize: '14px',
    fontWeight: 500,
    cursor: 'pointer',
  };

  const deleteBtnStyle: preact.JSX.CSSProperties = {
    background: 'none',
    border: 'none',
    color: '#9CA3AF',
    fontSize: '14px',
    cursor: 'pointer',
    padding: '2px 6px',
    lineHeight: 1,
    borderRadius: '4px',
  };

  return (
    <div style={panelStyle}>
      <div style={headerStyle}>
        <span style={{ fontSize: '16px', fontWeight: 600 }}>历史会话</span>
        <button onClick={onClose} style={iconBtnStyle} title="关闭">
          ×
        </button>
      </div>

      <div style={listStyle}>
        {isLoading && sessions.length === 0 && (
          <div style={emptyStyle}>加载中...</div>
        )}
        {!isLoading && sessions.length === 0 && (
          <div style={emptyStyle}>暂无历史会话</div>
        )}
        {sessions.map((s) => {
          const isActive = s.id === currentSessionId;
          const itemStyle: preact.JSX.CSSProperties = {
            padding: '12px 20px',
            cursor: 'pointer',
            backgroundColor: isActive ? '#EEF2FF' : 'transparent',
            borderLeft: isActive ? '3px solid #4F46E5' : '3px solid transparent',
            transition: 'background-color 0.15s',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
          };
          return (
            <div
              key={s.id}
              style={itemStyle}
              onClick={() => onSwitchSession(s.id)}
              onMouseEnter={(e) => {
                if (!isActive) (e.currentTarget as HTMLDivElement).style.backgroundColor = '#F3F4F6';
              }}
              onMouseLeave={(e) => {
                if (!isActive) (e.currentTarget as HTMLDivElement).style.backgroundColor = isActive ? '#EEF2FF' : 'transparent';
              }}
            >
              <div style={{ flex: 1, minWidth: 0 }}>
                <div
                  style={{
                    fontSize: '14px',
                    fontWeight: 500,
                    color: '#111827',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                  }}
                >
                  {s.title || '新会话'}
                </div>
                <div
                  style={{
                    fontSize: '12px',
                    color: '#6B7280',
                    marginTop: '4px',
                    display: 'flex',
                    justifyContent: 'space-between',
                  }}
                >
                  <span>{s.messageCount ?? 0} 条消息</span>
                  <span>{formatTime(s.updatedAt)}</span>
                </div>
              </div>
              <button
                style={deleteBtnStyle}
                onClick={(e) => {
                  e.stopPropagation();
                  onDeleteSession(s.id);
                }}
                onMouseEnter={(e) => {
                  (e.currentTarget as HTMLButtonElement).style.color = '#EF4444';
                  (e.currentTarget as HTMLButtonElement).style.backgroundColor = '#FEE2E2';
                }}
                onMouseLeave={(e) => {
                  (e.currentTarget as HTMLButtonElement).style.color = '#9CA3AF';
                  (e.currentTarget as HTMLButtonElement).style.backgroundColor = 'transparent';
                }}
                title="删除会话"
              >
                ✕
              </button>
            </div>
          );
        })}
      </div>

      <div style={footerStyle}>
        <button style={newBtnStyle} onClick={onNewSession}>
          + 新建会话
        </button>
      </div>
    </div>
  );
}
