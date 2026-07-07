export type TriggerType = 'cron' | 'once'

export interface TriggerConfig {
  type: TriggerType
  enabled: boolean
  cron_expression?: string
  execute_at?: string
  default_input: Record<string, any>
  last_triggered_at?: string
  next_trigger_at?: string
  created_at: string
  updated_at: string
}

export interface CronPreset {
  label: string
  value: string
  cron: string
}

export const CRON_PRESETS: CronPreset[] = [
  { label: '每小时', value: 'hourly', cron: '0 * * * *' },
  { label: '每天 09:00', value: 'daily_9', cron: '0 9 * * *' },
  { label: '每周一 09:00', value: 'weekly_mon_9', cron: '0 9 * * 1' },
  { label: '每月 1 号 09:00', value: 'monthly_1_9', cron: '0 9 1 * *' },
]
