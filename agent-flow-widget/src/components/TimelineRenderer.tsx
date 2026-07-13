// agent-flow-widget/src/components/TimelineRenderer.tsx

import type { TimelineEntry } from '../types';
import { ThinkingBlock } from './ThinkingBlock';
import { ToolCallBlock } from './ToolCallBlock';
import { InterruptBlock } from './InterruptBlock';
import type { InterruptData } from '../types';

interface TimelineRendererProps {
  timeline: TimelineEntry[];
  onInterruptAnswer?: (answer: string) => void;
  interruptDisabled?: boolean;
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

export function TimelineRenderer({ timeline, onInterruptAnswer, interruptDisabled }: TimelineRendererProps) {
  const textStyle: preact.JSX.CSSProperties = {
    margin: '4px 16px',
    padding: '0',
    fontSize: '14px',
    lineHeight: '1.6',
    color: '#1F2937',
    wordBreak: 'break-word',
  };

  const errorStyle: preact.JSX.CSSProperties = {
    margin: '8px 16px',
    padding: '10px 14px',
    borderRadius: '8px',
    backgroundColor: '#FEE2E2',
    color: '#991B1B',
    fontSize: '13px',
  };

  return (
    <div>
      {timeline.map((entry) => {
        switch (entry.type) {
          case 'thinking':
            return (
              <ThinkingBlock
                key={entry.id}
                content={entry.content}
                collapsed={entry.collapsed}
              />
            );

          case 'text':
            return (
              <div
                key={entry.id}
                style={textStyle}
                dangerouslySetInnerHTML={{ __html: renderMarkdown(entry.content) }}
              />
            );

          case 'tool_call':
            return (
              <ToolCallBlock
                key={entry.id}
                toolName={entry.toolName || ''}
                toolArgs={entry.toolArgs}
                content={entry.content}
                status={entry.toolStatus}
              />
            );

          case 'error':
            return (
              <div key={entry.id} style={errorStyle}>
                {entry.content || '发生错误'}
              </div>
            );

          case 'interrupt':
            if (!onInterruptAnswer) return null;
            return (
              <InterruptBlock
                key={entry.id}
                data={{
                  question: entry.content,
                  options: (entry as TimelineEntry & { options?: string[] }).options,
                } as InterruptData}
                onAnswer={onInterruptAnswer}
                disabled={interruptDisabled}
              />
            );

          default:
            return null;
        }
      })}
    </div>
  );
}
