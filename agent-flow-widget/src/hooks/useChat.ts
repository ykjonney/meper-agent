// agent-flow-widget/src/hooks/useChat.ts

import { useState, useCallback, useRef } from 'preact/hooks';
import type { Message, TimelineEntry, InterruptData, ToolStatus } from '../types';
import { streamAgentMessage, resumeAgentMessage } from '../services/agent-api';
import { getOrCreateVisitorId } from '../lib/visitor';

interface UseChatReturn {
  messages: Message[];
  timeline: TimelineEntry[];
  input: string;
  setInput: (value: string) => void;
  sendMessage: () => Promise<void>;
  isLoading: boolean;
  error: string | null;
  sessionId: string | null;
  clearMessages: () => void;
  pendingInterrupt: InterruptData | null;
  resumeWithAnswer: (answer: string) => Promise<void>;
}

let entryCounter = 0;
function makeId(): string {
  return `tl-${Date.now()}-${++entryCounter}`;
}

/**
 * 查找 timeline 中最后一条匹配 type（及可选 status）的条目
 */
function findLastEntry(
  tl: TimelineEntry[],
  type: string,
  status?: ToolStatus
): TimelineEntry | undefined {
  for (let i = tl.length - 1; i >= 0; i--) {
    const e = tl[i];
    if (e.type === type && (status === undefined || e.toolStatus === status)) {
      return e;
    }
  }
  return undefined;
}

/**
 * 处理 SSE 事件流，更新 timeline 与相关状态
 */
async function processStream(
  stream: AsyncGenerator<{ type: string; [k: string]: unknown }>,
  setTimeline: (updater: (prev: TimelineEntry[]) => TimelineEntry[]) => void,
  setMessages: (updater: (prev: Message[]) => Message[]) => void,
  setSessionId: (id: string) => void,
  setError: (msg: string | null) => void,
  setPendingInterrupt: (data: InterruptData | null) => void,
  assistantMsgId: string,
  isResume: boolean
): Promise<void> {
  for await (const event of stream) {
    switch (event.type) {
      case 'text_delta': {
        const content = String(event.content || '');
        setTimeline(prev => {
          const last = findLastEntry(prev, 'text');
          if (last) {
            return prev.map(e => e.id === last.id ? { ...e, content: e.content + content } : e);
          }
          return [...prev, { id: makeId(), type: 'text', content, timestamp: Date.now() }];
        });
        // 同步更新 assistant message content（向后兼容）
        setMessages(prev => {
          const idx = prev.findIndex(m => m.id === assistantMsgId);
          if (idx === -1) return prev;
          return prev.map((m, i) => i === idx ? { ...m, content: m.content + content } : m);
        });
        break;
      }

      case 'text': {
        // text 事件可能是完整文本块，也可能是增量（取决于后端实现）
        // 采用增量追加，与 text_delta 一致
        const content = String(event.content || '');
        setTimeline(prev => {
          const last = findLastEntry(prev, 'text');
          if (last) {
            return prev.map(e => e.id === last.id ? { ...e, content: e.content + content } : e);
          }
          return [...prev, { id: makeId(), type: 'text', content, timestamp: Date.now() }];
        });
        setMessages(prev => {
          const idx = prev.findIndex(m => m.id === assistantMsgId);
          if (idx === -1) return prev;
          return prev.map((m, i) => i === idx ? { ...m, content: m.content + content } : m);
        });
        break;
      }

      case 'thinking_delta':
      case 'thinking': {
        const content = String(event.content || '');
        setTimeline(prev => {
          const last = findLastEntry(prev, 'thinking');
          if (last) {
            return prev.map(e => e.id === last.id ? { ...e, content: e.content + content } : e);
          }
          return [...prev, {
            id: makeId(), type: 'thinking', content, timestamp: Date.now(), collapsed: true,
          }];
        });
        break;
      }

      case 'tool_call_start': {
        setTimeline(prev => [...prev, {
          id: makeId(),
          type: 'tool_call',
          content: '',
          timestamp: Date.now(),
          toolStatus: 'pending' as ToolStatus,
        }]);
        break;
      }

      case 'tool_call': {
        setTimeline(prev => {
          const pending = findLastEntry(prev, 'tool_call', 'pending');
          if (pending) {
            return prev.map(e =>
              e.id === pending.id
                ? { ...e, toolName: String(event.tool_name || ''), toolArgs: event.args as Record<string, unknown>, toolStatus: 'running' as ToolStatus }
                : e
            );
          }
          return [...prev, {
            id: makeId(),
            type: 'tool_call',
            content: '',
            timestamp: Date.now(),
            toolName: String(event.tool_name || ''),
            toolArgs: event.args as Record<string, unknown>,
            toolStatus: 'running' as ToolStatus,
          }];
        });
        break;
      }

      case 'tool_result': {
        setTimeline(prev => {
          const running = findLastEntry(prev, 'tool_call', 'running');
          if (running) {
            return prev.map(e =>
              e.id === running.id
                ? { ...e, content: String(event.content || ''), toolStatus: 'success' as ToolStatus }
                : e
            );
          }
          const pending = findLastEntry(prev, 'tool_call', 'pending');
          if (pending) {
            return prev.map(e =>
              e.id === pending.id
                ? { ...e, content: String(event.content || ''), toolName: String(event.tool_name || ''), toolStatus: 'success' as ToolStatus }
                : e
            );
          }
          return prev;
        });
        break;
      }

      case 'interrupt': {
        const data: InterruptData = {
          question: String(event.question || ''),
          clarification_type: event.clarification_type as string | undefined,
          context: event.context as string | undefined,
          options: event.options as string[] | undefined,
          interrupt_id: event.interrupt_id as string | undefined,
        };
        setPendingInterrupt(data);
        setTimeline(prev => [...prev, {
          id: makeId(),
          type: 'interrupt',
          content: data.question,
          timestamp: Date.now(),
        }]);
        // 完成当前 assistant 消息（流暂停）
        setMessages(prev => {
          const idx = prev.findIndex(m => m.id === assistantMsgId);
          if (idx === -1) return prev;
          return prev.map((m, i) => i === idx ? { ...m, streaming: false } : m);
        });
        break;
      }

      case 'error': {
        setError(String(event.message || ''));
        setTimeline(prev => [...prev, {
          id: makeId(),
          type: 'error',
          content: String(event.message || '未知错误'),
          timestamp: Date.now(),
        }]);
        if (!isResume) {
          // 非 resume 模式下移除空 assistant 消息
          setMessages(prev => prev.filter(m => m.id !== assistantMsgId));
        }
        break;
      }

      case 'done': {
        setSessionId(String(event.session_id || ''));
        setMessages(prev => {
          const idx = prev.findIndex(m => m.id === assistantMsgId);
          if (idx === -1) return prev;
          return prev.map((m, i) => i === idx ? { ...m, streaming: false } : m);
        });
        break;
      }
    }
  }
}

