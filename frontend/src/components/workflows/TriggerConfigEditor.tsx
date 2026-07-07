/**
 * TriggerConfigEditor — 触发配置主编辑器。
 *
 * 整合类型选择（Cron / 一次性）、Cron 预设、时间点、默认参数、启用开关，
 * 并提供下次/上次执行时间的只读展示以及保存/删除操作。
 *
 * 通过 WorkflowTriggerAPI 与后端同步。
 */
import { useState, useEffect, useCallback } from 'react'
import {
  Switch,
  Button,
  DatePicker,
  Spin,
  Alert,
  Typography,
  Radio,
  Popconfirm,
  Divider,
  message,
  Space,
} from 'antd'
import {
  SaveOutlined,
  DeleteOutlined,
  ClockCircleOutlined,
  CalendarOutlined,
  ReloadOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'

import { WorkflowTriggerAPI } from '@/services/workflow-trigger-api'
import type { TriggerConfig, TriggerType } from '@/types/workflow-trigger'
import CronPresetSelector from './CronPresetSelector'
import DefaultInputEditor from './DefaultInputEditor'

const { Text, Title } = Typography

interface Props {
  workflowId: string
}

/** 触发器类型的展示标签 */
const TYPE_LABELS: Record<TriggerType, string> = {
  cron: 'Cron 重复',
  once: '一次性执行',
}

export default function TriggerConfigEditor({ workflowId }: Props) {
  /* ─── 数据加载 ─── */
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [config, setConfig] = useState<TriggerConfig | null>(null)

  /* ─── 本地表单状态 ─── */
  const [type, setType] = useState<TriggerType>('cron')
  const [enabled, setEnabled] = useState(false)
  const [cronExpression, setCronExpression] = useState<string>('')
  const [executeAt, setExecuteAt] = useState<dayjs.Dayjs | null>(null)
  const [defaultInput, setDefaultInput] = useState<Record<string, any>>({})
  const [dirty, setDirty] = useState(false)
  const [saving, setSaving] = useState(false)

  /* ─── 加载现有配置 ─── */
  const loadConfig = useCallback(async () => {
    setLoading(true)
    setLoadError(null)
    try {
      const data = await WorkflowTriggerAPI.getTrigger(workflowId)
      setConfig(data)
      setType(data.type)
      setEnabled(data.enabled)
      setCronExpression(data.cron_expression ?? '')
      setExecuteAt(data.execute_at ? dayjs(data.execute_at) : null)
      setDefaultInput(data.default_input ?? {})
      setDirty(false)
    } catch (err) {
      // 404 视为"未配置"，不报错
      // apiClient normalizes errors → status lives on `statusCode`
      const status =
        (err as { statusCode?: number })?.statusCode ??
        (err as { response?: { status?: number } })?.response?.status
      if (status === 404) {
        setConfig(null)
        setDirty(false)
      } else {
        const msg = (err as { message?: string })?.message ?? '加载触发配置失败'
        setLoadError(msg)
      }
    } finally {
      setLoading(false)
    }
  }, [workflowId])

  useEffect(() => {
    void loadConfig()
  }, [loadConfig])

  /* ─── 表单变更 ─── */
  const handleTypeChange = (t: TriggerType) => {
    setType(t)
    setDirty(true)
  }

  const handleCronChange = (v: string) => {
    setCronExpression(v)
    setDirty(true)
  }

  const handleDateChange = (d: dayjs.Dayjs | null) => {
    setExecuteAt(d)
    setDirty(true)
  }

  const handleDefaultInputChange = (v: Record<string, any>) => {
    setDefaultInput(v)
    setDirty(true)
  }

  const handleEnabledChange = async (checked: boolean) => {
    setEnabled(checked)
    // 若已有配置，启用/禁用可直接通过 toggle 接口生效
    if (config) {
      try {
        const updated = await WorkflowTriggerAPI.toggleTrigger(workflowId, checked)
        setConfig(updated)
        setEnabled(updated.enabled)
        message.success(checked ? '触发器已启用' : '触发器已停用')
      } catch (err) {
        const msg = (err as { message?: string })?.message ?? '切换状态失败'
        message.error(msg)
        setEnabled(!checked)
      }
    } else {
      setDirty(true)
    }
  }

  /* ─── 保存 ─── */
  const handleSave = async () => {
    // 校验
    if (type === 'cron' && !cronExpression.trim()) {
      message.warning('请选择或输入 Cron 表达式')
      return
    }
    if (type === 'once' && !executeAt) {
      message.warning('请选择执行时间')
      return
    }

    setSaving(true)
    try {
      const payload: Partial<TriggerConfig> = {
        type,
        enabled,
        default_input: defaultInput,
      }
      if (type === 'cron') {
        payload.cron_expression = cronExpression.trim()
      } else {
        payload.execute_at = executeAt!.toISOString()
      }
      const updated = await WorkflowTriggerAPI.updateTrigger(workflowId, payload)
      setConfig(updated)
      setType(updated.type)
      setEnabled(updated.enabled)
      setCronExpression(updated.cron_expression ?? '')
      setExecuteAt(updated.execute_at ? dayjs(updated.execute_at) : null)
      setDefaultInput(updated.default_input ?? {})
      setDirty(false)
      message.success('触发配置已保存')
    } catch (err) {
      const msg = (err as { message?: string })?.message ?? '保存失败'
      message.error(msg)
    } finally {
      setSaving(false)
    }
  }

  /* ─── 删除 ─── */
  const handleDelete = async () => {
    try {
      await WorkflowTriggerAPI.deleteTrigger(workflowId)
      setConfig(null)
      setType('cron')
      setEnabled(false)
      setCronExpression('')
      setExecuteAt(null)
      setDefaultInput({})
      setDirty(false)
      message.success('触发配置已删除')
    } catch (err) {
      const msg = (err as { message?: string })?.message ?? '删除失败'
      message.error(msg)
    }
  }

  /* ─── 渲染 ─── */
  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Spin tip="加载触发配置..." />
      </div>
    )
  }

  if (loadError) {
    return <Alert message={loadError} type="error" showIcon className="!rounded-lg" />
  }

  return (
    <div className="flex flex-col gap-5 max-w-[680px]">
      {/* 标题 */}
      <div className="flex items-center justify-between">
        <Title level={5} className="!mb-0 !text-[#0F172A]">
          定时触发
        </Title>
        <div className="flex items-center gap-2">
          <Text className="text-xs text-[#64748B]">启用</Text>
          <Switch size="small" checked={enabled} onChange={handleEnabledChange} />
        </div>
      </div>

      {/* 类型选择 */}
      <div className="flex flex-col gap-2">
        <Text className="text-xs font-medium text-[#64748B]">触发类型</Text>
        <Radio.Group
          value={type}
          onChange={(e) => handleTypeChange(e.target.value)}
          optionType="button"
          buttonStyle="solid"
        >
          <Radio.Button value="cron">{TYPE_LABELS.cron}</Radio.Button>
          <Radio.Button value="once">{TYPE_LABELS.once}</Radio.Button>
        </Radio.Group>
      </div>

      {/* Cron 配置 */}
      {type === 'cron' && (
        <div className="flex flex-col gap-2">
          <Text className="text-xs font-medium text-[#64748B]">执行频率</Text>
          <CronPresetSelector
            value={cronExpression}
            onChange={handleCronChange}
            placeholder="选择 Cron 预设…"
          />
        </div>
      )}

      {/* 一次性配置 */}
      {type === 'once' && (
        <div className="flex flex-col gap-2">
          <Text className="text-xs font-medium text-[#64748B]">执行时间</Text>
          <DatePicker
            showTime
            value={executeAt}
            onChange={handleDateChange}
            placeholder="选择执行时间"
            format="YYYY-MM-DD HH:mm"
            className="!w-full"
          />
        </div>
      )}

      {/* 默认参数 */}
      <div className="flex flex-col gap-2">
        <Text className="text-xs font-medium text-[#64748B]">默认输入参数</Text>
        <DefaultInputEditor
          value={defaultInput}
          onChange={handleDefaultInputChange}
        />
      </div>

      {/* 状态展示 */}
      {config && (
        <>
          <Divider className="!my-2" />
          <div className="flex flex-col gap-1.5 text-xs text-[#64748B]">
            <div className="flex items-center gap-1.5">
              <ClockCircleOutlined className="text-[#94A3B8]" />
              <span>上次触发：</span>
              <span className="text-[#0F172A]">
                {config.last_triggered_at
                  ? dayjs(config.last_triggered_at).format('YYYY-MM-DD HH:mm')
                  : '—'}
              </span>
            </div>
            <div className="flex items-center gap-1.5">
              <CalendarOutlined className="text-[#94A3B8]" />
              <span>下次触发：</span>
              <span className="text-[#0F172A]">
                {config.next_trigger_at
                  ? dayjs(config.next_trigger_at).format('YYYY-MM-DD HH:mm')
                  : '—'}
              </span>
            </div>
            {config.updated_at && (
              <div className="flex items-center gap-1.5">
                <ReloadOutlined className="text-[#94A3B8]" />
                <span>最近更新：</span>
                <span className="text-[#0F172A]">
                  {dayjs(config.updated_at).format('YYYY-MM-DD HH:mm')}
                </span>
              </div>
            )}
          </div>
        </>
      )}

      {/* 操作按钮 */}
      <Divider className="!my-2" />
      <Space>
        <Button
          type="primary"
          icon={<SaveOutlined />}
          onClick={handleSave}
          loading={saving}
          disabled={!dirty}
        >
          保存
        </Button>
        <Popconfirm
          title="删除该触发配置？"
          description="删除后触发器将停止工作。"
          onConfirm={handleDelete}
          okText="删除"
          cancelText="取消"
          okButtonProps={{ danger: true }}
          disabled={!config}
        >
          <Button
            danger
            icon={<DeleteOutlined />}
            disabled={!config}
          >
            删除
          </Button>
        </Popconfirm>
      </Space>
    </div>
  )
}
