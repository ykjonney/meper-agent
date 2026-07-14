// agent-flow-widget/src/services/api-client.ts

import type { WidgetConfig } from '../types';

let config: WidgetConfig;

/**
 * 初始化 API 客户端配置
 */
export function initApiClient(widgetConfig: WidgetConfig): void {
  config = widgetConfig;
}

/**
 * 获取当前配置
 */
export function getConfig(): WidgetConfig {
  return config;
}

/**
 * 构建请求头
 */
export function buildHeaders(): HeadersInit {
  return {
    'Content-Type': 'application/json',
    Authorization: `Bearer ${config.apiKey}`,
  };
}

/**
 * 构建完整 URL
 */
export function buildUrl(path: string): string {
  const base = config.apiBaseUrl.replace(/\/$/, '');
  return `${base}${path}`;
}
