/**
 * 首绑门页 —— apikey 模式下「未授权该应用」（EXT_USER_NOT_BOUND）时的
 * 自助授权页，替代旧的死胡同提示页。
 *
 * 默认路径（自动开通，用户明确知晓）：
 * 只填当前网站密码；提交即①验证应用凭证，②若无平台账号则以「同账户
 * 密码」自动创建 Agent 平台账号（ext_user 角色）。创建行为经下方勾选
 * 明确告知并须用户主动确认——绝不无感建号。
 *
 * 备选路径（折叠展开「关联已有账号」）：额外验证平台账号密码
 * （claim，复用平台登录校验防爆破），身份挂到已有账号——适合用户名
 * 已有平台账号但密码不同（后端报 PLATFORM_USERNAME_TAKEN 时引导至此）
 * 或跨设备延续会话的场景。
 *
 * 应用账号固定为 introspection 带出的当前网站账号（不可改）；凭证经
 * 应用 login_url 真实验证。授权成功后回调 onBound。
 */
import { useEffect, useState } from 'react'
import { Button, Checkbox, Form, Input, Spin, Typography, message } from 'antd'
import { SafetyCertificateOutlined } from '@ant-design/icons'

import { useAuthStore } from '../store/auth'
import { authorizeApp, fetchAuthBootstrap } from '../api/authorizations'
import type { AuthBootstrap } from '../types'

interface Props {
  onBound: () => void
}

interface GateFormValues {
  password: string
  claimPlatformUsername?: string
  claimPlatformPassword?: string
}

export function BindingGatePage({ onBound }: Props) {
  const theme = useAuthStore((state) => state.theme)
  const isDark = theme === 'dark'
  const [boot, setBoot] = useState<AuthBootstrap | null>(null)
  const [loadError, setLoadError] = useState('')
  /** 展开「关联已有账号」（claim）路径；收起时为自动开通（建号）路径。 */
  const [showClaim, setShowClaim] = useState(false)
  /** 自动建号的知情确认（默认不勾，勾选前不能提交——创建绝不无感）。 */
  const [agreeCreate, setAgreeCreate] = useState(false)
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
        // 应用账号固定为当前网站账号（introspection 用户名，不可改）
        username: boot.ext_username,
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
  // 分区容器：浅底圆角卡，营造分区感
  const sectionStyle: React.CSSProperties = {
    background: isDark ? '#0b1729' : '#f4f7fa',
    borderRadius: 10,
    padding: '4px 12px 4px',
    marginBottom: 16,
  }
  const sectionTitleStyle: React.CSSProperties = {
    display: 'block',
    fontSize: 12,
    fontWeight: 600,
    margin: '10px 2px 8px',
    color: isDark ? '#94a3b8' : '#475569',
  }
  // 分区内字段间隙收紧（antd 默认 24 → 10）
  const compactItemStyle: React.CSSProperties = { marginBottom: 10 }

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
                应用授权
              </Typography.Title>
              <Typography.Paragraph
                type="secondary"
                style={{ marginBottom: 0, fontSize: 13 }}
              >
                首次使用需完成一次授权，之后 Agent 可在当前应用内以你的
                身份执行操作。授权只需这一次。
              </Typography.Paragraph>
            </div>

            <Form
              form={form}
              layout="vertical"
              onFinish={(values) => void handleSubmit(values)}
            >
              {showClaim ? (
                /* 关联路径：平台账号分区（claim） */
                <div style={sectionStyle}>
                  <Typography.Text style={sectionTitleStyle}>
                    Agent 平台账号
                  </Typography.Text>
                  <Form.Item
                    name="claimPlatformUsername"
                    style={compactItemStyle}
                    rules={[{ required: true, message: '请输入 Agent 平台账号' }]}
                  >
                    <Input placeholder="Agent 平台账号" autoComplete="off" />
                  </Form.Item>
                  <Form.Item
                    name="claimPlatformPassword"
                    style={compactItemStyle}
                    rules={[{ required: true, message: '请输入 Agent 平台密码' }]}
                  >
                    <Input.Password
                      placeholder="Agent 平台密码"
                      autoComplete="current-password"
                    />
                  </Form.Item>
                </div>
              ) : null}

              {/* 当前网站凭证（账号固定，仅填密码） */}
              <div style={sectionStyle}>
                <Typography.Text style={sectionTitleStyle}>
                  当前网站
                </Typography.Text>
                <Form.Item style={compactItemStyle}>
                  <Input
                    value={boot.ext_username}
                    disabled
                    placeholder="当前网站账号"
                    autoComplete="off"
                  />
                </Form.Item>
                <Form.Item
                  name="password"
                  style={compactItemStyle}
                  rules={[{ required: true, message: '请输入当前网站的登录密码' }]}
                >
                  <Input.Password
                    placeholder="当前网站的登录密码"
                    autoComplete="new-password"
                    autoFocus
                  />
                </Form.Item>
              </div>

              {showClaim ? (
                <Typography.Paragraph
                  type="secondary"
                  style={{ fontSize: 12, marginBottom: 16 }}
                >
                  验证 Agent 平台账号后，授权将关联到该账号——此前的会话
                  与文件会延续到当前身份。
                </Typography.Paragraph>
              ) : (
                /* 知情确认：自动建号绝不无感，勾选前不能提交 */
                <div style={{ marginBottom: 16 }}>
                  <Checkbox
                    checked={agreeCreate}
                    onChange={(e) => setAgreeCreate(e.target.checked)}
                  >
                    <Typography.Text style={{ fontSize: 12 }}>
                      我知晓：将自动为我创建 Agent 平台账号
                    </Typography.Text>
                  </Checkbox>
                  <Typography.Paragraph
                    type="secondary"
                    style={{ fontSize: 12, margin: '6px 0 0 24px' }}
                  >
                    账号与密码同当前网站（{boot.ext_username ||
                    '当前网站账号'}
                    ），用于在各应用间延续你的会话与文件。
                  </Typography.Paragraph>
                </div>
              )}

              <Button
                type="primary"
                htmlType="submit"
                loading={submitting}
                block
                size="large"
                disabled={!showClaim && !agreeCreate}
              >
                完成授权
              </Button>
              <Button
                type="link"
                block
                onClick={() => setShowClaim((value) => !value)}
              >
                {showClaim
                  ? '我没有平台账号（自动创建）'
                  : '已有 Agent 平台账号？关联已有账号'}
              </Button>
            </Form>
          </>
        )}
      </div>
    </div>
  )
}
