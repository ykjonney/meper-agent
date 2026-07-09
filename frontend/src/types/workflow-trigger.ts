export type TriggerType = 'cron' | 'once'

export interface TriggerConfig {
  _id?: string
  id?: string
  workflow_id: string
  user_id?: string
  type: TriggerType
  enabled: boolean
  cron_expression?: string
  execute_at?: string
  default_input: Record<string, any>
  schedule_version?: number
  last_triggered_at?: string
  next_trigger_at?: string
  created_at: string
  updated_at: string
}

export type ScheduleFrequency = 'hourly' | 'daily' | 'weekly' | 'monthly' | 'custom'

export const WEEKDAY_LABELS = ['一', '二', '三', '四', '五', '六', '日']
