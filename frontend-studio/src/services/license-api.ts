/**
 * License API service — 离线授权激活向导 / 到期警告条数据源。
 *
 * 端点（app/api/v1/system.py，无鉴权——防线是 RSA-SHA256 验签而非登录态）：
 * - GET  /api/v1/system/license/status   状态（指纹/授权方/到期日/错误码）
 * - POST /api/v1/system/license/install  装入 license.key（text/plain 原文）
 * - GET  /api/v1/system/license/request  授权申请文件（JSON 下载）
 */
import { apiClient } from '../lib/api-client'

export interface LicenseStatus {
  activated: boolean
  enforced: boolean
  dev_mode: boolean
  code: string
  fingerprint: string
  licensee?: string | null
  edition?: string | null
  license_id?: string | null
  expires_at?: string | null
  days_left?: number | null
  expiring_soon: boolean
}

export const licenseKeys = {
  status: ['license', 'status'] as const,
}

/**
 * 错误码 → 用户可见文案。后端只回短码（二进制内零明文路标），
 * 映射统一维护在前端。
 */
export const LICENSE_ERROR_TEXT: Record<string, string> = {
  LIC_E_NOT_ACTIVATED: '系统尚未激活，请完成下方激活步骤',
  LIC_E_READ: '授权文件无法读取，请检查文件内容是否完整',
  LIC_E_SIGNATURE: '授权文件签名无效，请确认从官方渠道获取',
  LIC_E_FINGERPRINT: '授权与本机不匹配，请使用本机指纹重新申请',
  LIC_E_EXPIRED: '授权已到期，请联系供应商续费后更新授权',
}

export function licenseErrorText(code: string): string {
  return LICENSE_ERROR_TEXT[code] ?? '授权校验失败，请联系技术支持'
}

export const licenseApi = {
  status: () => apiClient.get<LicenseStatus>('/api/v1/system/license/status'),

  install: (content: string) =>
    apiClient.post<LicenseStatus>('/api/v1/system/license/install', content, {
      headers: { 'Content-Type': 'text/plain' },
    }),

  requestFile: () =>
    apiClient.get<Blob>('/api/v1/system/license/request', { responseType: 'blob' }),
}
