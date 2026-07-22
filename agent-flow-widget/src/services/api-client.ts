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
  const headers: HeadersInit = {
    'Content-Type': 'application/json',
    Authorization: `Bearer ${config.apiKey}`,
  };

  // 回调验证模式：API Key 配置了 user_info_url 时，
  // 终端用户 token 通过 X-User-Token 透传给后端做 introspection 校验。
  // 后端 _extract_bearer_token 接受 "Bearer xxx" 或裸 token，这里统一带 Bearer 前缀。
  if (config.userToken) {
    headers['X-User-Token'] = `Bearer ${config.userToken}`;
  }

  return headers;
}

/**
 * 构建完整 URL
 */
export function buildUrl(path: string): string {
  const base = config.apiBaseUrl.replace(/\/$/, '');
  return `${base}${path}`;
}
