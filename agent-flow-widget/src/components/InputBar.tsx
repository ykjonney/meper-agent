// agent-flow-widget/src/components/InputBar.tsx

import { useCallback } from 'preact/hooks';

interface InputBarProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  disabled?: boolean;
  placeholder?: string;
}

export function InputBar({ value, onChange, onSubmit, disabled, placeholder }: InputBarProps) {
  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === 'Enter' && !e.shiftKey && !disabled) {
        e.preventDefault();
        onSubmit();
      }
    },
    [onSubmit, disabled]
  );

  const containerStyle: preact.JSX.CSSProperties = {
    display: 'flex',
    alignItems: 'center',
    padding: '12px 16px',
    borderTop: '1px solid #E5E7EB',
    backgroundColor: 'white',
  };

  const inputStyle: preact.JSX.CSSProperties = {
    flex: 1,
    padding: '10px 14px',
    border: '1px solid #D1D5DB',
    borderRadius: '20px',
    fontSize: '14px',
    outline: 'none',
  };

  const buttonStyle: preact.JSX.CSSProperties = {
    marginLeft: '8px',
    padding: '10px 16px',
    backgroundColor: disabled ? '#9CA3AF' : '#4F46E5',
    color: 'white',
    border: 'none',
    borderRadius: '20px',
    fontSize: '14px',
    fontWeight: 500,
    cursor: disabled ? 'not-allowed' : 'pointer',
  };

  return (
    <div style={containerStyle}>
      <input
        type="text"
        value={value}
        onInput={(e) => onChange((e.target as HTMLInputElement).value)}
        onKeyDown={handleKeyDown as any}
        onFocus={(e) => { (e.target as HTMLInputElement).style.borderColor = '#4F46E5'; }}
        onBlur={(e) => { (e.target as HTMLInputElement).style.borderColor = '#D1D5DB'; }}
        placeholder={placeholder || '输入消息...'}
        disabled={disabled}
        style={inputStyle}
      />
      <button onClick={onSubmit} disabled={disabled} style={buttonStyle}>
        发送
      </button>
    </div>
  );
}
