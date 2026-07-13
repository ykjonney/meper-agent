// agent-flow-widget/src/components/ThinkingBlock.tsx

import { useState } from 'preact/hooks';

interface ThinkingBlockProps {
  content: string;
  collapsed?: boolean;
}

export function ThinkingBlock({ content, collapsed: initialCollapsed = true }: ThinkingBlockProps) {
  const [collapsed, setCollapsed] = useState(initialCollapsed);

  const containerStyle: preact.JSX.CSSProperties = {
    margin: '8px 16px',
    borderRadius: '8px',
    border: '1px solid #E5E7EB',
    overflow: 'hidden',
  };

  const headerStyle: preact.JSX.CSSProperties = {
    display: 'flex',
    alignItems: 'center',
    gap: '6px',
    padding: '8px 12px',
    backgroundColor: '#F9FAFB',
    cursor: 'pointer',
    fontSize: '12px',
    color: '#6B7280',
    userSelect: 'none',
    border: 'none',
    width: '100%',
    textAlign: 'left',
  };

  const arrowStyle: preact.JSX.CSSProperties = {
    display: 'inline-block',
    transition: 'transform 0.2s',
    transform: collapsed ? 'rotate(-90deg)' : 'rotate(0deg)',
    fontSize: '10px',
  };

  const contentStyle: preact.JSX.CSSProperties = {
    padding: collapsed ? '0 12px' : '10px 12px',
    fontSize: '13px',
    lineHeight: '1.6',
    color: '#4B5563',
    maxHeight: collapsed ? '0' : '400px',
    overflow: 'hidden',
    transition: 'max-height 0.3s ease, padding 0.3s ease',
    whiteSpace: 'pre-wrap',
    wordBreak: 'break-word',
  };

  return (
    <div style={containerStyle}>
      <button style={headerStyle} onClick={() => setCollapsed(!collapsed)}>
        <span style={arrowStyle}>▼</span>
        <span>思考过程</span>
      </button>
      <div style={contentStyle}>{content || '思考中...'}</div>
    </div>
  );
}
