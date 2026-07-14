// agent-flow-widget/src/services/session-api.ts

import type { Session, Message, TimelineEntry, ToolStatus } from '../types';
import { buildHeaders, buildUrl } from './api-client';

interface SessionDoc {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
}

interface SessionListResponse {
  items: SessionDoc[];
  total: number;
}

interface RawTimelineEntry {
  type: string;
  content: string;
  tool_name?: string;
  tool_args?: Record<string, unknown>;
  tool_status?: string;
}

interface MessageDoc {
  id: string;
  role: string;
  content: string;
  timeline_entries: RawTimelineEntry[];
  created_at: string;
}

interface SessionDetailResponse {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  messages: MessageDoc[];
}

/**
 * 将后端 ISO 时间字符串转为 number（毫秒时间戳）。
 */
function parseTime(s: string): number {
  const t = Date.parse(s);
  return Number.isFinite(t) ? t : 0;
}

let _idCounter = 0;
function makeTlId(prefix: string): string {
  return `hist-${prefix}-${++_idCounter}`;
}

/**
 * 将后端 timeline_entries 转为前端 TimelineEntry[]，
 * 参考主前端 historyEntryToTimeline 实现：
 * - tool_call + tool_result 合并为单条 tool_call 条目
 * - thinking/text 直接转换
 */
function convertTimeline(entries: RawTimelineEntry[], msgId: string): TimelineEntry[] {
  const result: TimelineEntry[] = [];

  for (const entry of entries) {
    switch (entry.type) {
      case 'thinking':
        result.push({
          id: makeTlId(msgId),
          type: 'thinking',
          content: entry.content,
          timestamp: 0,
          collapsed: true,
        });
        break;

      case 'text':
        result.push({
          id: makeTlId(msgId),
          type: 'text',
          content: entry.content,
          timestamp: 0,
        });
        break;

      case 'tool_call':
        result.push({
          id: makeTlId(msgId),
          type: 'tool_call',
          content: '',
          timestamp: 0,
          toolName: entry.tool_name,
          toolArgs: entry.tool_args,
          toolStatus: 'running' as ToolStatus,
        });
        break;

      case 'tool_result': {
        // 合并到最近的同名 tool_call 条目（反向查找）
        let tool: TimelineEntry | undefined;
        for (let i = result.length - 1; i >= 0; i--) {
          if (result[i].type === 'tool_call' && result[i].toolName === entry.tool_name) {
            tool = result[i];
            break;
          }
        }
        if (tool) {
          tool.content = entry.content;
          tool.toolStatus = 'success' as ToolStatus;
        }
        break;
      }
    }
  }

  return result;
}

/**
 * 获取访客会话列表
 */
export async function listSessions(
  agentId: string,
  visitorId: string
): Promise<Session[]> {
  const url = buildUrl(
    `/api/v1/ext/agents/${encodeURIComponent(agentId)}/sessions?visitor_id=${encodeURIComponent(visitorId)}&page_size=50`
  );

  const response = await fetch(url, {
    method: 'GET',
    headers: buildHeaders(),
  });

  if (!response.ok) {
    throw new Error(`Failed to list sessions: ${response.status}`);
  }

  const data = (await response.json()) as SessionListResponse;

  return data.items.map((doc) => ({
    id: doc.id,
    title: doc.title || '新会话',
    createdAt: parseTime(doc.created_at),
    updatedAt: parseTime(doc.updated_at),
    messageCount: doc.message_count,
  }));
}

/**
 * 获取会话详情（包含历史消息）
 * 参考主前端 historyToMessages：每条 agent 消息携带自己的 timeline
 */
export async function getSessionDetail(
  sessionId: string,
  visitorId: string
): Promise<{ messages: Message[] }> {
  const url = buildUrl(
    `/api/v1/ext/sessions/${encodeURIComponent(sessionId)}?visitor_id=${encodeURIComponent(visitorId)}`
  );

  const response = await fetch(url, {
    method: 'GET',
    headers: buildHeaders(),
  });

  if (!response.ok) {
    throw new Error(`Failed to get session detail: ${response.status}`);
  }

  const data = (await response.json()) as SessionDetailResponse;

  const messages: Message[] = data.messages.map((msg) => {
    const role = msg.role === 'agent' ? 'assistant' : msg.role;

    // agent 消息：从 timeline_entries 构建 timeline 和提取文本
    let content = msg.content || '';
    let timeline: TimelineEntry[] | undefined;

    if (msg.role === 'agent' && msg.timeline_entries?.length) {
      timeline = convertTimeline(msg.timeline_entries, msg.id);
      if (!content) {
        content = msg.timeline_entries
          .filter(e => e.type === 'text')
          .map(e => e.content)
          .join('');
      }
    }

    return {
      id: msg.id,
      role: role as 'user' | 'assistant',
      content,
      timestamp: parseTime(msg.created_at),
      timeline,
    };
  });

  return { messages };
}

/**
 * 删除会话
 */
export async function deleteSession(
  sessionId: string,
  visitorId: string
): Promise<void> {
  const url = buildUrl(
    `/api/v1/ext/sessions/${encodeURIComponent(sessionId)}?visitor_id=${encodeURIComponent(visitorId)}`
  );

  const response = await fetch(url, {
    method: 'DELETE',
    headers: buildHeaders(),
  });

  if (!response.ok) {
    throw new Error(`Failed to delete session: ${response.status}`);
  }
}
