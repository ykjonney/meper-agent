import React, { useState } from 'react';
import { Cpu } from 'lucide-react';
import { useAppState } from '../AppContext';
import { useTheme } from '../ThemeContext';
import { useTranslation } from '../LocaleContext';
import {
  Card, Form, Input, Button, Typography, Alert
} from 'antd';
import {
  UserOutlined, LockOutlined, LoginOutlined
} from '@ant-design/icons';

const { Title, Text } = Typography;

export const LoginPage: React.FC = () => {
  const { login, setAuthView } = useAppState();
  const { isDark } = useTheme();
  const { t } = useTranslation();
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [form] = Form.useForm();

  const handleSubmit = (values: { username: string; password: string }) => {
    setError('');
    if (values.password.length < 4) {
      setError(t('auth.passwordMinLength'));
      return;
    }

    setLoading(true);
    setTimeout(() => {
      const ok = login(values.username, values.password);
      if (!ok) {
        setError(t('auth.loginFailed'));
      }
      setLoading(false);
    }, 600);
  };

  return (
    <div
      className="min-h-screen flex items-center justify-center p-4"
      style={{ background: isDark ? '#141414' : '#f5f5f5' }}
    >
      <div className="w-full max-w-sm">
        {/* Logo */}
        <div className="flex flex-col items-center mb-8">
          <div className="flex h-12 w-12 items-center justify-center rounded-lg bg-[#1677ff] text-white font-bold shadow-sm shadow-[#1677ff]/20 mb-3">
            <Cpu className="h-6 w-6" />
          </div>
          <Title level={4} style={{ margin: 0 }} className="tracking-tight">AgentPlat Console</Title>
          <Text type="secondary" className="text-xs font-mono mt-1">v1.1.0 · Web Portal</Text>
        </div>

        {/* Card */}
        <Card
          style={{
            background: isDark ? '#1f1f1f' : '#ffffff',
            borderColor: isDark ? '#303030' : '#f0f0f0',
          }}
        >
          <Title level={5} style={{ margin: 0 }}>{t('auth.loginTitle')}</Title>
          <Text type="secondary" className="text-xs block mb-5">{t('auth.loginSubtitle')}</Text>

          {error && (
            <Alert
              message={error}
              type="error"
              showIcon
              className="mb-4"
              closable
              onClose={() => setError('')}
            />
          )}

          <Form
            form={form}
            onFinish={handleSubmit}
            layout="vertical"
            size="large"
          >
            <Form.Item
              name="username"
              rules={[{ required: true, message: t('auth.usernameRequired') }]}
            >
              <Input
                prefix={<UserOutlined />}
                placeholder={t('auth.usernamePlaceholder')}
                autoComplete="username"
              />
            </Form.Item>

            <Form.Item
              name="password"
              rules={[{ required: true, message: t('auth.passwordRequired') }]}
            >
              <Input.Password
                prefix={<LockOutlined />}
                placeholder={t('auth.passwordPlaceholder')}
                autoComplete="current-password"
              />
            </Form.Item>

            <Form.Item style={{ marginBottom: 0 }}>
              <Button
                type="primary"
                htmlType="submit"
                loading={loading}
                icon={<LoginOutlined />}
                block
              >
                {t('auth.loginBtn')}
              </Button>
            </Form.Item>
          </Form>

          <div className="mt-5 pt-4 text-center" style={{ borderTop: isDark ? '1px solid #303030' : '1px solid #f0f0f0' }}>
            <Text type="secondary" className="text-xs">{t('auth.noAccount')}</Text>
            <Button
              type="link"
              size="small"
              className="text-xs p-0 ml-1"
              onClick={() => setAuthView('register')}
            >
              {t('auth.registerNow')}
            </Button>
          </div>
        </Card>

        {/* Hint */}
        <div className="mt-6 text-center">
          <Text type="secondary" className="text-xs">{t('auth.demoAccount')}</Text>
        </div>
      </div>
    </div>
  );
};
