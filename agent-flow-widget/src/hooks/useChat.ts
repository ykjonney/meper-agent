// agent-flow-widget/src/hooks/useChat.ts

import { useState, useCallback, useRef } from 'preact/hooks';
import type { Message } from '../types';
import { streamAgentMessage } from '../services/agent-api';
import { getOrCreateVisitorId } from '../lib/visitor';

interface UseChatReturn {
  messages: Message[];
  input: string;
  setInput: (value: string) => void;
  sendMessage: () => Promise<void>;
  isLoading: boolean;
  error: string | null;
  sessionId: string | null;
  clearMessages: () => void;
}

export function useChat(): UseChatReturn {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);

  const visitorId = useRef(getOrCreateVisitorId());

  const sendMessage = useCallback(async () => {
    if (!input.trim() || isLoading) return;

    const userMessage: Message = {
      id: crypto.randomUUID(),
      role: 'user',
      content: input.trim(),
      timestamp: Date.now(),
    };

    const assistantMessage: Message = {
      id: crypto.randomUUID(),
      role: 'assistant',
      content: '',
      timestamp: Date.now(),
      streaming: true,
    };

    setMessages(prev => [...prev, userMessage, assistantMessage]);
    setInput('');
    setIsLoading(true);
    setError(null);

    try {
      const stream = streamAgentMessage({
        message: userMessage.content,
        session_id: sessionId || undefined,
        visitor_id: visitorId.current,
      });

      for await (const event of stream) {
        if (event.type === 'text') {
          setMessages(prev => {
            const updated = [...prev];
            const last = updated[updated.length - 1];
            if (last && last.role === 'assistant') {
              updated[updated.length - 1] = {
                ...last,
                content: last.content + event.content,
              };
            }
            return updated;
          });
        } else if (event.type === 'done') {
          setSessionId(event.session_id);
          setMessages(prev => {
            const updated = [...prev];
            const last = updated[updated.length - 1];
            if (last && last.role === 'assistant') {
              updated[updated.length - 1] = { ...last, streaming: false };
            }
            return updated;
          });
        } else if (event.type === 'error') {
          setError(event.message);
          setMessages(prev => prev.slice(0, -1)); // 移除空的 assistant 消息
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '未知错误');
      setMessages(prev => prev.slice(0, -1));
    } finally {
      setIsLoading(false);
    }
  }, [input, isLoading, sessionId]);

  const clearMessages = useCallback(() => {
    setMessages([]);
    setSessionId(null);
    setError(null);
  }, []);

  return {
    messages,
    input,
    setInput,
    sendMessage,
    isLoading,
    error,
    sessionId,
    clearMessages,
  };
}
