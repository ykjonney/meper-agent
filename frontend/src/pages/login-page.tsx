/**
 * Login page — standalone (no AppLayout shell).
 *
 * Handles:
 * - Login form with username/password
 * - Error display for 401 responses
 * - Redirect to ?redirect param or /dashboard on success
 * - Redirect to /dashboard if already authenticated
 */
import { useState, type FormEvent } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Form, Input, Button, Alert, Typography } from 'antd'
import { UserOutlined, LockOutlined } from '@ant-design/icons'

import { useAuthStore, REFRESH_TOKEN_KEY } from '../stores/auth-store'
import { authApi } from '../services/auth-api'
import { decodeAccessToken } from '../lib/jwt'
import type { NormalizedApiError } from '../services/api-client'

const ERROR_CODE_MAP: Record<string, string> = {
  INVALID_CREDENTIALS: '用户名或密码错误',
  ACCOUNT_LOCKED: '账户已锁定，请稍后再试',
  ACCOUNT_DISABLED: '账户已禁用',
}

export function LoginPage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated)
  const setAuth = useAuthStore((s) => s.setAuth)

  const [loading, setLoading] = useState(false)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  // Already authenticated → redirect away
  if (isAuthenticated) {
    const redirect = searchParams.get('redirect') || '/dashboard'
    navigate(redirect, { replace: true })
    return null
  }

  const handleSubmit = async (values: { username: string; password: string }) => {
    setLoading(true)
    setErrorMessage(null)

    try {
      const { data } = await authApi.login(values.username, values.password)
      const payload = decodeAccessToken(data.access_token)

      if (!payload) {
        setErrorMessage('登录失败，服务器返回异常')
        return
      }

      // Store tokens
      localStorage.setItem(REFRESH_TOKEN_KEY, data.refresh_token)
      setAuth(data.access_token, {
        id: payload.sub,
        username: payload.username,
        role: payload.role,
      })

      const redirect = searchParams.get('redirect') || '/dashboard'
      navigate(redirect, { replace: true })
    } catch (err: unknown) {
      const apiError = err as NormalizedApiError | undefined
      const code = apiError?.code
      setErrorMessage(
        code && ERROR_CODE_MAP[code]
          ? ERROR_CODE_MAP[code]
          : apiError?.message ?? '登录失败，请检查用户名和密码',
      )
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex items-center justify-center min-h-screen bg-[#FAFAFA]">
      <div className="w-full max-w-[400px] px-6">
        <div className="bg-white rounded-xl shadow-[0_1px_3px_rgba(0,0,0,0.1)] p-8">
          {/* Header */}
          <div className="text-center mb-8">
            <Typography.Title
              level={2}
              className="!mb-1 !text-[#7C3AED]"
              style={{ fontFamily: "'Work Sans', sans-serif" }}
            >
              Agent Flow
            </Typography.Title>
            <Typography.Text type="secondary" className="text-sm">
              AI Agent 编排平台
            </Typography.Text>
          </div>

          {/* Error alert */}
          {errorMessage && (
            <Alert
              type="error"
              showIcon
              closable
              message={errorMessage}
              className="mb-4"
              onClose={() => setErrorMessage(null)}
            />
          )}

          {/* Login form */}
          <Form
            layout="vertical"
            onFinish={handleSubmit}
            validateTrigger={['onBlur', 'onSubmit']}
            size="large"
            autoComplete="off"
          >
            <Form.Item
              name="username"
              rules={[{ required: true, message: '请输入用户名' }]}
            >
              <Input
                prefix={<UserOutlined className="text-gray-400" />}
                placeholder="用户名"
                autoFocus
              />
            </Form.Item>

            <Form.Item
              name="password"
              rules={[{ required: true, message: '请输入密码' }]}
            >
              <Input.Password
                prefix={<LockOutlined className="text-gray-400" />}
                placeholder="密码"
              />
            </Form.Item>

            <Form.Item className="!mb-0">
              <Button
                type="primary"
                htmlType="submit"
                block
                loading={loading}
                className="h-10"
              >
                {loading ? '登录中...' : '登录'}
              </Button>
            </Form.Item>
          </Form>
        </div>
      </div>
    </div>
  )
}
