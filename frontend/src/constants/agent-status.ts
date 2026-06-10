/**
 * Shared agent status style constants.
 *
 * Simple { label, color, bg } mapping used by agents-page, drawer, and form.
 * For richer badges with icons, use components/status-badge.tsx instead.
 */

export interface StatusStyle {
  label: string
  color: string
  bg: string
}

export const AGENT_STATUS_STYLES: Record<string, StatusStyle> = {
  draft: { label: '草稿', color: '#94A3B8', bg: '#F1F5F9' },
  published: { label: '已发布', color: '#10B981', bg: '#D1FAE5' },
  archived: { label: '已归档', color: '#64748B', bg: '#F1F5F9' },
}
