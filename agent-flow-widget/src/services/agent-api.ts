// agent-flow-widget/src/services/agent-api.ts

import type { StreamEvent, InvokeRequest } from '../types';
import { buildHeaders, buildUrl, getConfig } from './api-client';

/** SSE 事件类型分发映射 */
const typeMap: Record<string, (p: Record<string, unknown>) => StreamEvent | null> = {
  text_delta: (p) => ({ type: 'text_delta', content: String(p.content || '') }),
  text: (p) => ({ type: 'text', content: String(p.content || '') }),
  thinking_delta: (p) => ({ type: 'thinking_delta', content: String(p.content || '') }),
  thinking: (p) => ({ type: 'thinking', content: String(p.content || '') }),
  tool_call_start: () => ({ type: 'tool_call_start' }),
  tool_call: (p) => ({
    type: 'tool_call',
    tool_name: String(p.tool_name || ''),
    args: (p.args as Record<string, unknown>) || {},
    id: String(p.id || ''),
  }),
  tool_result: (p) => ({
    type: 'tool_result',
    tool_name: String(p.tool_name || ''),
    content: String(p.content || ''),
  }),
  interrupt: (p) => ({
    type: 'interrupt',
    question: String(p.question || ''),
    clarification_type: p.clarification_type as string | undefined,
    context: p.context as string | undefined,
    options: p.options as string[] | undefined,
    interrupt_id: p.interrupt_id as string | undefined,
  }),
  error: (p) => ({
    type: 'error',
    message: String(p.message || ''),
    source: p.source as string | undefined,
  }),
};

/**
 * 从 ReadableStream 解析 SSE 事件
 */
async function* parseSSEStream(reader: ReadableStreamDefaultReader<Uint8Array>): AsyncGenerator<StreamEvent> {
  const decoder = new TextDecoder();
  let buffer = '';

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;

        const data = line.slice(6).trim();
        if (data === '[DONE]') continue;

        try {
          const parsed = JSON.parse(data) as Record<string, unknown>;
          const handler = typeMap[String(parsed.type ?? '')];
          if (handler) {
            const event = handler(parsed);
            if (event) yield event;
          }
          // 未知类型忽略
        } catch {
          // 非 JSON 数据，当作纯文本处理
          if (data && !data.startsWith('event:')) {
            yield { type: 'text', content: data };
          }
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}

/**
 * 流式调用 Agent
 * 返回异步迭代器，逐条产出 StreamEvent
 */
export async function* streamAgentMessage(
  request: InvokeRequest
): AsyncGenerator<StreamEvent> {
  const { agentId } = getConfig();
  const url = buildUrl(`/api/v1/ext/agents/${agentId}/invoke/stream`);

  const response = await fetch(url, {
    method: 'POST',
    headers: buildHeaders(),
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    const errorText = await response.text();
    yield { type: 'error', message: `请求失败: ${response.status} ${errorText}` };
    return;
  }

  const sessionId = response.headers.get('X-Session-Id');
  if (sessionId) {
    yield { type: 'done', session_id: sessionId };
  }

  const reader = response.body?.getReader();
  if (!reader) {
    yield { type: 'error', message: '无法读取响应流' };
    return;
  }

  yield* parseSSEStream(reader);
}

/**
 * 恢复被中断的 Agent（SSE 流式）
 */
export async function* resumeAgentMessage(
  sessionId: string,
  answer: string,
  visitorId: string
): AsyncGenerator<StreamEvent> {
  const { agentId } = getConfig();
  const url = buildUrl(`/api/v1/ext/agents/${agentId}/invoke/resume`);

  const response = await fetch(url, {
    method: 'POST',
    headers: buildHeaders(),
    body: JSON.stringify({ session_id: sessionId, answer, visitor_id: visitorId }),
  });

  if (!response.ok) {
    const errorText = await response.text();
    yield { type: 'error', message: `恢复请求失败: ${response.status} ${errorText}` };
    return;
  }

  const reader = response.body?.getReader();
  if (!reader) {
    yield { type: 'error', message: '无法读取响应流' };
    return;
  }

  yield* parseSSEStream(reader);
}