export function useChat(): UseChatReturn {
  const [messages, setMessages] = useState<Message[]>([]);
  const [timeline, setTimeline] = useState<TimelineEntry[]>([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [pendingInterrupt, setPendingInterrupt] = useState<InterruptData | null>(null);

  const visitorId = useRef(getOrCreateVisitorId());

  const sendMessage = useCallback(async () => {
    if (!input.trim() || isLoading) return;

    const userMessage: Message = {
      id: makeId(),
      role: 'user',
      content: input.trim(),
      timestamp: Date.now(),
    };

    const assistantMsgId = makeId();
    const assistantMessage: Message = {
      id: assistantMsgId,
      role: 'assistant',
      content: '',
      timestamp: Date.now(),
      streaming: true,
    };

    setMessages(prev => [...prev, userMessage, assistantMessage]);
    setTimeline([]);
    setInput('');
    setIsLoading(true);
    setError(null);
    setPendingInterrupt(null);

    try {
      const stream = streamAgentMessage({
        message: userMessage.content,
        session_id: sessionId || undefined,
        visitor_id: visitorId.current,
      });

      await processStream(
        stream, setTimeline, setMessages, setSessionId, setError,
        setPendingInterrupt, assistantMsgId, false
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : '未知错误');
      setMessages(prev => prev.filter(m => m.id !== assistantMsgId));
    } finally {
      setIsLoading(false);
    }
  }, [input, isLoading, sessionId]);

  const resumeWithAnswer = useCallback(async (answer: string) => {
    if (!answer.trim() || !sessionId || isLoading) return;

    const interruptData = pendingInterrupt;
    setPendingInterrupt(null);

    const assistantMsgId = makeId();
    const assistantMessage: Message = {
      id: assistantMsgId,
      role: 'assistant',
      content: '',
      timestamp: Date.now(),
      streaming: true,
    };

    setMessages(prev => [...prev, assistantMessage]);
    setIsLoading(true);
    setError(null);

    try {
      const stream = resumeAgentMessage(sessionId, answer.trim(), visitorId.current);

      await processStream(
        stream, setTimeline, setMessages, setSessionId, setError,
        setPendingInterrupt, assistantMsgId, true
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : '恢复失败');
      setMessages(prev => prev.filter(m => m.id !== assistantMsgId));
      // 恢复失败时重新显示 interrupt
      if (interruptData) setPendingInterrupt(interruptData);
    } finally {
      setIsLoading(false);
    }
  }, [sessionId, isLoading, pendingInterrupt]);

  const clearMessages = useCallback(() => {
    setMessages([]);
    setTimeline([]);
    setSessionId(null);
    setError(null);
    setPendingInterrupt(null);
  }, []);

  return {
    messages,
    timeline,
    input,
    setInput,
    sendMessage,
    isLoading,
    error,
    sessionId,
    clearMessages,
    pendingInterrupt,
    resumeWithAnswer,
  };
}
