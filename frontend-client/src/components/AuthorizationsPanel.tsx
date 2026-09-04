/**
 * 应用授权面板 —— 管理当前用户对各外部应用的授权（绑定/更新/解绑）。
 *
 * 两种鉴权模式共用（API 路径差异封装在 api/authorizations.ts）：
 * - jwt 模式：平台用户自服务
 * - apikey 模式：终端用户自服务；key 对应应用的 username 默认带出身份
 *   用户名（可改，凭证经应用 login_url 校验），其他应用自由填写。
 */
import { useCallback, useEffect, useState } from 'react'
import {
  Alert,
  Button,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Typography,
  message,
} from 'antd'

import { AUTH_MODE } from '../api/client'
import {
  authorizeApp,
  fetchAuthBootstrap,
  fetchAvailableApps,
  fetchMyAuthorizations,
  revokeApp,
} from '../api/authorizations'
import type { AvailableApp } from '../types'

interface Props {
  open: boolean
  onClose: () => void
}

interface BindFormValues {
  appId: string
  username: string
  password: string
}

export function AuthorizationsPanel({ open, onClose }: Props) {
  const [loading, setLoading] = useState(false)
  const [apps, setApps] = useState<AvailableApp[]>([])
  const [keyAppId, setKeyAppId] = useState<string | undefined>(undefined)
  /** apikey 模式下 key 应用的锁定用户名（introspection 身份）。 */
  const [extUsername, setExtUsername] = useState('')
  const [bindings, setBindings] = useState<
    { app_id: string; app_name: string; username: string; password_masked: string }[]
  >([])
  const [submitting, setSubmitting] = useState(false)
  const [form] = Form.useForm<BindFormValues>()
  const selectedAppId = Form.useWatch('appId', form)
  /** 当前选中应用名——账号/密码字段 label 随之带上应用名，与"平台账号"
   * （认领场景）仅靠命名区分，不加说明文字。 */
  const selectedAppName =
    apps.find((app) => app.id === selectedAppId)?.name || ''

  const reload = useCallback(async () => {
    setLoading(true)
    try {
      const [listResult, appsResult] = await Promise.all([
        fetchMyAuthorizations(),
        fetchAvailableApps(),
      ])
      setBindings(listResult.bindings)
      setApps(appsResult.items)
      setKeyAppId(appsResult.keyAppId)
    } catch {
      message.error('加载授权信息失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (!open) return
    void reload()
    // apikey 模式预取身份用户名（key 应用 username 锁定用）
    if (AUTH_MODE === 'apikey') {
      fetchAuthBootstrap()
        .then((boot) => setExtUsername(boot.ext_username))
        .catch(() => setExtUsername(''))
    } else {
      setExtUsername('')
    }
  }, [open, reload])

  /** key 对应应用：username 默认带出身份用户名（可改——登录名可能与
   * introspection 返回值不同；凭证经应用 login_url 校验，身份锚不受影响）。 */
  const isKeyApp = AUTH_MODE === 'apikey' && selectedAppId === keyAppId

  useEffect(() => {
    // 切到 key 应用时把身份用户名带作默认值（用户可改）
    if (isKeyApp && extUsername) {
      form.setFieldValue('username', extUsername)
    }
  }, [isKeyApp, extUsername, form])

  const handleSubmit = useCallback(
    async (values: BindFormValues) => {
      setSubmitting(true)
      try {
        const result = await authorizeApp(values.appId, {
          username: values.username,
          password: values.password,
        })
        setBindings(result.bindings)
        form.setFieldsValue({ password: '' })
        message.success('授权成功')
      } catch (error) {
        message.error(
          error instanceof Error ? error.message : '授权失败，请检查该应用的账号密码',
        )
      } finally {
        setSubmitting(false)
      }
    },
    [form],
  )

  const handleRevoke = useCallback(async (appId: string) => {
    try {
      const result = await revokeApp(appId)
      setBindings(result.bindings)
      message.success('已取消授权')
    } catch (error) {
      message.error(error instanceof Error ? error.message : '取消授权失败')
    }
  }, [])

  const boundAppIds = new Set(bindings.map((b) => b.app_id))

  return (
    <Modal
      title="应用授权"
      open={open}
      onCancel={onClose}
      footer={null}
      width={520}
      destroyOnHidden
    >
      {AUTH_MODE === 'apikey' ? (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message="授权后 Agent 可在你授权的应用内以你的身份执行操作。取消授权后相关能力将不可用。"
        />
      ) : null}

      <Typography.Text strong>已授权应用</Typography.Text>
      <div style={{ margin: '12px 0 24px' }}>
        {loading ? (
          <Typography.Text type="secondary">加载中…</Typography.Text>
        ) : bindings.length === 0 ? (
          <Typography.Text type="secondary">暂无授权应用</Typography.Text>
        ) : (
          <Space direction="vertical" style={{ width: '100%' }} size={8}>
            {bindings.map((binding) => (
              <div
                key={binding.app_id}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  gap: 12,
                  padding: '8px 12px',
                  borderRadius: 8,
                  background: 'rgba(127, 127, 127, 0.08)',
                }}
              >
                <div style={{ minWidth: 0 }}>
                  <Typography.Text strong>{binding.app_name || binding.app_id}</Typography.Text>
                  <Typography.Paragraph
                    type="secondary"
                    style={{ margin: 0, fontSize: 12 }}
                    ellipsis
                  >
                    {binding.username} · 密码 {binding.password_masked || '***'}
                  </Typography.Paragraph>
                </div>
                <Button
                  size="small"
                  danger
                  onClick={() => void handleRevoke(binding.app_id)}
                >
                  取消授权
                </Button>
              </div>
            ))}
          </Space>
        )}
      </div>

      <Typography.Text strong>{boundAppIds.size > 0 ? '绑定 / 更新应用' : '授权应用'}</Typography.Text>
      <Form
        form={form}
        layout="vertical"
        style={{ marginTop: 12 }}
        onFinish={(values) => void handleSubmit(values)}
      >
        <Form.Item
          name="appId"
          label="应用"
          rules={[{ required: true, message: '请选择应用' }]}
        >
          <Select
            placeholder="选择要授权的应用"
            options={apps.map((app) => ({
              value: app.id,
              label: `${app.name}${boundAppIds.has(app.id) ? '（已授权，可更新）' : ''}`,
            }))}
          />
        </Form.Item>
        <Form.Item
          name="username"
          label={selectedAppName ? `「${selectedAppName}」账号` : '账号'}
          rules={[{ required: true, message: '请输入该应用的登录账号' }]}
        >
          <Input
            placeholder={selectedAppName ? `「${selectedAppName}」账号` : '应用账号'}
            autoComplete="off"
          />
        </Form.Item>
        <Form.Item
          name="password"
          label={selectedAppName ? `「${selectedAppName}」密码` : '密码'}
          rules={[{ required: true, message: '请输入该应用的登录密码' }]}
        >
          <Input.Password
            placeholder={selectedAppName ? `「${selectedAppName}」密码` : '应用密码'}
            autoComplete="new-password"
          />
        </Form.Item>
        <Button type="primary" htmlType="submit" loading={submitting} block>
          完成授权
        </Button>
      </Form>
    </Modal>
  )
}
