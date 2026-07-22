// agent-flow-widget/src/index.tsx

import type { WidgetConfig } from './types';
import { mountWidget } from './widget';
import { initApiClient } from './services/api-client';

function init(config: WidgetConfig): void {
  if (!config.apiKey) throw new Error('apiKey is required');
  if (!config.agentId) throw new Error('agentId is required');
  if (!config.apiBaseUrl) throw new Error('apiBaseUrl is required');

  initApiClient(config);

  const container = document.createElement('div');
  container.id = 'agent-chat-widget';
  document.body.appendChild(container);

  mountWidget(config, container);
}

(window as any).AgentChat = { init };

// 自动初始化：检测当前 <script> 标签上的 data-* 属性
// <script src="agent-chat.js" data-api-key="sk-xxx" data-agent-id="agent_xxx" data-api-base-url="http://..."></script>
(function autoInit() {
  const scripts = document.querySelectorAll('script[src]');
  for (let i = scripts.length - 1; i >= 0; i--) {
    const el = scripts[i] as HTMLScriptElement;
    const agentId = el.getAttribute('data-agent-id');
    if (!agentId) continue;

    const apiKey = el.getAttribute('data-api-key') || '';
    const apiBaseUrl = el.getAttribute('data-api-base-url') || '';
    const userToken = el.getAttribute('data-user-token') || undefined;
    const title = el.getAttribute('data-title') || undefined;
    const position = (el.getAttribute('data-position') || undefined) as WidgetConfig['position'];

    const suggestedQuestionsAttr = el.getAttribute('data-suggested-questions');
    const suggestedQuestions = suggestedQuestionsAttr
      ? suggestedQuestionsAttr.split(',').map(s => s.trim()).filter(Boolean)
      : undefined;

    init({ apiKey, agentId, apiBaseUrl, userToken, title, position, suggestedQuestions });
    break; // 只初始化第一个匹配的 script
  }
})();
