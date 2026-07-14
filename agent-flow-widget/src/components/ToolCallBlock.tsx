// agent-flow-widget/src/components/ToolCallBlock.tsx

import { useState } from 'preact/hooks';
import type { ToolStatus } from '../types';

interface ToolCallBlockProps {
  toolName: string;
  toolArgs?: Record<string, unknown>;
  content: string;
  status?: ToolStatus;
}

function getStatusIcon(status?: ToolStatus): string {
  switch (status) {
    case 'pending':
    case 'running':
      return '◌';
    case 'success':
      return '✓';
    case 'error':
      return '✗';
    default:
      return '◌';
  }
}

function getStatusColor(status?: ToolStatus): string {
  switch (status) {
    case 'pending':
    case 'running':
      return '#F59E0B';
    case 'success':
      return '#10B981';
    case 'error':
      return '#EF4444';
    default:
      return '#6B7280';
  }
}

export function ToolCallBlock({ toolName, toolArgs, content, status }: ToolCallBlockProps) {
  const [expanded, setExpanded] = useState(false);

  const containerStyle: preact.JSX.CSSProperties = {
    margin: '6px 16px',
    borderRadius: '8px',
    border: '1px solid #E5E7EB',
    overflow: 'hidden',
    fontSize: '13px',
  };

  const headerStyle: preact.JSX.CSSProperties = {
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
    padding: '8px 12px',
    backgroundColor: '#F9FAFB',
    cursor: 'pointer',
    userSelect: 'none',
    border: 'none',
    width: '100%',
    textAlign: 'left',
  };

  const iconStyle: preact.JSX.CSSProperties = {
    color: getStatusColor(status),
    fontSize: '14px',
    fontWeight: 'bold',
    animation: (status === 'pending' || status === 'running') ? 'afSpin 1s linear infinite' : 'none',
  };

  const nameStyle: preact.JSX.CSSProperties = {
    flex: 1,
    color: '#374151',
    fontWeight: 500,
  };

  const arrowStyle: preact.JSX.CSSProperties = {
    color: '#9CA3AF',
    fontSize: '10px',
    transition: 'transform 0.2s',
    transform: expanded ? 'rotate(0deg)' : 'rotate(-90deg)',
  };

  const detailsStyle: preact.JSX.CSSProperties = {
    padding: '8px 12px',
    borderTop: '1px solid #E5E7EB',
    backgroundColor: '#FAFAFA',
    fontSize: '12px',
    color: '#4B5563',
  };

  const labelStyle: preact.JSX.CSSProperties = {
    color: '#9CA3AF',
    fontSize: '11px',
    marginBottom: '4px',
  };

  const codeStyle: preact.JSX.CSSProperties = {
    background: '#F3F4F6',
    padding: '6px 8px',
    borderRadius: '4px',
    fontSize: '11px',
    whiteSpace: 'pre-wrap',
    wordBreak: 'break-all',
    maxHeight: '150px',
    overflowY: 'auto',
    marginTop: '4px',
  };

  const hasDetails = toolArgs && Object.keys(toolArgs).length > 0;
  const hasResult = !!content;

  return (
    <div style={containerStyle}>
      <button style={headerStyle} onClick={() => setExpanded(!expanded)}>
        <span style={iconStyle}>{getStatusIcon(status)}</span>
        <span style={nameStyle}>{toolName || '工具调用'}</span>
        {(hasDetails || hasResult) && <span style={arrowStyle}>▼</span>}
      </button>
      {expanded && (hasDetails || hasResult) && (
        <div style={detailsStyle}>
          {hasDetails && (
            <div style={{ marginBottom: hasResult ? '8px' : '0' }}>
              <div style={labelStyle}>参数</div>
              <pre style={codeStyle}>{JSON.stringify(toolArgs, null, 2)}</pre>
            </div>
          )}
          {hasResult && (
            <div>
              <div style={labelStyle}>结果</div>
              <pre style={codeStyle}>{content}</pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
