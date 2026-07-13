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
