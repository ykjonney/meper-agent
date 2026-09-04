/**
 * 首绑门页 —— apikey 模式下「未授权该应用」（EXT_USER_NOT_BOUND）时的
 * 自助授权页，替代旧的死胡同提示页。
 *
 * 两条路径（二选一）：
 * ① 直接授权（默认）：填应用账号（默认带出 introspection 用户名，可改）
 *   + 密码，后端自动开通平台账号；
 * ② 关联已有平台账号（折叠展开）：额外验证平台账号密码（复用登录校验
 *   防爆破），身份挂到已有账号——历史会话/文件无缝延续。
 *
 * 账号默认 ext_username 但允许修改（登录名与 introspection 返回值不同
 * 的场景）；凭证仍经应用 login_url 真实验证。授权成功后回调 onBound。
 */
import { useEffect, useState } from 'react'
import { Button, Form, Input, Spin, Typography, message } from 'antd'
import { SafetyCertificateOutlined } from '@ant-design/icons'

import { useAuthStore } from '../store/auth'
import { authorizeApp, fetchAuthBootstrap } from '../api/authorizations'
import type { AuthBootstrap } from '../types'

interface Props {
  onBound: () => void
}

interface GateFormValues {
  username?: string
  password: string
  claimPlatformUsername?: string
  claimPlatformPassword?: string
}

export function BindingGatePage({ onBound }: Props) {
  const theme = useAuthStore((state) => state.theme)
  const isDark = theme === 'dark'
  const [boot, setBoot] = useState<AuthBootstrap | null>(null)
  const [loadError, setLoadError] = useState('')
  const [showClaim, setShowClaim] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [form] = Form.useForm<GateFormValues>()

  useEffect(() => {
    fetchAuthBootstrap()
      .then(setBoot)
      .catch((error: unknown) => {
        setLoadError(
          error instanceof Error ? error.message : '加载应用信息失败',
        )
      })
  }, [])

  const handleSubmit = async (values: GateFormValues) => {
    if (!boot) return
    setSubmitting(true)
    try {
      const claim =
        showClaim && values.claimPlatformUsername && values.claimPlatformPassword
          ? {
              claimPlatformUsername: values.claimPlatformUsername,
              claimPlatformPassword: values.claimPlatformPassword,
            }
          : {}
      await authorizeApp(boot.app.id, {
        username: values.username?.trim() || boot.ext_username,
        password: values.password,
        ...claim,
      })
      message.success('授权成功，正在进入对话…')
      onBound()
    } catch (error) {
      message.error(
        error instanceof Error ? error.message : '授权失败，请检查密码',
      )
    } finally {
      setSubmitting(false)
    }
  }

  const cardStyle: React.CSSProperties = {
    minHeight: '100vh',
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    padding: 24,
    background: isDark ? '#0f172a' : '#f8fafc',
  }
  const panelStyle: React.CSSProperties = {
    width: 380,
    maxWidth: '100%',
    padding: 28,
    borderRadius: 16,
    background: isDark ? '#1e293b' : '#ffffff',
    boxShadow: '0 8px 30px rgba(0, 0, 0, 0.12)',
  }

  return (
    <div style={cardStyle}>
      <div style={panelStyle}>
        {boot === null ? (
          loadError ? (
            <Typography.Text type="danger">{loadError}</Typography.Text>
          ) : (
            <div style={{ textAlign: 'center', padding: 32 }}>
              <Spin />
            </div>
          )
        ) : (
          <>
            <div style={{ textAlign: 'center', marginBottom: 20 }}>
              <div
                style={{
                  width: 52,
                  height: 52,
                  borderRadius: '50%',
                  display: 'grid',
                  placeItems: 'center',
                  margin: '0 auto 12px',
                  background: isDark ? '#1e3a5f66' : '#e0ecf8',
                  color: '#315f92',
                  fontSize: 26,
                }}
              >
                <SafetyCertificateOutlined />
              </div>
              <Typography.Title level={4} style={{ margin: 0 }}>
                授权「{boot.app.name || '应用'}」
              </Typography.Title>
              <Typography.Paragraph
                type="secondary"
                style={{ marginBottom: 0, fontSize: 13 }}
              >
                首次使用需完成一次授权，之后 Agent 可在该应用内以你的身份
                执行操作。授权只需这一次。
              </Typography.Paragraph>
            </div>

            <Form
              form={form}
              layout="vertical"
              initialValues={{ username: boot.ext_username }}
              onFinish={(values) => void handleSubmit(values)}
            >
              <Form.Item
                name="username"
                label={`「${boot.app.name || '该应用'}」账号`}
                rules={[{ required: true, message: '请输入该应用的账号' }]}
              >
                <Input placeholder={`「${boot.app.name || '该应用'}」账号`} autoComplete="off" />
              </Form.Item>
              <Form.Item
                name="password"
                label={`「${boot.app.name || '该应用'}」密码`}
                rules={[{ required: true, message: '请输入该应用的登录密码' }]}
              >
                <Input.Password
                  placeholder={`「${boot.app.name || '该应用'}」密码`}
                  autoComplete="new-password"
                  autoFocus
                />
              </Form.Item>

              {showClaim ? (
                <>
                  <Typography.Paragraph
                    type="secondary"
                    style={{ fontSize: 12, marginBottom: 12 }}
                  >
                    验证平台账号后，授权将关联到你的已有账号——此前的会话与
                    文件会延续到当前身份。
                  </Typography.Paragraph>
                  <Form.Item
                    name="claimPlatformUsername"
                    label="平台账号"
                    rules={[{ required: true, message: '请输入平台账号' }]}
                  >
                    <Input placeholder="平台账号" autoComplete="off" />
                  </Form.Item>
                  <Form.Item
                    name="claimPlatformPassword"
                    label="平台密码"
                    rules={[{ required: true, message: '请输入平台密码' }]}
                  >
                    <Input.Password
                      placeholder="平台密码"
                      autoComplete="current-password"
                    />
                  </Form.Item>
                </>
              ) : null}

              <Button
                type="primary"
                htmlType="submit"
                loading={submitting}
                block
                size="large"
              >
                完成授权
              </Button>
              <Button
                type="link"
                block
                onClick={() => setShowClaim((value) => !value)}
              >
                {showClaim ? '使用新账号（无需平台账号）' : '已有平台账号？关联已有账号'}
              </Button>
            </Form>
          </>
        )}
      </div>
    </div>
  )
}
