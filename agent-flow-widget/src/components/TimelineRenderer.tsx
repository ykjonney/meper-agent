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

/**
 * 将 timeline 按顺序分组：连续的 text 条目合并为一组，
 * 其他条目各自独立一组。参考主前端 chat-panel 的渲染逻辑。
 */
type Group =
  | { kind: 'text'; entries: TimelineEntry[] }
  | { kind: 'single'; entry: TimelineEntry };

function groupEntries(timeline: TimelineEntry[]): Group[] {
  const groups: Group[] = [];
  for (const entry of timeline) {
    if (entry.type === 'text') {
      const last = groups[groups.length - 1];
      if (last && last.kind === 'text') {
        last.entries.push(entry);
        continue;
      }
      groups.push({ kind: 'text', entries: [entry] });
    } else {
      groups.push({ kind: 'single', entry });
    }
  }
  return groups;
}

export function TimelineRenderer({ timeline, onInterruptAnswer, interruptDisabled }: TimelineRendererProps) {
  // 与 MessageBubble 中 assistant 样式一致
  const containerStyle: preact.JSX.CSSProperties = {
    display: 'flex',
    justifyContent: 'flex-start',
    marginBottom: '12px',
    padding: '0 16px',
  };

  const bubbleStyle: preact.JSX.CSSProperties = {
    maxWidth: '80%',
    padding: '10px 14px',
    borderRadius: '16px 16px 16px 4px',
    backgroundColor: '#F3F4F6',
    color: '#1F2937',
    fontSize: '14px',
    lineHeight: '1.5',
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

  const groups = groupEntries(timeline);

  return (
    <div>
      {groups.map((group, gi) => {
        if (group.kind === 'text') {
          // 连续 text 条目合并在同一个气泡中
          return (
            <div key={`tg-${gi}`} style={containerStyle}>
              <div style={bubbleStyle}>
                {group.entries.map((entry, idx) => (
                  <div
                    key={entry.id}
                    dangerouslySetInnerHTML={{ __html: renderMarkdown(entry.content) }}
                    style={idx > 0 ? { marginTop: '8px' } : undefined}
                  />
                ))}
              </div>
            </div>
          );
        }

        const entry = group.entry;
        switch (entry.type) {
          case 'thinking':
            return (
              <ThinkingBlock
                key={entry.id}
                content={entry.content}
                collapsed={entry.collapsed}
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
