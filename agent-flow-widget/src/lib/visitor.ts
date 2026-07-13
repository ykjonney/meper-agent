// agent-flow-widget/src/lib/visitor.ts

const STORAGE_KEY = 'agent-chat-visitor-id';

/**
 * 获取或创建 visitor ID
 * 首次调用时生成 UUID 并存入 localStorage
 * 后续调用从 localStorage 读取
 */
export function getOrCreateVisitorId(): string {
  let visitorId = localStorage.getItem(STORAGE_KEY);

  if (!visitorId) {
    visitorId = crypto.randomUUID();
    localStorage.setItem(STORAGE_KEY, visitorId);
  }

  return visitorId;
}

/**
 * 清除 visitor ID（用于调试）
 */
export function clearVisitorId(): void {
  localStorage.removeItem(STORAGE_KEY);
}
