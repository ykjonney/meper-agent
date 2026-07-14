// agent-flow-widget/src/components/InterruptBlock.tsx

import type { InterruptData } from '../types';

interface InterruptBlockProps {
  data: InterruptData;
  onAnswer: (answer: string) => void;
  disabled?: boolean;
}

export function InterruptBlock({ data, onAnswer, disabled }: InterruptBlockProps) {
  const containerStyle: preact.JSX.CSSProperties = {
    margin: '8px 16px',
    padding: '12px 16px',
    borderRadius: '12px',
    border: '1px solid #FDE68A',
    backgroundColor: '#FFFBEB',
  };

  const questionStyle: preact.JSX.CSSProperties = {
    fontSize: '13px',
    color: '#92400E',
    lineHeight: '1.5',
    marginBottom: data.options && data.options.length > 0 ? '10px' : '0',
    whiteSpace: 'pre-wrap',
  };

  const optionsStyle: preact.JSX.CSSProperties = {
    display: 'flex',
    flexWrap: 'wrap',
    gap: '6px',
  };

  const optionBtnStyle: preact.JSX.CSSProperties = {
    padding: '6px 12px',
    borderRadius: '16px',
    border: '1px solid #F59E0B',
    backgroundColor: 'white',
    color: '#92400E',
    fontSize: '12px',
    cursor: disabled ? 'not-allowed' : 'pointer',
    transition: 'background-color 0.2s',
  };

  return (
    <div style={containerStyle}>
      <div style={questionStyle}>{data.question}</div>
      {data.options && data.options.length > 0 && (
        <div style={optionsStyle}>
          {data.options.map((option, i) => (
            <button
              key={i}
              style={optionBtnStyle}
              disabled={disabled}
              onClick={() => onAnswer(option)}
              onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = '#FEF3C7'; }}
              onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = 'white'; }}
            >
              {option}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
