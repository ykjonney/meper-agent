import React, { useState } from 'react';
import { Cpu } from 'lucide-react';
import { useAppState } from '../AppContext';
import { useTheme } from '../ThemeContext';
import { useTranslation } from '../LocaleContext';
import {
  Card, Form, Input, Button, Select, Typography, Alert
} from 'antd';
import {
  UserOutlined, LockOutlined, MailOutlined, UserAddOutlined
} from '@ant-design/icons';

const { Title, Text } = Typography;

export const RegisterPage: React.FC = () => {
  const { register, setAuthView, roles } = useAppState();
  const { isDark } = useTheme();
  const { t } = useTranslation();
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [form] = Form.useForm();

  const defaultRoleId = roles.find(r => !r.isSystem)?.id || roles[0]?.id || '';

  const handleSubmit = (values: { username: string; email: string; password: string; confirmPassword: string; roleId: string }) => {
    setError('');

    if (values.username.trim().length < 3) {
      setError(t('auth.usernameMinLength'));
      return;
    }
    if (values.password !== values.confirmPassword) {
      setError(t('auth.passwordMismatch'));
      return;
    }

    setLoading(true);
    setTimeout(() => {
      const ok = register({
        username: values.username.trim(),
        email: values.email.trim(),
        password: values.password,
        roleIds: [values.roleId],
      });
      if (!ok) {
        setError(t('auth.registerFailed'));
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
          <Title level={5} style={{ margin: 0 }}>{t('auth.registerTitle')}</Title>
          <Text type="secondary" className="text-xs block mb-5">{t('auth.registerSubtitle')}</Text>

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
            initialValues={{ roleId: defaultRoleId }}
          >
            <Form.Item
              name="username"
              rules={[
                { required: true, message: t('auth.usernameRequired') },
                { min: 3, message: t('auth.usernameMinLength') },
              ]}
            >
              <Input
                prefix={<UserOutlined />}
                placeholder={t('auth.usernameMin3')}
              />
            </Form.Item>

            <Form.Item
              name="email"
              rules={[
                { required: true, message: t('auth.emailRequired') },
                { type: 'email', message: t('auth.emailInvalid') },
              ]}
            >
              <Input
                prefix={<MailOutlined />}
                placeholder="your@email.com"
              />
            </Form.Item>

            <Form.Item
              name="password"
              rules={[
                { required: true, message: t('auth.passwordRequired') },
                { min: 4, message: t('auth.passwordMinLength') },
              ]}
            >
              <Input.Password
                prefix={<LockOutlined />}
                placeholder={t('auth.passwordMin4')}
              />
            </Form.Item>

            <Form.Item
              name="confirmPassword"
              dependencies={['password']}
              rules={[
                { required: true, message: t('auth.confirmPassword') },
                ({ getFieldValue }) => ({
                  validator(_, value) {
                    if (!value || getFieldValue('password') === value) {
                      return Promise.resolve();
                    }
                    return Promise.reject(new Error(t('auth.passwordMismatch')));
                  },
                }),
              ]}
            >
              <Input.Password
                prefix={<LockOutlined />}
                placeholder={t('auth.confirmAgain')}
              />
            </Form.Item>

            <Form.Item
              name="roleId"
              rules={[{ required: true, message: t('auth.roleRequired') }]}
            >
              <Select
                options={roles.map(role => ({
                  label: `${role.name} — ${role.description}`,
                  value: role.id,
                }))}
                placeholder={t('auth.selectRole')}
                              />
            </Form.Item>

            <Form.Item style={{ marginBottom: 0 }}>
              <Button
                type="primary"
                htmlType="submit"
                loading={loading}
                icon={<UserAddOutlined />}
                block
              >
                {t('auth.registerBtn')}
              </Button>
            </Form.Item>
          </Form>

          <div className="mt-5 pt-4 text-center" style={{ borderTop: isDark ? '1px solid #303030' : '1px solid #f0f0f0' }}>
            <Text type="secondary" className="text-xs">{t('auth.hasAccount')}</Text>
            <Button
              type="link"
              size="small"
              className="text-xs p-0 ml-1"
              onClick={() => setAuthView('login')}
            >
              {t('auth.backToLogin')}
            </Button>
          </div>
        </Card>
      </div>
    </div>
  );
};
