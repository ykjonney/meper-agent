import React, { useState } from 'react';
import { useAppState } from '../AppContext';
import { useTheme } from '../ThemeContext';
import {
  Mail, Phone, Building2, Calendar, Clock, Shield, Key
} from 'lucide-react';
import { useTranslation } from '../LocaleContext';
import {
  Card, Form, Input, Button, Tabs, Avatar, Tag, Space,
  Descriptions, Typography, Alert, message, Divider
} from 'antd';
import {
  EditOutlined, SaveOutlined, CloseOutlined,
  MailOutlined, PhoneOutlined, BankOutlined,
  CalendarOutlined, ClockCircleOutlined, KeyOutlined,
  LockOutlined, UserOutlined
} from '@ant-design/icons';

const { TextArea } = Input;
const { Title, Text, Paragraph } = Typography;

export const ProfilePage: React.FC = () => {
  const { currentUser, roles, updateProfile, changePassword } = useAppState();
  const { isDark } = useTheme();
  const { t } = useTranslation();

  const [profileForm] = Form.useForm();
  const [passwordForm] = Form.useForm();
  const [editing, setEditing] = useState(false);
  const [passwordError, setPasswordError] = useState('');
  const [passwordSuccess, setPasswordSuccess] = useState(false);

  if (!currentUser) return null;

  const userRoles = currentUser.roleIds.map(rid => roles.find(r => r.id === rid)).filter(Boolean);
  const initials = currentUser.username.slice(0, 1).toUpperCase();

  const getAvatarColor = (name: string) => {
    const colors = ['#1677ff', '#52c41a', '#faad14', '#f5222d', '#722ed1', '#13c2c2', '#eb2f96'];
    let hash = 0;
    for (let i = 0; i < name.length; i++) hash = name.charCodeAt(i) + ((hash << 5) - hash);
    return colors[Math.abs(hash) % colors.length];
  };

  const handleStartEdit = () => {
    profileForm.setFieldsValue({
      email: currentUser.email,
      phone: currentUser.phone || '',
      department: currentUser.department || '',
      bio: currentUser.bio || '',
    });
    setEditing(true);
  };

  const handleSaveProfile = () => {
    profileForm.validateFields().then(values => {
      updateProfile({
        email: values.email.trim(),
        phone: values.phone || undefined,
        department: values.department || undefined,
        bio: values.bio || undefined,
      });
      setEditing(false);
      message.success(t('profile.profileUpdated'));
    });
  };

  const handleCancelEdit = () => {
    setEditing(false);
  };

  const handleChangePassword = () => {
    passwordForm.validateFields().then(values => {
      setPasswordError('');
      setPasswordSuccess(false);

      if (values.newPassword.length < 4) {
        setPasswordError(t('profile.newPasswordMin'));
        return;
      }

      const ok = changePassword(values.oldPassword, values.newPassword);
      if (!ok) {
        setPasswordError(t('profile.currentPasswordWrong'));
      } else {
        setPasswordSuccess(true);
        passwordForm.resetFields();
        message.success(t('profile.passwordChangedShort'));
      }
    });
  };

  const tabItems = [
    {
      key: 'profile',
      label: (
        <span className="flex items-center gap-1.5">
          <UserOutlined />
          {t('profile.profileTab')}
        </span>
      ),
      children: (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Left: Profile summary */}
          <div className="lg:col-span-1">
            <Card
              className="text-center"
              style={{ background: isDark ? '#141414' : '#fafafa' }}
            >
              <Avatar
                size={64}
                style={{ backgroundColor: getAvatarColor(currentUser.username), marginBottom: 12 }}
              >
                <span className="text-2xl font-bold">{initials}</span>
              </Avatar>
              <Title level={5} style={{ margin: 0 }}>{currentUser.username}</Title>
              <Text type="secondary" className="text-xs block mb-3">{currentUser.email}</Text>

              <div className="flex flex-wrap gap-1.5 justify-center mb-4">
                {userRoles.map(role => role && (
                  <Tag key={role.id} color="blue">{role.name}</Tag>
                ))}
              </div>

              <Descriptions column={1} size="small" className="text-left">
                {currentUser.department && (
                  <Descriptions.Item label={<span className="flex items-center gap-1"><BankOutlined /> {t('profile.department')}</span>}>
                    <Text className="text-xs">{currentUser.department}</Text>
                  </Descriptions.Item>
                )}
                {currentUser.phone && (
                  <Descriptions.Item label={<span className="flex items-center gap-1"><PhoneOutlined /> {t('profile.phone')}</span>}>
                    <Text className="text-xs">{currentUser.phone}</Text>
                  </Descriptions.Item>
                )}
                <Descriptions.Item label={<span className="flex items-center gap-1"><CalendarOutlined /> {t('profile.registered')}</span>}>
                  <Text className="text-xs">{currentUser.createdAt}</Text>
                </Descriptions.Item>
                {currentUser.lastLoginAt && (
                  <Descriptions.Item label={<span className="flex items-center gap-1"><ClockCircleOutlined /> {t('profile.lastLogin')}</span>}>
                    <Text className="text-xs">{currentUser.lastLoginAt}</Text>
                  </Descriptions.Item>
                )}
              </Descriptions>
            </Card>
          </div>

          {/* Right: Edit form */}
          <div className="lg:col-span-2">
            <Card
              title={t('profile.profileTitle')}
              extra={
                editing ? (
                  <Space>
                    <Button size="small" icon={<CloseOutlined />} onClick={handleCancelEdit}>
                      {t('profile.cancelBtn')}
                    </Button>
                    <Button size="small" type="primary" icon={<SaveOutlined />} onClick={handleSaveProfile}>
                      {t('profile.saveBtn')}
                    </Button>
                  </Space>
                ) : (
                  <Button size="small" type="primary" ghost icon={<EditOutlined />} onClick={handleStartEdit}>
                    {t('profile.editBtn')}
                  </Button>
                )
              }
            >
              {editing ? (
                <Form
                  form={profileForm}
                  layout="vertical"
                >
                  <Form.Item
                    label={t('profile.emailLabel')}
                    name="email"
                    rules={[
                      { required: true, message: t('profile.emailRequired') },
                      { type: 'email', message: t('profile.emailInvalid') },
                    ]}
                  >
                    <Input prefix={<MailOutlined />} />
                  </Form.Item>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-x-4">
                    <Form.Item label={t('profile.phoneLabel')} name="phone">
                      <Input prefix={<PhoneOutlined />} placeholder={t('profile.phonePlaceholder')} />
                    </Form.Item>
                    <Form.Item label={t('profile.departmentLabel')} name="department">
                      <Input prefix={<BankOutlined />} placeholder={t('profile.departmentPlaceholder')} />
                    </Form.Item>
                  </div>
                  <Form.Item label={t('profile.bioLabel')} name="bio">
                    <TextArea rows={3} placeholder={t('profile.bioPlaceholder')} />
                  </Form.Item>
                </Form>
              ) : (
                <div className="space-y-3">
                  <div className="flex items-center gap-2 text-sm">
                    <MailOutlined style={{ color: isDark ? '#737373' : '#8c8c8c' }} />
                    <Text>{currentUser.email}</Text>
                  </div>
                  {currentUser.phone && (
                    <div className="flex items-center gap-2 text-sm">
                      <PhoneOutlined style={{ color: isDark ? '#737373' : '#8c8c8c' }} />
                      <Text>{currentUser.phone}</Text>
                    </div>
                  )}
                  {currentUser.department && (
                    <div className="flex items-center gap-2 text-sm">
                      <BankOutlined style={{ color: isDark ? '#737373' : '#8c8c8c' }} />
                      <Text>{currentUser.department}</Text>
                    </div>
                  )}
                  {currentUser.bio && (
                    <div
                      className="text-sm mt-2 px-4 py-2.5 rounded"
                      style={{ background: isDark ? '#262626' : '#fafafa' }}
                    >
                      {currentUser.bio}
                    </div>
                  )}
                </div>
              )}
            </Card>
          </div>
        </div>
      ),
    },
    {
      key: 'password',
      label: (
        <span className="flex items-center gap-1.5">
          <LockOutlined />
          {t('profile.passwordTab')}
        </span>
      ),
      children: (
        <Card
          title={
            <span className="flex items-center gap-2">
              <KeyOutlined />
              {t('profile.changePasswordTitle')}
            </span>
          }
          className="max-w-lg"
        >
          {passwordSuccess && (
            <Alert
              message={t('profile.passwordChanged')}
              type="success"
              showIcon
              className="mb-4"
            />
          )}

          {passwordError && (
            <Alert
              message={passwordError}
              type="error"
              showIcon
              className="mb-4"
              closable
              onClose={() => setPasswordError('')}
            />
          )}

          <Form
            form={passwordForm}
            layout="vertical"
          >
            <Form.Item
              label={t('profile.currentPassword')}
              name="oldPassword"
              rules={[{ required: true, message: t('profile.currentPasswordRequired') }]}
            >
              <Input.Password prefix={<LockOutlined />} placeholder={t('profile.currentPasswordRequired')} />
            </Form.Item>
            <Form.Item
              label={t('profile.newPassword')}
              name="newPassword"
              rules={[
                { required: true, message: t('profile.newPasswordRequired') },
                { min: 4, message: t('profile.newPasswordMin') },
              ]}
            >
              <Input.Password prefix={<LockOutlined />} placeholder={t('profile.newPasswordPlaceholder')} />
            </Form.Item>
            <Form.Item
              label={t('profile.confirmNewPassword')}
              name="confirmPassword"
              dependencies={['newPassword']}
              rules={[
                { required: true, message: t('profile.confirmPasswordRequired') },
                ({ getFieldValue }) => ({
                  validator(_, value) {
                    if (!value || getFieldValue('newPassword') === value) {
                      return Promise.resolve();
                    }
                    return Promise.reject(new Error(t('profile.passwordMismatch')));
                  },
                }),
              ]}
            >
              <Input.Password prefix={<LockOutlined />} placeholder={t('profile.confirmNewPasswordPlaceholder')} />
            </Form.Item>
            <Form.Item style={{ marginBottom: 0 }}>
              <Button
                type="primary"
                icon={<KeyOutlined />}
                onClick={handleChangePassword}
              >
                {t('profile.changePasswordBtn')}
              </Button>
            </Form.Item>
          </Form>
        </Card>
      ),
    },
  ];

  return (
    <div className="px-4 py-6">
      <Card size="small">
        <Tabs items={tabItems} />
      </Card>
    </div>
  );
};
