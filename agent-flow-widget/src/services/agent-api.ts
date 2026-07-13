// agent-flow-widget/src/services/agent-api.ts

import type { StreamEvent, InvokeRequest } from '../types';
import { buildHeaders, buildUrl, getConfig } from './api-client';

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
        if (line.startsWith('data: ')) {
          const data = line.slice(6).trim();
          if (data === '[DONE]') continue;

          try {
            const parsed = JSON.parse(data);
            if (parsed.type === 'text' || parsed.content) {
              yield { type: 'text', content: parsed.content || parsed.text || '' };
            }
          } catch {
            // 非 JSON 数据，当作纯文本处理
            if (data && !data.startsWith('event:')) {
              yield { type: 'text', content: data };
            }
          }
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}
